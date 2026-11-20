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

"""Sweep orchestrator + CLI for the routing benchmark.

Executes (arm x enumeration x registry-size x assistant x selector)
combinations over a query-case dataset and emits stage-attributed run
records plus aggregate summaries.

Real runs require the ainara package (matcher model) and configured LLM
backends; --dry-run validates the entire pipeline offline with stub LLMs
and a stub matcher, executing no model and no skill.

Usage (from the repo root):

  # Offline pipeline validation:
  python scripts/evaluation/routing_benchmark/runner.py --dry-run

  # Snapshot the live registry from a running Orakle server:
  python scripts/evaluation/routing_benchmark/runner.py --snapshot \\
      --orakle-url http://localhost:8100 \\
      --snapshot-out scripts/evaluation/routing_benchmark/fixtures/registry.json

  # A real cell (flat arm, ids enumeration, one model for both roles):
  python scripts/evaluation/routing_benchmark/runner.py \\
      --snapshot-file <registry.json> \\
      --arm flat --enumeration ids \\
      --assistant "provider:model" --out results/flat_ids.json

  # Orakle arm, split-brain (different selector):
  python scripts/evaluation/routing_benchmark/runner.py \\
      --snapshot-file <registry.json> \\
      --arm orakle --enumeration ids \\
      --assistant "provider:big-model" --selector "provider:small-model"
"""

import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
))

from scripts.evaluation.routing_benchmark import dataset as ds  # noqa: E402
from scripts.evaluation.routing_benchmark import (  # noqa: E402
    enumerations as en,
)
from scripts.evaluation.routing_benchmark.arms import (  # noqa: E402
    FlatArm,
    OrakleArm,
)
from scripts.evaluation.routing_benchmark.metrics import (  # noqa: E402
    aggregate,
    format_summary,
)
from scripts.evaluation.routing_benchmark.payload import (  # noqa: E402
    load_snapshot,
    snapshot_registry,
)
from scripts.evaluation.routing_benchmark.stubs import (  # noqa: E402
    StubLLM,
    StubMatcher,
)

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOT = os.path.join(
    os.path.dirname(__file__), "fixtures", "registry.json"
)
DEFAULT_DATASET = os.path.join(
    os.path.dirname(__file__), "datasets", "seed.jsonl"
)


def build_llm(spec: str):
    """Build a real LLM backend from a 'provider:model' spec.

    Wraps ainara.framework.llm.create_llm_backend; kept lazy so the
    harness stays importable without the ainara package.
    """
    from ainara.framework.llm import create_llm_backend

    return create_llm_backend(selected_provider=spec)


def build_matcher():
    """Build the real transformer matcher (lazy; downloads on first use)."""
    from ainara.framework.matcher.transformers import (
        OrakleMatcherTransformers,
    )

    return OrakleMatcherTransformers()


def build_registry(
    snapshot_path: str,
    cases,
    target_n=None,
    seed: int = 0,
):
    """Assemble the registry for a sweep cell.

    The registry always contains every skill the dataset references
    (otherwise route cases can never score correct), padded to
    target_n with distractors when requested.
    """
    registry = load_snapshot(snapshot_path)
    needed = {c.expected_skill_id for c in cases if c.expected_skill_id}
    missing = needed - set(registry.keys())
    if missing:
        raise SystemExit(
            f"Snapshot {snapshot_path} is missing skills referenced by "
            f"the dataset: {sorted(missing)}"
        )
    if target_n and target_n > len(registry):
        from scripts.evaluation.routing_benchmark.dataset import (
            synthesize_distractors,
        )

        registry = dict(registry)
        registry.update(
            synthesize_distractors(target_n - len(registry), seed=seed)
        )
    return registry


def build_enumeration_blocks(registry, enumeration: str, warmed_tag=None):
    """Render the requested enumeration level(s) for a registry."""
    wanted = en.LEVELS if enumeration == "all" else [enumeration]
    blocks = {}
    for level in wanted:
        if level == "ids":
            blocks[level] = en.render_ids(registry)
        elif level == "domains":
            blocks[level] = en.render_domains(registry)
        elif level == "none":
            blocks[level] = en.render_none()
        elif level == "warmed":
            renderer = en.WarmedRenderer(
                registry, cache_dir=os.path.join(
                    os.path.dirname(__file__), ".warming_cache"
                )
            )
            tag = warmed_tag or "default"
            blocks[level] = renderer.render(
                tag, summarize_fn=default_warming_summarize
            )
        else:
            raise SystemExit(f"unknown enumeration level: {level}")
    return blocks


def default_warming_summarize(warming_input: str):
    """Real warming pass through the assistant LLM is TODO: the JSON
    contract is defined and verified mechanically; wiring the actual
    model call goes here once the boot-up integration lands."""
    raise SystemExit(
        "warmed enumeration requires a real warming pass; wire "
        "default_warming_summarize to an LLM backend (see "
        "enumerations.WarmedRenderer for the contract) or use the "
        "offline stub in the tests"
    )


