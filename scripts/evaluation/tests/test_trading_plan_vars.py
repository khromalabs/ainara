# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for coin-parameterized plans (plan `variables` + per-run override).

Runs under the ainara (main) venv:
    python -m unittest scripts.evaluation.tests.test_trading_plan_vars

The delta-neutral plans declare `variables: {coin: BTC}` and reference it as
{{$coin}}. A run points the same plan at ETH or SOL with
`Conductor.trigger_plan(variables={"coin": ...})`. These tests load the real
plan files and drive the Conductor's own override check, bindings snapshot and
lock, so nothing here is a replica that could drift from the real path. No step
executes: `_execute_plan` is replaced where a run would start.
"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.evaluation.tests._executor_env import (  # noqa: E402
    require_framework_deps,
)

require_framework_deps()

from ainara.bureau.conductor import Conductor  # noqa: E402
from ainara.bureau.plan import Plan, PlanValidationError  # noqa: E402
from ainara.bureau.scratchpad import Scratchpad, map_strings  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PLANS = ROOT / "plans"


def _conductor():
    c = Conductor(PLANS, llm_config={}, orakle_servers=[],
                  global_capabilities=[], step_registry={})
    c.start()
    return c


def resolve_step(conductor, plan_name, step_name, override=None):
    """Resolve a skill step's params the way _execute_plan does."""
    plan = conductor.plans[plan_name]
    bindings, error = conductor._build_static_bindings(plan, "[test]", override)
    assert error is None, error
    sp = Scratchpad(max_chars=plan.scratchpad_max_chars,
                    static_bindings=bindings)
    return map_strings(
        plan.steps[step_name].params or {},
        lambda text: sp.resolve_template(text, native_whole=True),
    )


def _join_runs():
    for t in threading.enumerate():
        if t.name.startswith("conductor-"):
            t.join(timeout=5)


class PlanVariables(unittest.TestCase):
    def setUp(self):
        self.c = _conductor()

    def test_both_plans_load_with_btc_default(self):
        self.assertEqual(self.c.plans["delta_neutral_farm"].variables,
                         {"coin": "BTC"})
        self.assertEqual(self.c.plans["delta_neutral_exit"].variables,
                         {"coin": "BTC"})

    def test_farm_default_and_override(self):
        self.assertEqual(
            resolve_step(self.c, "delta_neutral_farm", "evaluate")["coin"], "BTC")
        for coin in ("ETH", "SOL"):
            self.assertEqual(resolve_step(self.c, "delta_neutral_farm",
                                          "evaluate", {"coin": coin})["coin"],
                             coin)

    def test_exit_override(self):
        self.assertEqual(resolve_step(self.c, "delta_neutral_exit",
                                      "evaluate_exit")["coin"], "BTC")
        self.assertEqual(resolve_step(self.c, "delta_neutral_exit",
                                      "evaluate_exit", {"coin": "ETH"})["coin"],
                         "ETH")

    def test_non_string_params_pass_through(self):
        # capital_usd (a number) must not be stringified by template resolution.
        cap = resolve_step(self.c, "delta_neutral_farm", "evaluate")["capital_usd"]
        self.assertIsInstance(cap, int)

    def test_old_vars_reference_no_longer_loads(self):
        # {{vars.coin}} would now be read as a reference to a step named
        # "vars"; the plan loader must refuse it rather than run it unresolved.
        p = Path(tempfile.mkdtemp()) / "old.yaml"
        p.write_text(
            "variables:\n  coin: BTC\nsteps:\n  s:\n    type: skill\n"
            "    skill: x\n    params:\n      coin: \"{{vars.coin}}\"\n",
            encoding="utf-8")
        with self.assertRaises(PlanValidationError):
            Plan(p)


class VariableOverrideValidation(unittest.TestCase):
    def setUp(self):
        self.c = _conductor()
        self.started = []
        self.c._execute_plan = lambda *a: self.started.append(a)

    def test_unknown_name_is_refused(self):
        # A typo must not silently run the default coin.
        run_id, error = self.c.trigger_plan("delta_neutral_farm",
                                            variables={"con": "ETH"})
        self.assertIsNone(run_id)
        self.assertTrue(error.startswith("invalid_variables:"), error)
        self.assertIn("con", error)
        self.assertEqual(self.started, [])
        self.assertFalse(self.c._locks["delta_neutral_farm"].locked())

    def test_non_scalar_value_is_refused(self):
        for bad in ({"coin": {"x": 1}}, {"coin": ["ETH"]}, {"coin": None}):
            _, error = self.c.trigger_plan("delta_neutral_farm", variables=bad)
            self.assertTrue(error.startswith("invalid_variables:"), bad)

    def test_chained_reference_value_is_refused(self):
        _, error = self.c.trigger_plan("delta_neutral_farm",
                                       variables={"coin": "{{$coin}}"})
        self.assertTrue(error.startswith("invalid_variables:"), error)

    def test_non_mapping_is_refused(self):
        _, error = self.c.trigger_plan("delta_neutral_farm", variables="ETH")
        self.assertTrue(error.startswith("invalid_variables:"), error)

    def test_valid_override_reaches_the_run(self):
        _, error = self.c.trigger_plan("delta_neutral_farm",
                                       variables={"coin": "ETH"})
        self.assertIsNone(error)
        _join_runs()
        self.assertEqual(self.started[0][3], {"coin": "ETH"})

    def test_no_override_runs_with_empty_overrides(self):
        _, error = self.c.trigger_plan("delta_neutral_farm")
        self.assertIsNone(error)
        _join_runs()
        self.assertEqual(self.started[0][3], {})


class PlanLockIsPerName(unittest.TestCase):
    """Runs of one plan never overlap, whatever coin each targets.

    Chosen deliberately: `avoid_if` looks locks up by plan name, so a
    per-coin lock would stop `delta_neutral_farm`'s `avoid_if:
    [delta_neutral_exit]` from seeing an ETH exit in flight. Per-coin
    schedules are staggered, and a collision is a 409 the scheduler logs as
    a skip.
    """

    def setUp(self):
        self.c = _conductor()
        # Leave the lock held as a real run would, without executing anything.
        self.c._execute_plan = lambda *a: None

    def test_second_coin_is_refused_while_first_runs(self):
        _, error = self.c.trigger_plan("delta_neutral_exit",
                                       variables={"coin": "BTC"})
        self.assertIsNone(error)
        _, error = self.c.trigger_plan("delta_neutral_exit",
                                       variables={"coin": "ETH"})
        self.assertEqual(error, "already_running")

    def test_avoid_if_sees_any_coin_of_the_other_plan(self):
        self.c.trigger_plan("delta_neutral_exit", variables={"coin": "SOL"})
        _, error = self.c.trigger_plan("delta_neutral_farm",
                                       avoid_if=["delta_neutral_exit"],
                                       variables={"coin": "BTC"})
        self.assertEqual(error, "avoid_condition_met:delta_neutral_exit")


if __name__ == "__main__":
    unittest.main()
