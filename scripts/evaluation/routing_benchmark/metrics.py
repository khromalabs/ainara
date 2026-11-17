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

"""Scoring and stage attribution.

Every run record is decomposed into stages so failures can be attributed
to the layer that caused them -- the metric dimension flat-context
benchmarks skip:

  trigger    (assistant)  did it delegate at all?
  retrieval  (embeddings) was the true skill among the candidates?
  selection  (selector)   did it pick the right skill?
  parameters (selector)   did the args honor the Annotated contract?

Classifications:

  correct               full pipeline succeeded (or clean abstention)
  silent_memory_answer  assistant answered without delegating on a
                        route/trap case -- the critical failure
  retrieval_miss        expected skill not in the candidate set
                        (guaranteed failure: flat arms cannot fail
                        this way, which is the point)
  selection_miss        skill in candidates, wrong pick or no pick
  param_partial         right skill, incomplete/invalid parameters
  param_miss            right skill, params scored 0
  abstain_correct       abstain case, nothing invoked
  abstain_false_positive abstain case, something was invoked
"""

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Classifications that count as a correct end-to-end outcome.
CORRECT_CLASSES = ("correct", "abstain_correct")


@dataclass
class RunRecord:
    """Full provenance for one (case, arm, configuration) execution."""

    case_id: str
    category: str
    delicacy: str
    arm: str
    enumeration: str
    assistant_model: str
    selector_model: str
    n_registry: int
    query: str
    expected_skill_id: Optional[str]
    expected_params: Dict[str, Any]
    classification: str = "unclassified"
    trigger: Dict[str, Any] = field(default_factory=dict)
    retrieval: Dict[str, Any] = field(default_factory=dict)
    selection: Dict[str, Any] = field(default_factory=dict)
    parameter_score: Optional[float] = None
    context_chars: int = 0
    latencies: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def now() -> float:
    return time.monotonic()


def parameter_score(
    extracted: Dict[str, Any], expected: Dict[str, Any]
) -> float:
    """Score extracted parameters against the expected contract.

    1.0 = perfect. Empty expected contract -> 1.0 by convention ("do
    not score parameters"), matching the seed dataset convention.
    Self-contained on purpose (no coupling to the legacy evaluator's
    metrics module) so the harness stays importable without the
    ainara package.
    """
    if not expected:
        return 1.0
    if not extracted:
        return 0.0

    def norm(value: Any) -> str:
        return str(value).strip().lower()

    hits = 0
    for name, expected_value in expected.items():
        got = extracted.get(name)
        if got is None:
            continue
        if norm(got) == norm(expected_value):
            hits += 1.0
        elif str(expected_value).lower() in str(got).lower():
            hits += 0.5  # subsumed value (e.g. sentence contains term)
    return hits / len(expected)


def expected_rank(matches: List[Dict[str, Any]], skill_id: str) -> Optional[int]:
    """1-based rank of skill_id in the candidate list, or None."""
    for i, match in enumerate(matches, 1):
        if match.get("skill_id") == skill_id:
            return i
    return None


def classify(case_category: str, record: Dict[str, Any]) -> str:
    """Attribute the outcome of one run record to a stage.

    ``record`` needs: emitted (bool), candidates (list of dicts with
    skill_id), selected_skill_id (str|None), parameter_score (float).
    """
    expected = record.get("expected_skill_id")
    emitted = bool(record.get("emitted"))
    selected = record.get("selected_skill_id")
    has_selection = bool(selected)

    if case_category == "abstain":
        if emitted or has_selection:
            return "abstain_false_positive"
        return "abstain_correct"

    # route / trap
    if not emitted and not has_selection:
        return "silent_memory_answer"
    if case_category in ("route", "trap") and expected not in (None, ""):
        candidates = record.get("candidates")
        retrieval_ran = record.get(
            "retrieval_ran",
            bool(candidates),  # unspecified: infer from presence
        )
        if retrieval_ran and candidates is not None:
            candidate_ids = [c.get("skill_id") for c in candidates]
            if expected not in candidate_ids:
                return "retrieval_miss"
    if selected != expected:
        return "selection_miss"
    score = record.get("parameter_score")
    if score is not None:
        if score <= 0.0:
            return "param_miss"
        if score < 1.0:
            return "param_partial"
    return "correct"