def run_cell(
    arm,
    cases,
    registry,
) -> list:
    records = []
    for case in cases:
        logger.info("[%s] case %s ...", arm.name, case.id)
        try:
            record = arm.run(case)
        except Exception as exc:  # keep the sweep alive; log + record
            logger.exception("case %s failed: %s", case.id, exc)
            continue
        records.append(record)
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="offline validation with stub LLM/matcher")
    parser.add_argument("--snapshot", action="store_true",
                        help="fetch the live registry and exit")
    parser.add_argument("--orakle-url",
                        default="http://localhost:8100")
    parser.add_argument("--snapshot-out", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--snapshot-file", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--arm", default="orakle",
                        choices=["flat", "orakle", "both"])
    parser.add_argument("--enumeration", default="all",
                        choices=["ids", "domains", "warmed", "none",
                                 "all"])
    parser.add_argument("--assistant", default=None,
                        help="'provider:model' for real runs")
    parser.add_argument("--selector", default=None,
                        help="'provider:model' (split-brain)")
    parser.add_argument("--n", type=int, default=None,
                        help="target registry size (pad w/ distractors)")
    parser.add_argument("--warmed-tag", default="default")
    parser.add_argument("--out", default=None, help="results JSON path")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(levelname)s %(name)s: %(message)s")

    if args.snapshot:
        registry = snapshot_registry(args.orakle_url, args.snapshot_out)
        print(
            f"Snapshot OK: {len(registry)} capabilities -> "
            f"{args.snapshot_out}"
        )
        return 0

    cases = ds.load_dataset(args.dataset)

    if args.dry_run:
        return _dry_run(args, cases)

    if not args.assistant:
        parser.error(
            "real runs need --assistant 'provider:model' (or --dry-run)"
        )

    registry = build_registry(args.snapshot_file, cases, target_n=args.n)
    assistant = build_llm(args.assistant)
    selector = build_llm(args.selector) if args.selector else assistant

    arms = []
    if args.arm in ("flat", "both"):
        arms.append(FlatArm(
            assistant_llm=assistant, selector_llm=selector,
            registry=registry,
        ))
    if args.arm in ("orakle", "both"):
        matcher = build_matcher()
        for cap_id, cap in registry.items():
            matcher.register_skill(cap_id, cap.description)
        orakle = OrakleArm(
            matcher=matcher, assistant_llm=assistant,
            selector_llm=selector, registry=registry,
        )
        arms.append(orakle)

    records = []
    for arm in arms:
        if isinstance(arm, OrakleArm):
            blocks = build_enumeration_blocks(
                registry, args.enumeration, warmed_tag=args.warmed_tag
            )
            for level, block in blocks.items():
                arm.set_enumeration(block)
                logger.info("=== cell: orakle/%s ===", level)
                records.extend(run_cell(arm, cases, registry))
        else:
            records.extend(run_cell(arm, cases, registry))

    return _finish(records, args)


def _dry_run(args, cases) -> int:
    """Offline pipeline validation: stub LLMs, stub matcher, seed data."""
    registry = build_registry(args.snapshot_file, cases, target_n=args.n)
    matcher = StubMatcher()
    for cap_id, cap in registry.items():
        matcher.register_skill(cap_id, cap.description)

    flat_llm = StubLLM(
        responses=[(
            r"\{",
            json.dumps({
                "skill_id": "tools_calculator",
                "parameters": {"expression": "stub"},
            }),
        )],
        default=json.dumps({"skill_id": None}),
    )
    assistant = StubLLM(
        responses=[(
            r"weather|news|clipboard|file|browser|app|portfolio|mercado"
            r"|calculate|fetch",
            "<orakle>stub intent</orakle>",
        )],
        default="I know the answer from my own knowledge.",
        model_tag="stub-assistant",
    )
    selector = StubLLM(
        responses=[(
            r"\{",
            json.dumps({"skill_id": "tools_calculator",
                        "parameters": {}}),
        )],
        default=json.dumps({"skill_id": None}),
        model_tag="stub-selector",
    )

    records = []
    if args.arm in ("flat", "both"):
        records.extend(run_cell(
            FlatArm(assistant_llm=flat_llm, registry=registry),
            cases, registry,
        ))
    if args.arm in ("orakle", "both"):
        orakle = OrakleArm(
            matcher=matcher, assistant_llm=assistant,
            selector_llm=selector, registry=registry,
        )
        blocks = build_enumeration_blocks(
            registry, "ids" if args.enumeration == "all"
            else args.enumeration
        )
        for level, block in blocks.items():
            orakle.set_enumeration(block)
            records.extend(run_cell(orakle, cases, registry))

    print(f"DRY RUN: {len(records)} records; "
          f"{sum(1 for r in records if r.errors)} with errors")
    return _finish(records, args)


def _finish(records, args) -> int:
    summary = aggregate(records)
    print(format_summary(summary))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        doc = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "config": {
                "arm": args.arm,
                "enumeration": args.enumeration,
                "assistant": args.assistant,
                "selector": args.selector,
                "n": args.n,
                "dataset": args.dataset,
            },
            "summary": summary,
            "records": [r.to_dict() for r in records],
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        print(f"Results -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
