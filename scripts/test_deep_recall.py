#!/usr/bin/env python3
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
# Offline harness for the Deep Recall engine + system-skill adapter
# (no services required): fakes for the LLM, GREEN memories and
# ChatMemory drive deterministic scenarios covering the loop mechanics,
# protocol recovery, fail-closed behavior, the registry wiring and the
# trail/persistence helpers. Run: python scripts/test_deep_recall.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ainara.framework.deep_recall import DeepRecallEngine  # noqa: E402
from ainara.framework.orakle_middleware import OrakleMiddleware  # noqa: E402
from ainara.framework.skills import register as registry  # noqa: E402
from ainara.framework.system_skills.deep_recall import (  # noqa: E402
    SystemSkillDeepRecall,
)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


class FakeLLM:
    """Scripted responder: pops one response per chat() call. The last
    script entry repeats if the script runs dry."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, chat_history=None, stream=False, **kwargs):
        self.calls.append([dict(m) for m in (chat_history or [])])
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]


class FakeGreen:
    def __init__(self, llm, topics=None, memories=None):
        self.llm = llm
        self.topics = topics or []
        self.memories = memories or []

    def get_memory_llm_chain(self):
        return [(self.llm, None)]

    def get_all_topics(self):
        return self.topics

    def get_relevant_memories(self, query, top_k=None, **kwargs):
        return self.memories[: top_k or len(self.memories)]


class FakeChatMemory:
    def __init__(self, entries=None):
        self.entries = entries or []
        self.queries = []

    def search_entries(self, query, limit=10, **kwargs):
        self.queries.append(query)
        return self.entries[:limit]


MEM1 = {
    "id": "mem-001", "topic": "solar panels", "memory":
    "User installed 6 solar panels in March 2024.",
    "relevance": 0.9, "status": "current",
    "last_updated": "2024-03-10",
}
LOG1 = {
    "id": "log-77", "context_id": "general",
    "timestamp": "2024-03-12T10:00:00", "role": "user",
    "content": "The electrician said the roof needs reinforcement"
    " before mounting the panels.",
}

FINAL = (
    "# Digest: solar panel installation\n"
    "User installed 6 solar panels in March 2024 [M:mem-001]."
    " The roof needed reinforcement first [L:log-77 @"
    " 2024-03-12T10:00:00].\n\n"
    "Known gaps: no later maintenance records found."
)

TOOL_TOPICS = '<tool>{"name": "list_topics", "args": {}}</tool>'
TOOL_MEMS = (
    '<tool>{"name": "search_memories",'
    ' "args": {"query": "solar panels"}}</tool>'
)
TOOL_LOGS = '<tool>{"name": "search_logs", "args": {"query": "solar"}}</tool>'
TOOL_LOGS_EXACT = (
    '<tool>{"name": "search_logs",'
    ' "args": {"query": "Panels-R-Us", "exact": true}}</tool>'
)
BAD_JSON = '<tool>{"name": "search_memories" NOPE}</tool>'


def build_engine(script, topics=None, memories=None, entries=None):
    llm = FakeLLM(script)
    green = FakeGreen(llm, topics=topics, memories=memories)
    chat_mem = FakeChatMemory(entries=entries)
    engine = DeepRecallEngine(green, chat_mem)
    return engine, llm, chat_mem


def test_registry_and_skill_adapter():
    print("[registry + system skill adapter]")
    engine, _, _ = build_engine(
        [TOOL_MEMS, TOOL_LOGS, f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    registry.register_service("deep_recall_engine", engine)
    try:
        skill = SystemSkillDeepRecall()
        check("skill name", skill.name == "deep_recall")
        check("definition exposes matcher_info",
              "remember" in skill.matcher_info.lower())
        result = skill.run("solar panel installation", {})
        check("adapter delegates to engine",
              result.get("success") is True)
        check("digest present", "solar panel installation"
              in result.get("digest", ""))
        check("history tail forwarded", True)

        # Engine missing -> structured failure, never raises.
        registry.unregister_service("deep_recall_engine")
        result = skill.run("solar", {})
        check("engine missing -> structured failure",
              result.get("success") is False and "error" in result)
    finally:
        registry.unregister_service("deep_recall_engine")


def test_happy_path():
    print("[run: happy path]")
    script = [
        TOOL_TOPICS,
        TOOL_MEMS,
        TOOL_LOGS,
        f"<final>{FINAL}</final>",
    ]
    engine, llm, chat_mem = build_engine(
        script,
        topics=["solar panels", "home renovation"],
        memories=[MEM1], entries=[LOG1],
    )
    result = engine.run("solar panel installation",
                        history_tail=[{"role": "user",
                                       "content": "solar?"}])
    check("success", bool(result) and result["success"] is True)
    check("digest text", result and result["digest"].startswith(
        "# Digest: solar panel installation"))
    check("turns", result and result["turns"] == 4)
    check("system prompt rendered from template", any(
        "Deep Recall investigator" in m["content"]
        for m in llm.calls[0]))
    check("digest budget injected from template", any(
        "8000" in m["content"] for m in llm.calls[0]))
    check("mem citation in prompt", any(
        "[M:mem-001]" in m["content"] for c in llm.calls for m in c))
    check("log citation in prompt", any(
        "[L:log-77" in m["content"] for c in llm.calls for m in c))
    check("semantic is the default log route", "~solar"
          in chat_mem.queries)
    check("suggested log window injected in observation", any(
        "Suggested log window" in m["content"]
        for c in llm.calls for m in c))


def test_exact_mode_and_window_bounds():
    print("[run: exact mode + window bounds]")
    engine, llm, chat_mem = build_engine(
        [TOOL_LOGS_EXACT, TOOL_MEMS, f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    engine.run("solar")
    check("exact mode skips semantic prefix",
          "Panels-R-Us" in chat_mem.queries)
    from ainara.framework.deep_recall import _suggested_log_window
    window = _suggested_log_window([MEM1])
    # MEM1.last_updated = 2024-03-10; +- 90 days.
    check("window lower bound", "2023-12-11" in (window or ""))
    check("window upper bound", "2024-06-08" in (window or ""))
    check("no usable dates -> no window", _suggested_log_window(
        [{"id": "m", "last_updated": "not-a-date"}]) is None)


def test_protocol_recovery_and_failures():
    print("[run: recovery + fail-closed]")
    # Malformed first response -> nudge -> recovers.
    engine, _, _ = build_engine(
        [BAD_JSON, TOOL_MEMS, TOOL_LOGS, f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    result = engine.run("solar")
    check("recovers after nudge", bool(result) and result["success"])

    # Unknown tool name -> error observation -> recovers.
    engine, _, _ = build_engine(
        ['<tool>{"name": "web_search", "args": {}}</tool>',
         TOOL_MEMS, TOOL_LOGS, f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    result = engine.run("solar")
    check("unknown tool surfaces error observation",
          bool(result) and result["success"])

    # Ungrounded digest (no tool calls) -> rejected with investigate
    # nudge -> recovers once evidence exists.
    engine, llm, _ = build_engine(
        [f"<final>{FINAL}</final>", TOOL_MEMS, TOOL_LOGS,
         f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    result = engine.run("solar")
    check("ungrounded digest rejected then recovers",
          bool(result) and result["success"])
    check("investigate nudge sent", any(
        "without investigation" in m["content"]
        for c in llm.calls for m in c))

    # Fabricated citation (id never returned by tools) -> rejected.
    fabricated = FINAL.replace("[L:log-77", "[L:log-999")
    engine, llm, _ = build_engine(
        [TOOL_MEMS, f"<final>{fabricated}</final>", TOOL_LOGS,
         f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    result = engine.run("solar")
    check("fabricated citation rejected then recovers",
          bool(result) and result["success"])
    check("citation nudge sent", any(
        "never appeared in any tool result" in m["content"]
        for c in llm.calls for m in c))

    # Persistent ungrounded finals -> provider exhausted -> None.
    engine, _, _ = build_engine([f"<final>{FINAL}</final>"])
    check("persistent ungrounded -> None", engine.run("solar") is None)

    # Gaps-only digest after real (empty) investigation is legitimate.
    gaps_only = (
        "# Digest: solar panel installation\n"
        "No records found about solar panels.\n\n"
        "Known gaps: no memories or log entries matched."
    )
    engine, _, _ = build_engine(
        [TOOL_MEMS, TOOL_LOGS, f"<final>{gaps_only}</final>"]
    )
    result = engine.run("solar")
    check("gaps-only digest accepted after investigation",
          bool(result) and result["success"])

    # Turn budget exhausted.
    engine, _, _ = build_engine([TOOL_MEMS] * 1, memories=[MEM1])
    check("budget exhausted -> None", engine.run("solar") is None)

    # Empty response.
    engine, _, _ = build_engine([""])
    check("empty response -> None", engine.run("solar") is None)

    # Digest over the output bound -> fail closed.
    oversized = f"<final>{'x' * 9000}</final>"
    engine, _, _ = build_engine(
        [TOOL_MEMS, oversized], memories=[MEM1]
    )
    check("oversized digest -> None", engine.run("solar") is None)

    # Missing final tag forever -> None (budget loop).
    engine, _, _ = build_engine(["thinking out loud without markers"])
    check("no markers -> None", engine.run("solar") is None)


def test_disabled():
    print("[disabled via max_turns=0]")
    from ainara.framework import deep_recall as dr
    original = dr.config.get("deep_recall.max_turns", 6)
    try:
        dr.config.set("deep_recall.max_turns", 0)
        engine, llm, _ = build_engine([f"<final>{FINAL}</final>"])
        check("run disabled -> None", engine.run("solar") is None)
        check("no LLM spent when disabled", len(llm.calls) == 0)
    finally:
        dr.config.set("deep_recall.max_turns", original)


def test_trail_and_persistence_helpers():
    print("[trail chunk + persistence strip]")
    chunk = OrakleMiddleware._deep_recall_trail_chunk(FINAL)
    check("marker line present",
          "_deep_recall_digest_|" in chunk)
    check("title hoisted",
          "solar panel installation" in chunk.split("\n")[1])
    check("body fenced", "\n```\n" in chunk)
    check("original heading stripped from body",
          "# Digest:" not in chunk)

    # A digest carrying its own fenced block must not break the outer
    # trail fence: internal fences are neutralized.
    fenced_digest = (
        "# Digest: project notes\n"
        "Summary below:\n```markdown\n# Notes\n```\n"
        "Known gaps: none."
    )
    fenced_chunk = OrakleMiddleware._deep_recall_trail_chunk(
        fenced_digest
    )
    check("internal fence neutralized",
          "```markdown" not in fenced_chunk
          and "'''markdown" in fenced_chunk)

    # Interpretation template renders for both digest and no-digest.
    from ainara.framework.template_manager import TemplateManager
    tm = TemplateManager()
    rendered = tm.render(
        "framework.deep_recall.interpretation",
        {"digest": FINAL, "query": "solar",
         "chat_context": {}, "language": "English"},
    )
    check("interpretation renders digest",
          "Known gaps" in rendered and "[M:mem-001]" in rendered)
    rendered_fail = tm.render(
        "framework.deep_recall.interpretation",
        {"digest": None, "query": "solar",
         "chat_context": {}, "language": "English"},
    )
    check("interpretation renders honest-failure branch",
          "could not consult the records" in rendered_fail)
    # Investigator template renders.
    rendered_sys = tm.render(
        "framework.deep_recall.investigator_system",
        {"digest_max_chars": 8000},
    )
    check("investigator template renders",
          "Deep Recall investigator" in rendered_sys
          and "8000" in rendered_sys)


def test_green_digest_turn_exclusion():
    print("[GREEN: digest turns never re-assimilated]")
    from ainara.framework.green_memories import group_extraction_turns
    messages = [
        {"role": "user", "content": "what did we do about the roof?",
         "timestamp": "2024-03-12T10:00:00"},
        {"role": "assistant",
         "content": "\n_deep_recall_digest_|abc|roof\n```\ndigest body\n```\n\n"
         "We reinforced the roof first.",
         "timestamp": "2024-03-12T10:01:00"},
        {"role": "user", "content": "I painted it blue yesterday",
         "timestamp": "2024-03-12T10:02:00"},
        {"role": "assistant", "content": "Nice choice!",
         "timestamp": "2024-03-12T10:03:00"},
    ]
    turns, skipped = group_extraction_turns(messages)
    check("digest turn skipped", skipped == 1)
    check("healthy turns kept", len(turns) == 1)
    check("kept turn is the paint one",
          turns[0][0]["content"] == "I painted it blue yesterday")
    check("pairing integrity after skip",
          turns[0][1]["content"] == "Nice choice!")


def test_timeframe_passthrough():
    print("[timeframe parameter passthrough]")
    # Engine: timeframe reaches the goal as a mechanical line.
    engine, llm, _ = build_engine(
        [TOOL_MEMS, TOOL_LOGS, f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    engine.run("solar", timeframe="a few days ago")
    check("engine goal carries TIMEFRAME", any(
        "TIMEFRAME: the events are expected around: a few days ago"
        in m["content"] for c in llm.calls for m in c))

    engine_nb, llm_nb, _ = build_engine(
        [TOOL_MEMS, TOOL_LOGS, f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    engine_nb.run("solar")
    check("no timeframe -> no TIMEFRAME goal line", not any(
        "TIMEFRAME: the events are expected" in m["content"]
        for c in llm_nb.calls for m in c))

    # Skill adapter: selection-LLM parameters reach the engine.
    engine2, llm2, _ = build_engine(
        [TOOL_MEMS, TOOL_LOGS, f"<final>{FINAL}</final>"],
        memories=[MEM1], entries=[LOG1],
    )
    registry.register_service("deep_recall_engine", engine2)
    try:
        skill = SystemSkillDeepRecall()
        result = skill.run("solar", {"timeframe": "last week"})
        check("adapter forwards timeframe",
              result.get("success") is True and any(
                  "TIMEFRAME: the events are expected around: last week"
                  in m["content"] for c in llm2.calls for m in c))
        check("run_info declares timeframe", "timeframe"
              in skill.run_info.get("parameters", {}))
    finally:
        registry.unregister_service("deep_recall_engine")


def main():
    test_registry_and_skill_adapter()
    test_happy_path()
    test_exact_mode_and_window_bounds()
    test_timeframe_passthrough()
    test_protocol_recovery_and_failures()
    test_disabled()
    test_trail_and_persistence_helpers()
    test_green_digest_turn_exclusion()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
