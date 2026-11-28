"""Capability digest: the ID-free ability menu the main conversation model sees.

The main chat model never needs capability IDs. It only states intents in
natural language inside ``<orakle>...</orakle>`` tags; the transformer
matcher and the selection LLM (which are ID-native) do the routing and
parameter filling. Handing the main model a list of internal identifiers is
inert inventory at best — and contradicts the ORAKLE POLICY stealth rule
("do not use terms like tools, APIs, or skills") plus the framework doctrine
that the model thinks about WHAT can be done, never HOW.

This module compiles the capability payload into a compact ability menu:

- **Generated once per capability set.** The payload is hashed; on hash
  match the cached digest is reused, so the LLM compilation pass only runs
  when skills are installed, removed or updated.
- **LLM-compiled, mechanically validated.** The compiler sees lean
  capability cards and must return JSON entries, each covering explicit
  capability IDs. Validation enforces full coverage, no ID leakage into the
  rendered text, and the fixed-list rule below.
- **Fixed option sets are shown complete and closed.** Where a parameter
  declares a fixed enumeration (``Literal`` in ``run()`` annotations), the
  digest lists EVERY value with ``|`` separators and never uses "…",
  "..." or "etc." — an open-ended rendering would invite the model to
  invent options. Open-ended parameters are described with at most two
  examples phrased as "such as".
- **Mechanical fallback.** Without the LLM (or on validation failure) a
  deterministic projection is built from first docstring sentences plus the
  fixed enumerations. Degraded, never broken.

Cache location: ``<data dir>/capability_digest.json``. Bureau agents are
deliberately untouched: their system prompts keep the lean, ID-native
capability menu (``format_capabilities_menu``), which is the documented
agent contract (see docs/architecture/orakle-routing.md).
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from ainara.framework.config import get_data_dir

logger = logging.getLogger(__name__)

CACHE_FILENAME = "capability_digest.json"
CACHE_VERSION = 1

# Fixed option lists must be closed: any ellipsis or "etc." in a rendered
# entry implies unlisted options and fails validation.
_ELLIPSIS_RE = re.compile(r"\.\.\.|…")
_MECHANISM_TALK_RE = re.compile(r"\b(skills?|tools?|APIs?|endpoints?)\b",
                                re.IGNORECASE)
# A rendered entry must not contain any capability id (e.g.
# "memory_deep_recall"): ids are selection-layer vocabulary.
_ENUM_VALUES_RE = re.compile(r"one of:\s*(.+)", re.IGNORECASE)
_QUOTED_VALUE_RE = re.compile(r"'([^']+)'")

MAX_ENTRY_CHARS = 340


def payload_hash(capabilities: List[dict]) -> str:
    """Stable hash of everything that can change the digest's wording."""
    canonical = []
    for skill in sorted(capabilities, key=lambda s: s.get("name", "")):
        canonical.append(
            {
                "name": skill.get("name"),
                "description": skill.get("description"),
                "parameters": [
                    {
                        "name": p.get("name"),
                        "type": p.get("type"),
                        "description": p.get("description"),
                    }
                    for p in skill.get("parameters", [])
                ],
            }
        )
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fixed_options(param: dict) -> Optional[str]:
    """Render a fixed enumeration COMPLETELY, or None for open parameters.

    Only ``one of: ...`` type declarations qualify — they are the closed
    sets declared via ``Literal`` in ``run()``. Everything else (free
    strings, lists, formats like recency) is open-ended and is left to the
    compiler's "such as" phrasing instead of a closed list.
    """
    match = _ENUM_VALUES_RE.search(str(param.get("type", "")))
    if not match:
        return None
    values = _QUOTED_VALUE_RE.findall(match.group(1))
    if not values:
        return None
    return f"{param.get('name')}: {'|'.join(values)}"


def _capability_card(skill: dict) -> str:
    """Lean card for the compiler: id, semantic description, fixed options."""
    lines = [f"id: {skill.get('name')}"]
    description = " ".join((skill.get("description") or "").split())
    lines.append(f"what: {description}")
    fixed = [
        opt
        for opt in (
            _fixed_options(p) for p in skill.get("parameters", [])
        )
        if opt
    ]
    if fixed:
        lines.append("fixed options (list them COMPLETELY, closed):")
        lines.extend(f"  - {opt}" for opt in fixed)
    return "\n".join(lines)


_GENERATION_SYSTEM_PROMPT = (
    "You compile a compact menu of ABILITIES for an AI assistant's system"
    " prompt, from backend capability cards. The assistant states intents in"
    " natural language; a separate routing layer maps them to backends. The"
    " assistant never sees capability ids and never mentions mechanisms:"
    " the words 'skill', 'tool', 'API' must not appear.\n"
    "\n"
    "Rules:\n"
    "- Group several capabilities into ONE entry only when they clearly"
    " share a domain and fit ~25 words; otherwise one entry per capability.\n"
    "- Phrase entries as what the assistant CAN DO (verb-first, natural).\n"
    "- Where a card lists FIXED options, copy the list COMPLETELY and CLOSED"
    " with | separators (e.g. search_type comprehensive|academic|recent|"
    "exploratory|news|crypto|jobs). NEVER use '...', '…' or 'etc.': the"
    " reader must understand the list is exhaustive.\n"
    "- For open-ended parameters (free text, formats) give at most two"
    " examples phrased as 'such as'.\n"
    "- Each entry: max 25 words plus any fixed option lists.\n"
    "\n"
    "Respond with ONLY a JSON array:"
    ' [{"text": "ability entry", "covers": ["capability_id", ...]}].'
    " Every capability id must appear in exactly one entry's covers."
)


