# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the two-leg opener's crossing-limit planner.

executor/server.plan_hedge_legs is pure, but it lives in the daemon module, so
this test must run under the EXECUTOR venv (executor/.venv), which has Flask +
the venue SDKs installed:

    executor/.venv/Scripts/python.exe -m unittest \
        scripts.evaluation.tests.test_trading_plan_hedge_legs

Focus: the SOL open bug (2026-07-25). A taker fill needs the limit to CROSS —
sell below ref, buy above. Nearest-dollar round() sent both SOL legs to 74 (buy
below the ~74.25 market -> rested, never filled). The fix rounds directionally
(floor sell, ceil buy) so a $1 tick can never uncross a leg.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from executor.server import plan_hedge_legs  # noqa: E402


class Crossing(unittest.TestCase):
    def _legs(self, ref, cross_pct=0.05, **kw):
        return plan_hedge_legs("X", "X-USD", 1.0, ref, cross_pct, **kw)

    def _assert_crosses(self, ref):
        legs = self._legs(ref)
        sell, buy = legs["short"]["price"], legs["long"]["price"]
        self.assertLess(sell, ref, f"sell {sell} must be below ref {ref}")
        self.assertGreater(buy, ref, f"buy {buy} must be above ref {ref}")

    def test_btc_crosses(self):
        self._assert_crosses(64094.5)

    def test_eth_crosses(self):
        self._assert_crosses(1860.35)

    def test_sol_crosses(self):
        # The regression: ref 74.2455 used to round BOTH legs to 74.
        legs = self._legs(74.2455)
        self.assertEqual(legs["short"]["price"], 74)
        self.assertEqual(legs["long"]["price"], 75)

    def test_integer_ref_still_crosses(self):
        self._assert_crosses(74.0)

    def test_sub_dollar_price_refused(self):
        # A $1 tick cannot express a crossing sell below ~$1 — refuse, don't send
        # a zero/non-crossing price.
        with self.assertRaises(ValueError):
            self._legs(0.85)


class SizingGuards(unittest.TestCase):
    def test_size_floored_to_fit_cap_at_the_worse_price(self):
        # buy (ceil, =75) is the worse price; size must fit the cap THERE, not at
        # ref. 1 unit * 75 = $75 > $70 cap -> shaved down.
        legs = plan_hedge_legs("X", "X-USD", 1.0, 74.2455, 0.05, cap_notional=70.0)
        self.assertIsNotNone(legs["shaved"])
        self.assertLessEqual(legs["long"]["size"] * legs["long"]["price"], 70.0 + 1e-9)
        self.assertEqual(legs["short"]["size"], legs["long"]["size"])  # delta-neutral

    def test_quantize_floors_both_legs_equally(self):
        legs = plan_hedge_legs("X", "X-USD", 0.7539, 74.2455, 0.05, size_step=0.1)
        self.assertEqual(legs["short"]["size"], legs["long"]["size"])
        self.assertAlmostEqual(legs["long"]["size"], 0.7, places=10)

    def test_zero_size_rejected(self):
        with self.assertRaises(ValueError):
            plan_hedge_legs("X", "X-USD", 0, 100.0, 0.05)


if __name__ == "__main__":
    unittest.main()