def aggregate(records: List[RunRecord]) -> Dict[str, Any]:
    """Aggregate run records into summary metrics.

    Groups: all, by arm, by enumeration, by category, by delicacy,
    (arm, enumeration). Counts classifications, plus trigger and
    retrieval metrics where applicable, plus token/latency means.
    """
    def group_stats(group: List[RunRecord]) -> Dict[str, Any]:
        n = len(group) or 1
        classes: Dict[str, int] = {}
        for rec in group:
            classes[rec.classification] = (
                classes.get(rec.classification, 0) + 1
            )
        correct = sum(classes.get(c, 0) for c in CORRECT_CLASSES)

        # Trigger stage: over route/trap cases only.
        act = [r for r in group if r.category in ("route", "trap")]
        acted = [r for r in act if r.trigger.get("emitted")]
        # Silent memory answers = critical failure class.
        silent = [
            r
            for r in act
            if r.classification == "silent_memory_answer"
        ]

        # Retrieval stage: records that carry candidates.
        retr = [
            r
            for r in group
            if r.retrieval.get("expected_rank") is not None
            or r.retrieval.get("candidates") is not None
        ]
        hits = [
            r for r in retr if r.retrieval.get("expected_rank") is not None
        ]
        ranks = [
            r.retrieval["expected_rank"]
            for r in hits
            if isinstance(r.retrieval.get("expected_rank"), int)
        ]
        mrr = (
            sum(1.0 / rank for rank in ranks) / len(retr) if retr else None
        )

        ctx = [r.context_chars for r in group]
        lat = [
            r.latencies.get("total", 0.0)
            for r in group
            if r.latencies.get("total")
        ]
        return {
            "n": len(group),
            "accuracy": round(correct / n, 4),
            "classifications": classes,
            "trigger_recall": (
                round(len(acted) / len(act), 4) if act else None
            ),
            "silent_memory_rate": (
                round(len(silent) / len(act), 4) if act else None
            ),
            "retrieval_recall": (
                round(len(hits) / len(retr), 4) if retr else None
            ),
            "retrieval_mrr": round(mrr, 4) if mrr is not None else None,
            "mean_context_chars": (
                round(sum(ctx) / n, 1) if ctx else 0
            ),
            "mean_total_latency_s": (
                round(sum(lat) / len(lat), 3) if lat else None
            ),
        }

    def by_key(records_list: List[RunRecord], attr: str) -> Dict[str, Any]:
        groups: Dict[str, List[RunRecord]] = {}
        for rec in records_list:
            groups.setdefault(str(getattr(rec, attr)), []).append(rec)
        return {k: group_stats(v) for k, v in sorted(groups.items())}

    summary: Dict[str, Any] = {
        "overall": group_stats(records),
        "by_arm": by_key(records, "arm"),
        "by_enumeration": by_key(records, "enumeration"),
        "by_category": by_key(records, "category"),
        "by_delicacy": by_key(records, "delicacy"),
    }

    # The pairing cell: (arm, enumeration).
    cells: Dict[str, List[RunRecord]] = {}
    for rec in records:
        cells.setdefault(f"{rec.arm}/{rec.enumeration}", []).append(rec)
    summary["by_cell"] = {
        k: group_stats(v) for k, v in sorted(cells.items())
    }
    return summary


def format_summary(summary: Dict[str, Any]) -> str:
    """Human-readable summary table (fits an 80-col terminal)."""
    lines = ["", "=== routing benchmark summary ==="]
    overall = summary.get("overall", {})
    lines.append("-- overall --")
    lines.append(
        f"  {'all':<28} acc={overall['accuracy']:.3f} "
        f"trig={_fmt(overall['trigger_recall'])} "
        f"silent={_fmt(overall['silent_memory_rate'])} "
        f"retr={_fmt(overall['retrieval_recall'])} "
        f"ctx={overall['mean_context_chars']:.0f}ch"
    )
    for scope in ("by_cell", "by_delicacy"):
        section = summary.get(scope, {})
        lines.append(f"-- {scope} --")
        for key, stats in section.items():
            lines.append(
                f"  {key:<28} acc={stats['accuracy']:.3f} "
                f"trig={_fmt(stats['trigger_recall'])} "
                f"silent={_fmt(stats['silent_memory_rate'])} "
                f"retr={_fmt(stats['retrieval_recall'])} "
                f"ctx={stats['mean_context_chars']:.0f}ch"
            )
    lines.append("")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{value:.3f}"
