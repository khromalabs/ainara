# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Deep Recall: deliberative memory investigation for past-event turns.

GREEN provides the reflexive tier: instant, cheap, lossy retrieval that
covers most turns. When the conversation reaches into past events, the
reflex tier routinely returns cherry-picked fragments — and the model
fills the gaps collaboratively, i.e. confabulates. Deep Recall is the
deliberative tier: a bounded, tool-using investigation loop over the two
local corpora (GREEN memories + conversation logs) that returns a
cited digest, so the model words the full picture instead of guessing.

Design notes:
- The conversation model triggers Deep Recall through the ordinary
  ORAKLE channel: it is exposed as a system skill
  (system_skills/deep_recall.py), so the existing tag contract,
  selection flow, skill_intention sentence and loading pill all apply.
  No dedicated tag, no pre-turn probe: zero added latency on turns that
  don't need recall.
- The loop is a bespoke mini ReAct here, not the Bureau Agent path: the
  corpus objects live in this process, and the offload-digestion
  transport (Bureau over HTTP) cannot reach them.
- The investigation tools are internal Python callables, deliberately
  OUTSIDE the Orakle skill system: they must never become routing
  candidates (core-bloat doctrine) and only make sense inside a recall
  loop.
- Text-marker protocol (<tool>/<final>) instead of native function
  calling: local/Ollama backends must work identically.
- Fail to silence: every failure path returns None and the turn simply
  proceeds on the reflex tier. Recall is an enhancement, never a gate.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from ainara.framework.config import config
from ainara.framework.storage.time_bounds import resolve_date_bound
from ainara.framework.template_manager import TemplateManager

logger = logging.getLogger(__name__)

# --- Tuning constants ---------------------------------------------------
# Expert knobs live in code on purpose (zero user-facing config); the
# single config override is deep_recall.max_turns (0 = disable).
# Sized for the compound case (declared compound scope): ~2 investigation
# turns per recalled topic plus synthesis. The budget guard makes the
# final turn force synthesis, so an unused surplus costs nothing.
DEFAULT_MAX_TURNS = 8
SEARCH_LIMIT = 8

# Windowed memory retrieval (search_memories with start/end): top_k
# follows GREEN's context-window tiers, with a hard ceiling regardless
# of how large the model window is (a 1M-context model still gets 20:
# long observation lists are expensive in latency and cost, and the
# digest only needs the salient facts). The result is also clamped to
# the window's density: a sparse period returns all its memories.
MEMORY_TOP_K_TIERS = ((4096, 6), (8000, 10), (32768, 15), (None, 20))
MEMORY_CLIP_UNWINDOWED = 600
MEMORY_CLIP_WINDOWED = 180

# Chronological log browsing (browse_logs): coverage instrument for
# periods memories do not cover, and verification depth for claims.
LOGS_WINDOW_LIMIT = 25
LOGS_WINDOW_MAX_LIMIT = 40
LOGS_CLIP = 180
MAX_OBS_CHARS = 6000
DIGEST_MAX_CHARS = 8000
MAX_TOPICS = 60
LOG_HIT_CLIP = 400
# Date anchoring: memories carry their last-updated dates; the
# conversations that generated them cluster around those dates. The
# suggested log window (min/max hit dates +- this many days) scopes
# search_logs calls so a precise timeframe replaces an unbounded scan.
RECALL_WINDOW_DAYS = 90

_TOOL_RE = re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.DOTALL)
_FINAL_RE = re.compile(r"<final>(.*)</final>", re.DOTALL)
# Citations in a digest: [M:<id>] / [L:<id> @ <timestamp>].
_CITATION_RE = re.compile(r"\[([ML]):([^\]\s@]+)")

_NUDGE_NOTE = (
    "[System: your last response did not follow the protocol. Respond"
    " with EITHER <tool>{\"name\": ..., \"args\": {...}}</tool> OR"
    " <final>...digest...</final> — nothing else.]"
)

