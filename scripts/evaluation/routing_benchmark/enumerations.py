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

"""Enumeration renderers: the "cognitive offloading" axis.

Four levels of capability enumeration presented to the assistant model:

  ids      - comma-joined capability ids (current Ainara behavior).
             The model knows the inventory by name only.
  domains  - framework-written domain/verb-phrase menu. The refusal
             reflex seems keyed to ACTION TYPES, not specific skills,
             so a domain-level declaration may restore trigger behavior
             at O(#domains) tokens.
  warmed   - model self-summary (warming stage): the model reads the
             LEAN payload offline and writes its own domain menu, which
             is then mechanically verified and cached. Self-authored
             framing should improve intent-query phrasing (vocabulary
             match) and perceived permission.
  none     - category policy text only. Pure intent delegation: no
             inventory knowledge at all in context.

The rendered text is a PERMISSION/FRAMING surface only. It must never
become a selection surface: selection stays with Orakle (or with the
flat arm's own mechanism), and the policy text must keep that contract
explicit so the model emits intent queries instead of "calling" skills
it read about in its own summary.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .payload import Capability, fingerprint

logger = logging.getLogger(__name__)

# Levels, ordered by information density (highest first).
LEVELS = ["ids", "domains", "warmed", "none"]


@dataclass
class EnumBlock:
    """A rendered enumeration block for the assistant's system prompt."""

    level: str
    text: str
    approx_tokens: int
    metadata: Dict[str, Any] = field(default_factory=dict)


