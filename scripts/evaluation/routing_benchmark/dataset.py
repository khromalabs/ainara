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

"""Query case dataset for the routing benchmark.

Case categories:

  route   - a capability applies; expected skill id (+ optionally
            expected parameters).
  abstain - NO capability applies; the system must not invoke anything.
            The model over-triggering is cheap (Orakle returns "no
            match"); the failure asymmetry makes under-triggering the
            dangerous direction, so abstain cases measure precision.
  trap    - a capability applies, but the query tempts an answer from
            parametric memory (stale or subtly wrong). The model
            answering from memory is the critical silent failure this
            benchmark exists to measure: "answered confidently instead
            of delegating".

Delicacy grades action sensitivity and drives the delicate-action
trigger recall metric (the "I can't access your clipboard" refusal
reflex for undeclared actions):

  innocuous - read-only or informational actions
  delicate  - mutating or sensitive actions (clipboard writes, file
              operations, trading orders)

Expected parameters may be an empty dict, meaning "do not score
parameters" (only skill-id correctness is evaluated).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .payload import Capability

logger = logging.getLogger(__name__)

CATEGORIES = ("route", "abstain", "trap")
DELICACY_LEVELS = ("innocuous", "delicate")


@dataclass
class QueryCase:
    """One evaluation query with its ground truth."""

    id: str
    category: str  # route | abstain | trap
    query: str
    expected_skill_id: Optional[str] = None
    expected_params: Dict[str, Any] = field(default_factory=dict)
    delicacy: str = "innocuous"
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "query": self.query,
            "expected_skill_id": self.expected_skill_id,
            "expected_params": self.expected_params,
            "delicacy": self.delicacy,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueryCase":
        return cls(
            id=data["id"],
            category=data["category"],
            query=data["query"],
            expected_skill_id=data.get("expected_skill_id"),
            expected_params=data.get("expected_params", {}) or {},
            delicacy=data.get("delicacy", "innocuous"),
            tags=data.get("tags", []) or [],
        )


def load_dataset(path: str) -> List[QueryCase]:
    """Load and validate a JSONL dataset."""
    cases: List[QueryCase] = []
    seen_ids = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data = json.loads(line)
                case = QueryCase.from_dict(data)
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(
                    f"{path}:{line_no}: invalid case ({exc})"
                ) from exc
            _validate_case(case, path, line_no)
            if case.id in seen_ids:
                raise ValueError(f"{path}:{line_no}: duplicate id {case.id}")
            seen_ids.add(case.id)
            cases.append(case)
    if not cases:
        raise ValueError(f"{path}: dataset is empty")
    logger.info("Loaded %d query cases from %s", len(cases), path)
    return cases


def _validate_case(case: QueryCase, path: str, line_no: int) -> None:
    where = f"{path}:{line_no}"
    if case.category not in CATEGORIES:
        raise ValueError(
            f"{where}: category must be one of {CATEGORIES}, "
            f"got {case.category!r}"
        )
    if case.delicacy not in DELICACY_LEVELS:
        raise ValueError(
            f"{where}: delicacy must be one of {DELICACY_LEVELS}, "
            f"got {case.delicacy!r}"
        )
    if case.category == "route" and not case.expected_skill_id:
        raise ValueError(f"{where}: route case requires expected_skill_id")
    if case.category == "abstain" and case.expected_skill_id:
        raise ValueError(
            f"{where}: abstain case must not have expected_skill_id"
        )


def validate_against_registry(
    cases: List[QueryCase], registry: Dict[str, Capability]
) -> List[str]:
    """Cross-check dataset ground truth against a capability registry.

    Returns a list of warnings (does not raise): route/trap cases must
    reference skills that exist in the registry the sweep will run
    against, otherwise the case can never be scored 'correct'.
    """
    warnings = []
    registry_ids = set(registry.keys())
    for case in cases:
        if case.expected_skill_id and case.expected_skill_id not in registry_ids:
            warnings.append(
                f"case {case.id}: expected skill "
                f"{case.expected_skill_id!r} not in registry"
            )
    return warnings


def synthesize_distractors(n: int, seed: int = 0) -> Dict[str, Capability]:
    """Generate plausible-but-fake capabilities to pad the registry.

    Used for the registry-size (N) axis when the real registry is too
    small. Distractors are semantically confusable on purpose (word
    combinations drawn from real domains). TODO: replace with real
    public tool corpora (e.g. BFCL tool definitions converted to lean
    payloads) for the publishable runs.
    """
    import random

    rng = random.Random(seed)
    verbs = [
        "search", "list", "analyze", "track", "convert", "monitor",
        "translate", "summarize", "compare", "visualize", "schedule",
        "archive",
    ]
    objects = [
        "podcasts", "invoices", "recipes", "flights", "repositories",
        "playlists", "contacts", "documents", "transactions", "trends",
        "bookmarks", "subtitles",
    ]
    qualifiers = [
        "local", "historical", "upcoming", "encrypted", "popular",
        "archived", "personal", "public", "draft", "pending",
    ]
    registry: Dict[str, Capability] = {}
    used = set()
    while len(registry) < n:
        name = (
            f"{rng.choice(qualifiers)}_{rng.choice(objects)}_"
            f"{rng.choice(verbs)}"
        )
        if name in used:
            continue
        used.add(name)
        description = (
            f"{rng.choice(verbs).capitalize()} {rng.choice(qualifiers)} "
            f"{rng.choice(objects)} based on the given criteria."
        )
        registry[f"distractor_{name}"] = Capability(
            id=f"distractor_{name}",
            description=description,
            parameters=[
                Capability.from_dict(
                    {
                        "id": "x",
                        "description": "",
                        "parameters": [
                            {
                                "name": "query",
                                "type": "string",
                                "description": "What to act on",
                                "required": True,
                            }
                        ],
                    }
                ).parameters[0]
            ],
        )
    return registry