def _parse_entries(raw: str) -> Optional[List[dict]]:
    """Extract the JSON array from the compiler's response."""
    if not raw:
        return None
    text = raw.strip()
    # Tolerate a fenced block around the JSON.
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        entries = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(entries, list) or not entries:
        return None
    return entries


def _validate_entries(
    entries: List[dict], capabilities: List[dict]
) -> Optional[List[str]]:
    """Mechanical validation gate. Returns rendered lines or None."""
    ids = [s.get("name") for s in capabilities]
    id_set = set(ids)
    # Longest-first alternation so overlapping ids can't shadow each other.
    id_token_re = (
        re.compile(
            "|".join(map(re.escape, sorted(id_set, key=len, reverse=True)))
        )
        if id_set
        else None
    )

    covered: set = set()
    lines: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        text = str(entry.get("text", "")).strip()
        covers = entry.get("covers", [])
        if not text or not isinstance(covers, list) or not covers:
            return None
        if len(text) > MAX_ENTRY_CHARS:
            return None
        if _ELLIPSIS_RE.search(text):
            return None
        if re.search(r"\betc\.?\b", text, re.IGNORECASE):
            return None
        if _MECHANISM_TALK_RE.search(text):
            return None
        if id_token_re and id_token_re.search(text):
            return None
        entry_ids = [c for c in covers if c in id_set]
        if not entry_ids:
            return None
        if covered.intersection(entry_ids):
            return None  # an id covered twice
        covered.update(entry_ids)
        lines.append(f"- {text}")
    if covered != id_set:
        return None  # incomplete coverage
    return lines


def _mechanical_menu(capabilities: List[dict]) -> List[str]:
    """Deterministic fallback: first sentence + complete fixed options."""
    lines = []
    for skill in sorted(capabilities, key=lambda s: s.get("name", "")):
        description = " ".join((skill.get("description") or "").split())
        match = re.match(r"(.+?[.!?])(\s|$)", description)
        gloss = match.group(1) if match else description
        if len(gloss) > 110:
            # Prefer the last inner sentence or clause boundary over a
            # raw word cut, so the fallback never dangles mid-clause.
            for sep in (". ", "; ", ", "):
                cut = gloss.rfind(sep, 0, 110)
                if cut > 40:
                    gloss = gloss[:cut]
                    break
            else:
                gloss = gloss[:110].rsplit(" ", 1)[0]
            gloss = re.sub(
                r"\s+(and|or|the|a|an|to|for|with|of|that|which|from|into)$", "",
                gloss,
            )
        gloss = gloss.rstrip(".")
        fixed = [
            opt
            for opt in (
                _fixed_options(p) for p in skill.get("parameters", [])
            )
            if opt
        ]
        suffix = f" ({'; '.join(fixed)})" if fixed else ""
        lines.append(f"- {gloss}{suffix}")
    return lines


_HEADER = (
    "Through ORAKLE, simply by stating your intent in natural language, you"
    " can do all of the following:"
)


def _read_cache(cache_path: Path) -> Optional[dict]:
    try:
        with open(cache_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("version") == CACHE_VERSION and data.get("digest"):
            return data
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return None


def _write_cache(cache_path: Path, digest_hash: str, digest: str) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "version": CACHE_VERSION,
                    "hash": digest_hash,
                    "digest": digest,
                },
                fh,
                ensure_ascii=False,
            )
        tmp.replace(cache_path)
    except OSError as exc:
        logger.warning("Could not persist capability digest cache: %s", exc)


def build_capability_digest(
    capabilities: List[dict],
    llm,
    cache_path: Optional[Path] = None,
) -> str:
    """Compile the ID-free ability menu for the main conversation model.

    Hash-gated: the LLM compilation pass runs only when the capability
    payload changes; otherwise the cached digest is reused. Falls back to
    the deterministic mechanical menu when the LLM is unavailable or its
    output fails validation. Never raises.
    """
    if not capabilities:
        return ""
    digest_hash = payload_hash(capabilities)
    if cache_path is None:
        cache_path = Path(get_data_dir()) / CACHE_FILENAME
    cache_path = Path(cache_path)

    cached = _read_cache(cache_path)
    if cached and cached.get("hash") == digest_hash:
        return cached["digest"]

    lines: Optional[List[str]] = None
    if llm is not None:
        cards = "\n\n".join(_capability_card(s) for s in capabilities)
        user_prompt = (
            "CAPABILITY CARDS:\n\n"
            f"{cards}\n\n"
            "Compile the ability menu now. Respond with ONLY the JSON array."
        )
        for attempt in (1, 2):
            try:
                raw = llm.chat(
                    chat_history=[
                        {"role": "system", "content": _GENERATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    stream=False,
                )
            except Exception as exc:
                logger.warning(
                    "Capability digest generation failed (attempt %d): %s",
                    attempt,
                    exc,
                )
                break
            entries = _parse_entries(raw)
            if entries:
                lines = _validate_entries(entries, capabilities)
                if lines:
                    logger.info(
                        "Capability digest compiled (%d entries, hash %s).",
                        len(lines),
                        digest_hash[:12],
                    )
                    break
                logger.warning(
                    "Capability digest validation failed (attempt %d,"
                    " coverage/ellipsis/id/mechanism rule breach).",
                    attempt,
                )
            else:
                logger.warning(
                    "Capability digest: unparseable compiler response"
                    " (attempt %d).",
                    attempt,
                )

    if lines is None:
        lines = _mechanical_menu(capabilities)
        logger.info("Capability digest fell back to mechanical projection.")

    digest = _HEADER + "\n" + "\n".join(lines)
    _write_cache(cache_path, digest_hash, digest)
    return digest