_NUDGE_INVESTIGATE_NOTE = (
    "[System: a digest without investigation is not acceptable. You"
    " have gathered no evidence: call a tool first (search_memories or"
    " search_logs), read the results, and only then produce the digest"
    " — citing exclusively what the tool results returned.]"
)

_NUDGE_CITATION_NOTE = (
    "[System: the digest carries no citations, or cites ids that never"
    " appeared in any tool result. Citations must come verbatim from"
    " the evidence you gathered: investigate with the tools, then cite"
    " the ids exactly as the results showed them. If the evidence does"
    " not cover the topic, say so in the Known gaps section instead of"
    " writing an uncited digest.]"
)


class DeepRecallEngine:
    """Bounded investigation loop over GREEN memories + chat logs.

    Runs on the memory-tier LLM (configured for speed over depth —
    ideal for this job) and returns a cited digest, or None on any
    failure (fail to silence).
    """

    def __init__(self, green_memories, chat_memory):
        self.green_memories = green_memories
        self.chat_memory = chat_memory
        self.template_manager = TemplateManager()

    # -- public API ------------------------------------------------------

    def run(
        self,
        query: str,
        history_tail: Optional[List[Dict]] = None,
        timeframe: Union[str, List[str], None] = None,
    ) -> Optional[Dict[str, Any]]:
        """Investigate the corpora for `query` and return
        {"success": True, "digest": str, "turns": int} or None.

        Runs the loop against the memory-tier provider chain in
        failover order (GREEN's _run_with_memory_llm policy): a
        provider that errors or yields no digest hands the whole
        investigation to the next one; the default LLM is the final
        fallback. All exhausted -> None (fail to silence).

        `timeframe` is the user-stated period(s) extracted by the
        selection LLM (e.g. 'a few days ago', or a list like
        ['last week', 'in March'] for compound requests); each entry
        reaches the loop as a mechanical goal line and is resolved
        against the current date to scope log searches.
        """
        max_turns = self._max_turns()
        if max_turns == 0:
            return None
        timeframes: List[str] = []
        if isinstance(timeframe, str):
            timeframes = [timeframe]
        elif timeframe:
            timeframes = [
                t.strip() for t in timeframe
                if isinstance(t, str) and t.strip()
            ]
        try:
            chain = self.green_memories.get_memory_llm_chain()
        except Exception:
            logger.exception("DEEP_RECALL: could not resolve LLM chain")
            return None
        for llm, reasoning_effort in chain:
            try:
                result = self._run_loop(
                    query, history_tail, max_turns, llm, reasoning_effort,
                    timeframes,
                )
            except Exception:
                logger.exception(
                    "DEEP_RECALL: memory-tier provider failed; trying"
                    " next in chain"
                )
                continue
            if result:
                return result
            logger.warning(
                "DEEP_RECALL: memory-tier provider produced no digest;"
                " trying next in chain"
            )
        logger.warning(
            "DEEP_RECALL: all memory-tier providers exhausted"
            " without a digest."
        )
        return None

    # -- internals -------------------------------------------------------

    def _max_turns(self) -> int:
        try:
            return int(config.get("deep_recall.max_turns", DEFAULT_MAX_TURNS))
        except (TypeError, ValueError):
            return DEFAULT_MAX_TURNS

    def _run_loop(
        self,
        query: str,
        history_tail: Optional[List[Dict]],
        max_turns: int,
        llm,
        reasoning_effort: Optional[str],
        timeframes: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        system_prompt = self.template_manager.render(
            "framework.deep_recall.investigator_system",
            {"digest_max_chars": DIGEST_MAX_CHARS},
        )
        goal_parts = [
            "Investigate everything the user and you have ever said or"
            " experienced about the following topic, then produce the"
            " cited digest described in your instructions.",
            "",
            f"TOPIC: {query}",
        ]
        if history_tail:
            tail = [
                f"{m.get('role')}: {_clip(m.get('content'), 300)}"
                for m in history_tail[-6:]
                if m.get("role") in ("user", "assistant")
            ]
            if tail:
                goal_parts += ["", "RECENT CONVERSATION (for reference):"]
                goal_parts += tail
        if timeframes:
            goal_parts += [
                "",
                "TIMEFRAME(S): the events are expected around: "
                + "; ".join(timeframes) + ".",
                "Resolve these against today's date and scope search_logs"
                " with start_date/end_date accordingly.",
            ]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(goal_parts)},
        ]

        nudges = 0
        tool_calls = {"search_memories": 0, "search_logs": 0,
                      "list_topics": 0, "window_overview": 0,
                      "browse_logs": 0}
        seen_ids = set()  # evidence ids actually returned by tools
        provider_name = "?"
        provider_conf = getattr(llm, "provider", None)
        if isinstance(provider_conf, dict):
            provider_name = provider_conf.get("model", "?")
        # Context window of the investigating provider: drives adaptive
        # top_k for date-scoped memory retrieval (GREEN's tiers).
        self._context_window = 4096
        get_ctx = getattr(llm, "get_context_window", None)
        if callable(get_ctx):
            try:
                self._context_window = get_ctx() or 4096
            except Exception:
                pass
        logger.info(
            "DEEP_RECALL: investigation on %s (reasoning_effort=%s,"
            " context_window=%s)",
            provider_name, reasoning_effort, self._context_window,
        )
        for turn in range(max_turns):
            if turn == max_turns - 1 and any(tool_calls.values()):
                # Budget guard: a final turn with evidence must
                # synthesize, not keep searching (the dominant failure
                # mode observed in production logs).
                messages.append({
                    "role": "user",
                    "content": (
                        "BUDGET NOTE: this is your final turn. Do not"
                        " call more tools: emit <final> now with the"
                        " best digest the evidence you gathered"
                        " supports, listing what is still missing under"
                        " 'Known gaps:'."
                    ),
                })
            response = llm.chat(
                chat_history=messages,
                stream=False,
                reasoning_effort=reasoning_effort,
            )
            text = (response or "").strip()
            if not text:
                logger.warning("DEEP_RECALL: empty LLM response, aborting")
                return None
            logger.info(
                "DEEP_RECALL turn %d/%d response: %s",
                turn + 1, max_turns, _clip(text, 200),
            )
            messages.append({"role": "assistant", "content": text})

            final = _FINAL_RE.search(text)
            if final:
                digest = final.group(1).strip()
                # Mechanical evidence contract: the model words the
                # truth, it never writes without it.
                if not any(tool_calls.values()):
                    # Ungrounded digest: no investigation happened.
                    # Reject and demand evidence (fail over to the next
                    # chain provider if the model keeps refusing).
                    nudges += 1
                    if nudges > 2:
                        logger.warning(
                            "DEEP_RECALL: digest without investigation"
                            " rejected repeatedly; aborting this"
                            " provider."
                        )
                        return None
                    logger.warning(
                        "DEEP_RECALL: rejected ungrounded digest (no"
                        " tool calls); nudging to investigate."
                    )
                    messages.append({
                        "role": "user",
                        "content": _NUDGE_INVESTIGATE_NOTE,
                    })
                    continue
                found = _CITATION_RE.findall(digest)
                if found and any(
                    (kind, cid) not in seen_ids
                    for kind, cid in found
                ):
                    # Fabricated citation: an id the tools never
                    # returned. Same doctrine as _scrub_forged_results.
                    nudges += 1
                    if nudges > 2:
                        logger.warning(
                            "DEEP_RECALL: fabricated citations rejected"
                            " repeatedly; aborting this provider."
                        )
                        return None
                    logger.warning(
                        "DEEP_RECALL: rejected digest citing ids never"
                        " returned by tools; nudging."
                    )
                    messages.append({
                        "role": "user",
                        "content": _NUDGE_CITATION_NOTE,
                    })
                    continue
                if len(digest) > DIGEST_MAX_CHARS:
                    logger.warning(
                        "DEEP_RECALL: digest (%d chars) exceeds bound"
                        " (%d); failing closed.",
                        len(digest), DIGEST_MAX_CHARS,
                    )
                    return None
                logger.info(
                    "DEEP_RECALL: digest ready in %d turns, tool calls:"
                    " %s", turn + 1, tool_calls,
                )
                return {"success": True, "digest": digest,
                        "turns": turn + 1}

            match = None
            for match in _TOOL_RE.finditer(text):
                pass  # keep the LAST tool call if several appear
            if match is None:
                nudges += 1
                if nudges > 2:
                    logger.warning(
                        "DEEP_RECALL: protocol not followed after"
                        " nudges; aborting."
                    )
                    return None
                messages.append({"role": "user", "content": _NUDGE_NOTE})
                continue

            try:
                call = json.loads(match.group(1))
                name = call.get("name")
                args = call.get("args") or {}
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                name, args = None, {}
            observation = self._execute_tool(name, args, tool_calls)
            seen_ids.update(_CITATION_RE.findall(observation))
            messages.append({
                "role": "user",
                "content": "TOOL RESULT:\n" + _clip(observation,
                                                    MAX_OBS_CHARS),
            })

        logger.warning(
            "DEEP_RECALL: turn budget (%d) exhausted without a digest.",
            max_turns,
        )
        return None

    # -- tools -----------------------------------------------------------

    def _execute_tool(
        self,
        name: Optional[str],
        args: Dict[str, Any],
        tool_calls: Dict[str, int],
    ) -> str:
        """Dispatch an internal retrieval tool; returns the observation
        text (never raises)."""
        try:
            if name == "list_topics":
                tool_calls[name] += 1
                return self._tool_list_topics(args)
            if name == "search_memories":
                tool_calls[name] += 1
                return self._tool_search_memories(args)
            if name == "search_logs":
                tool_calls[name] += 1
                return self._tool_search_logs(args)
            if name == "window_overview":
                tool_calls[name] += 1
                return self._tool_window_overview(args)
            if name == "browse_logs":
                tool_calls[name] += 1
                return self._tool_browse_logs(args)
            return (
                f"ERROR: unknown tool {name!r}. Available tools:"
                " list_topics, search_memories, search_logs,"
                " window_overview, browse_logs."
            )
        except Exception as exc:
            logger.exception("DEEP_RECALL: tool %r failed", name)
            return f"ERROR: tool {name!r} failed: {exc}"

    def _tool_list_topics(self, args: Dict[str, Any]) -> str:
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        for bound in (start_date, end_date):
            if bound is not None and resolve_date_bound(bound) is None:
                return (
                    f"ERROR: list_topics received an unparseable date"
                    f" bound: {bound!r}. Use YYYY-MM-DD."
                )
        topics = self.green_memories.get_all_topics(
            start_date=start_date, end_date=end_date
        )
        if not topics:
            scope = (
                " in that period"
                if start_date or end_date
                else " yet (the memory store is empty)"
            )
            return f"No memory topics exist{scope}."
        clipped = topics[:MAX_TOPICS]
        suffix = (
            f" (…and {len(topics) - MAX_TOPICS} more)"
            if len(topics) > MAX_TOPICS else ""
        )
        return "Memory topics:\n" + "\n".join(f"- {t}" for t in clipped) \
            + suffix

    def _tool_search_memories(self, args: Dict[str, Any]) -> str:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return (
                "ERROR: search_memories requires a non-empty \"query\""
                " string arg."
            )
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        for bound in (start_date, end_date):
            if bound is not None and resolve_date_bound(bound) is None:
                return (
                    f"ERROR: search_memories received an unparseable"
                    f" date bound: {bound!r}. Use YYYY-MM-DD."
                )
        windowed = start_date is not None or end_date is not None
        if windowed:
            candidates = self.green_memories.count_memories_in_window(
                start_date=start_date, end_date=end_date
            )
            top_k = _memory_top_k(self._context_window, candidates)
        else:
            candidates = None
            top_k = SEARCH_LIMIT
        hits = self.green_memories.get_relevant_memories(
            query.strip(),
            top_k=top_k,
            start_date=start_date,
            end_date=end_date,
        )
        lines = []
        if windowed:
            lines.append(
                f"Window {start_date or 'beginning'}..{end_date or 'today'}:"
                f" {candidates} memories exist; showing top"
                f" {len(hits)} by relevance."
            )
        if not hits:
            if windowed:
                lines.append(
                    "No memories matched inside the period. Memories may"
                    " not cover it at all (see window_overview); if raw"
                    " history is needed, use browse_logs."
                )
            else:
                lines.append(
                    "No memories matched. Try different phrasing, related"
                    " topics, or search_logs."
                )
            return "\n".join(lines)
        clip = MEMORY_CLIP_WINDOWED if windowed else MEMORY_CLIP_UNWINDOWED
        for m in hits:
            lines.append(
                f"[M:{m.get('id')}] (topic={m.get('topic')},"
                f" relevance={m.get('relevance')},"
                f" status={m.get('status')},"
                f" created={m.get('created_at')},"
                f" updated={m.get('last_updated')})"
                f" {_clip(m.get('memory'), clip)}"
            )
        if not windowed:
            window = _suggested_log_window(hits)
            if window:
                lines.append(window)
        return "Memory hits:\n" + "\n".join(lines)

    def _tool_window_overview(self, args: Dict[str, Any]) -> str:
        """Mechanical, model-computed facts about a period: message
        density, memory coverage, weekly distribution. Lets the agent
        plan a period investigation before spending searches on it —
        the numbers are framework-computed data, never model guesses."""
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        if not start_date or not end_date:
            return (
                "ERROR: window_overview requires start_date and"
                " end_date (YYYY-MM-DD)."
            )
        for bound in (start_date, end_date):
            if resolve_date_bound(bound) is None:
                return (
                    f"ERROR: window_overview received an unparseable"
                    f" date bound: {bound!r}. Use YYYY-MM-DD."
                )
        overview = self.chat_memory.window_overview(
            start_date, end_date, all_contexts=True
        )
        memories = self.green_memories.count_memories_in_window(
            start_date=start_date, end_date=end_date
        )
        lines = [
            f"Period {start_date}..{end_date}:",
            f"- conversation messages: {overview.get('count', 0)}"
            f" (from {overview.get('first') or '—'} to"
            f" {overview.get('last') or '—'})",
            f"- memories created in the period: {memories}",
        ]
        if memories == 0:
            lines.append(
                "- memories do NOT cover this period at all: raw"
                " conversation logs are the only source (browse_logs)."
            )
        weekly = overview.get("weekly") or []
        if weekly:
            bars = ", ".join(f"{label}: {n}" for label, n in weekly)
            lines.append(f"- messages per week: {bars}")
        return "Window overview (mechanical facts):\n" + "\n".join(lines)

    def _tool_browse_logs(self, args: Dict[str, Any]) -> str:
        """Chronological, paged traversal of a period's raw log. The
        coverage instrument when memories are thin or absent, and for
        verifying the day-by-day shape of a period."""
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        if not start_date or not end_date:
            return (
                "ERROR: browse_logs requires start_date and end_date"
                " (YYYY-MM-DD)."
            )
        for bound in (start_date, end_date):
            if resolve_date_bound(bound) is None:
                return (
                    f"ERROR: browse_logs received an unparseable date"
                    f" bound: {bound!r}. Use YYYY-MM-DD."
                )
        try:
            offset = max(0, int(args.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(args.get("limit") or LOGS_WINDOW_LIMIT)
        except (TypeError, ValueError):
            limit = LOGS_WINDOW_LIMIT
        limit = max(1, min(limit, LOGS_WINDOW_MAX_LIMIT))

        overview = self.chat_memory.window_overview(
            start_date, end_date, all_contexts=True
        )
        total = overview.get("count", 0)
        if total == 0:
            return (
                f"Period {start_date}..{end_date}: no conversation"
                " messages recorded at all."
            )
        messages = self.chat_memory.browse_window(
            start_date, end_date, offset=offset, limit=limit,
            all_contexts=True,
        )
        lines = [
            f"Period {start_date}..{end_date}: {total} messages total;"
            f" showing {offset}-{offset + len(messages)} in"
            " chronological order.",
        ]
        if offset + len(messages) < total:
            lines.append(
                f"More remain: page with offset={offset + len(messages)}."
            )
        for e in messages:
            lines.append(
                f"[L:{e.get('id')} @ {e.get('timestamp')}]"
                f" ({e.get('role')}) {_clip(e.get('content'), LOGS_CLIP)}"
            )
        return "Conversation log (chronological):\n" + "\n".join(lines)

    def _tool_search_logs(self, args: Dict[str, Any]) -> str:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return (
                "ERROR: search_logs requires a non-empty \"query\""
                " string arg."
            )
        query = query.strip()
        # Semantic (Chroma embeddings) is the default: it finds related
        # content regardless of exact wording. Exact/FTS mode is opt-in
        # for rare literal terms — and its terms are AND-joined, so it
        # only works with short queries (the prompt teaches this).
        exact = bool(args.get("exact"))
        search_query = query if exact else ("~" + query)
        entries = self.chat_memory.search_entries(
            search_query,
            limit=SEARCH_LIMIT,
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            all_contexts=True,
        )
        if not entries:
            return (
                "No conversation log entries matched. Try exact"
                " keywords, semantic=true, or a wider date range."
            )
        lines = []
        for e in entries:
            context = e.get("context_id")
            if context is None:
                context = (e.get("metadata") or {}).get("context_id")
            lines.append(
                f"[L:{e.get('id')} @ {e.get('timestamp')}]"
                f" (context={context}, role={e.get('role')})"
                f" {_clip(e.get('content'), LOG_HIT_CLIP)}"
            )
        return "Conversation log hits:\n" + "\n".join(lines)


def _clip(text: Any, limit: int) -> str:
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " […truncated]"


def _memory_top_k(context_window: int, candidates: int) -> int:
    """top_k for date-scoped memory retrieval: GREEN's context-window
    tiers with a hard ceiling, clamped to the window's density. The
    density count is a mechanical fact; the model never enlarges the
    list by itself beyond the ceiling."""
    for threshold, tier in MEMORY_TOP_K_TIERS:
        if threshold is None or context_window <= threshold:
            break
    return min(tier, candidates)


def _suggested_log_window(hits: List[Dict]) -> Optional[str]:
    """Mechanical date anchoring for the loop: memories carry their
    last-updated dates, and the conversations that generated them
    cluster around those dates. Returns the suggested search_logs
    date window (min/max hit dates +- RECALL_WINDOW_DAYS) as an
    observation line, or None when no hit carries a usable date."""
    dates = []
    for m in hits:
        raw = m.get("last_updated")
        try:
            dates.append(
                datetime.fromisoformat(
                    str(raw).replace("Z", "+00:00")
                ).date()
            )
        except (ValueError, TypeError):
            continue
    if not dates:
        return None
    lo = min(dates) - timedelta(days=RECALL_WINDOW_DAYS)
    hi = max(dates) + timedelta(days=RECALL_WINDOW_DAYS)
    return (
        f"Suggested log window (scope search_logs with start_date/"
        f"end_date around it): {lo.isoformat()} .. {hi.isoformat()}"
    )