def approx_tokens(text: str) -> int:
    """Cheap token estimate (chars/4). TODO: real tokenizer accounting."""
    return max(1, len(text) // 4)


# Verb phrases per domain. These carry the permission signal: the
# hypothesis is that the sufficient unit is "verb phrase per domain",
# not "domain noun". Extend as new domains appear in the registry.
DOMAIN_PHRASES = {
    "system": (
        "system control: read and write the system clipboard, perform "
        "file operations, search files, launch applications and open URLs"
    ),
    "search": "search the internet for information, news, products",
    "finance": "look up current stock market quotes and company data",
    "crypto": (
        "cryptocurrency technical analysis, screening, security checks "
        "and trading operations (account state, orders, logs, watchlists)"
    ),
    "shopping": "search supermarket products and build shopping carts",
    "html": "download and read the content of web pages",
    "time": "current weather conditions and forecasts",
    "tools": "evaluate mathematical expressions",
}


def domain_of(cap_id: str) -> str:
    """Derive the domain key from a capability id.

    Convention: ids look like ``<domain>_<name>`` for core skills and
    ``user_<category>_<name>`` / ``<vendor>_<app>_<domain>_<name>``
    for user and Nexus skills.
    """
    parts = cap_id.split("_")
    if parts[0] in ("user", "khromalabs"):
        # user_crypto_eventscanner -> crypto
        # khromalabs_ataria_crypto_analysis -> crypto
        if len(parts) >= 3 and parts[0] == "khromalabs":
            return parts[2]
        if len(parts) >= 2:
            return parts[1]
        return "misc"
    return parts[0]


def render_ids(registry: Dict[str, Capability]) -> EnumBlock:
    """Level 'ids': comma-joined capability ids (Ainara's current hint)."""
    ids = sorted(registry.keys())
    text = ", ".join(ids)
    return EnumBlock(
        level="ids",
        text=text,
        approx_tokens=approx_tokens(text),
        metadata={"count": len(ids)},
    )


def render_domains(registry: Dict[str, Capability]) -> EnumBlock:
    """Level 'domains': framework-written domain menu.

    Group capability ids by domain and emit one verb-phrase line per
    domain. Capability ids are NOT revealed: the menu is a permission
    declaration over action types, not an inventory.
    """
    groups: Dict[str, List[str]] = {}
    for cap_id in sorted(registry.keys()):
        groups.setdefault(domain_of(cap_id), []).append(cap_id)
    lines = []
    coverage = {}
    for domain in sorted(groups.keys()):
        phrase = DOMAIN_PHRASES.get(domain, f"{domain} related actions")
        coverage[domain] = groups[domain]
        lines.append(f"- {phrase}")
    text = "ORAKLE capabilities by domain:\n" + "\n".join(lines)
    return EnumBlock(
        level="domains",
        text=text,
        approx_tokens=approx_tokens(text),
        metadata={"domains": {d: ids for d, ids in coverage.items()}},
    )


def render_none() -> EnumBlock:
    """Level 'none': no inventory knowledge whatsoever.

    The policy text alone must carry the delegation contract. Trigger
    recall for small models is the known risk of this level.
    """
    text = (
        "ORAKLE is a natural language delegation system: state any "
        "intent that requires real-time data or real-world actions "
        "inside <orakle>...</orakle> tags and the system handles it. "
        "No capability list is provided; the system decides what it "
        "can do."
    )
    return EnumBlock(
        level="none",
        text=text,
        approx_tokens=approx_tokens(text),
        metadata={},
    )


# --- Warming stage ----------------------------------------------------

WARMING_PROMPT_VERSION = "v0"


class WarmedRenderer:
    """Level 'warmed': the model writes its own capability summary.

    The target (assistant) model reads the LEAN payload OFFLINE during
    the boot-up process and compresses it into a domain menu in its own
    terms. Output is semi-structured and mechanically VERIFIED before
    caching: a hallucination frozen into cache would be served on every
    turn forever, worse than a stale id list.

    Cache key: (model_tag, registry fingerprint, prompt version).
    Verification failure -> graceful fallback to the 'ids' level.
    """

    def __init__(
        self,
        registry: Dict[str, Capability],
        cache_dir: Optional[str] = None,
    ):
        self.registry = registry
        self.cache_dir = cache_dir

    def warming_input(self) -> str:
        """Lean payload rendering the model reads during warming."""
        lines = []
        for cap_id in sorted(self.registry.keys()):
            cap = self.registry[cap_id]
            params = ", ".join(
                f"{p.name}({'R' if p.required else 'O'})"
                for p in cap.parameters
            )
            lines.append(
                f"{cap_id}: {cap.description}"
                + (f" [params: {params}]" if params else "")
            )
        return "\n".join(lines)

    def _verify(self, summary: Dict[str, Any]) -> Optional[List[str]]:
        """Mechanical verification of a warming summary.

        Returns a list of problems, or None if the summary is valid.
        """
        domains = summary.get("domains")
        if not isinstance(domains, list) or not domains:
            return ["summary must contain a non-empty 'domains' list"]
        registry_ids = set(self.registry.keys())
        referenced: List[str] = []
        problems: List[str] = []
        for i, dom in enumerate(domains):
            if not isinstance(dom, dict):
                problems.append(f"domains[{i}] is not an object")
                continue
            cap_ids = dom.get("capability_ids", [])
            if not isinstance(cap_ids, list) or not cap_ids:
                problems.append(f"domains[{i}] has no capability_ids")
                continue
            for cid in cap_ids:
                if cid not in registry_ids:
                    problems.append(f"hallucinated capability id: {cid}")
                referenced.append(cid)
        if problems:
            return problems
        missing = registry_ids - set(referenced)
        if missing:
            problems.append(f"uncovered capability ids: {sorted(missing)}")
        duplicated = [
            cid
            for cid in set(referenced)
            if referenced.count(cid) > 1
        ]
        if duplicated:
            problems.append(f"duplicated capability ids: {duplicated}")
        return problems or None

    def _cache_path(self, model_tag: str, reg_fp: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        safe_tag = re.sub(r"[^A-Za-z0-9._-]", "_", model_tag)
        return os.path.join(
            self.cache_dir,
            f"warming_{safe_tag}_{reg_fp}_{WARMING_PROMPT_VERSION}.json",
        )

    def render(
        self,
        model_tag: str,
        summarize_fn: Callable[[str], Dict[str, Any]],
    ) -> EnumBlock:
        """Render the warmed enumeration (with cache + verification).

        ``summarize_fn`` receives the warming input text and returns
        {"domains": [{"name": ..., "actions": ..., "capability_ids":
        [...]}]}. It is expected to wrap the LLM call; it may be a stub
        for offline dry runs.
        """
        reg_fp = fingerprint(self.registry)
        cache_path = self._cache_path(model_tag, reg_fp)

        summary = None
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as fh:
                summary = json.load(fh)
            logger.info("Warming cache hit: %s", cache_path)

        if summary is None:
            summary = summarize_fn(self.warming_input())
            problems = self._verify(summary)
            if problems:
                logger.warning(
                    "Warming summary FAILED verification for %s: %s; "
                    "falling back to 'ids' enumeration",
                    model_tag,
                    "; ".join(problems),
                )
                fallback = render_ids(self.registry)
                fallback.metadata["warmed_fallback"] = problems
                return fallback
            if cache_path:
                os.makedirs(self.cache_dir, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as fh:
                    json.dump(summary, fh, indent=1, sort_keys=True)

        lines = [
            f"- {d.get('name', '?')}: {d.get('actions', '')}"
            for d in summary.get("domains", [])
        ]
        text = "ORAKLE capabilities you can act through:\n" + "\n".join(
            lines
        )
        return EnumBlock(
            level="warmed",
            text=text,
            approx_tokens=approx_tokens(text),
            metadata={
                "model_tag": model_tag,
                "registry_fingerprint": reg_fp,
                "domains": summary.get("domains"),
            },
        )
