# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for coin-parameterized plans (the Conductor `vars` mechanism).

Runs under the ainara (main) venv:
    python -m unittest scripts.evaluation.tests.test_trading_plan_vars

A plan-level `vars:` block is seeded into the scratchpad at run start so step
params resolve {{vars.coin}}. This verifies the real delta-neutral plan files
plus the exact merge + resolution the conductor performs, so one plan file can
be pointed at BTC/ETH/SOL.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from ainara.bureau.plan import Plan, PlanValidationError  # noqa: E402
from ainara.bureau.scratchpad import Scratchpad  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PLANS = ROOT / "plans"


def resolve_step(plan, step_name, override=None):
    """Replica of trigger_plan's vars merge + _execute_plan's seed + the
    conductor param-resolution loop (conductor.py:851)."""
    run_vars = dict(plan.vars)
    if override:
        run_vars.update(override)
    sp = Scratchpad(max_chars=plan.scratchpad_max_chars)
    if run_vars:
        sp.store("vars", dict(run_vars))
    out = {}
    for k, v in (plan.steps[step_name].params or {}).items():
        out[k] = sp.resolve_template(v) if isinstance(v, str) else v
    return out


class PlanVars(unittest.TestCase):
    def setUp(self):
        self.farm = Plan(PLANS / "delta_neutral_farm.yaml")
        self.exit = Plan(PLANS / "delta_neutral_exit.yaml")

    def test_defaults_are_btc(self):
        self.assertEqual(self.farm.vars, {"coin": "BTC"})
        self.assertEqual(self.exit.vars, {"coin": "BTC"})

    def test_farm_default_and_override(self):
        self.assertEqual(resolve_step(self.farm, "evaluate")["coin"], "BTC")
        self.assertEqual(resolve_step(self.farm, "evaluate", {"coin": "ETH"})["coin"], "ETH")
        self.assertEqual(resolve_step(self.farm, "evaluate", {"coin": "SOL"})["coin"], "SOL")

    def test_non_string_params_pass_through(self):
        # capital_usd (a number) must not be stringified by template resolution;
        # only string params flow through the {{...}} resolver.
        cap = resolve_step(self.farm, "evaluate")["capital_usd"]
        self.assertIsInstance(cap, int)

    def test_exit_override(self):
        self.assertEqual(resolve_step(self.exit, "evaluate_exit")["coin"], "BTC")
        self.assertEqual(resolve_step(self.exit, "evaluate_exit", {"coin": "ETH"})["coin"], "ETH")

    def test_nested_vars_rejected(self):
        p = Path(tempfile.mkdtemp()) / "bad.yaml"
        p.write_text(
            "vars:\n  coin: {nested: no}\nsteps:\n  s:\n    type: skill\n    skill: x\n",
            encoding="utf-8")
        with self.assertRaises(PlanValidationError):
            Plan(p)


if __name__ == "__main__":
    unittest.main()
