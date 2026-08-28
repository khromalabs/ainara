# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the read-only portfolio skill's book-wide rollup + liq math.

Runs under the ainara (main) venv:
    python -m unittest scripts.evaluation.tests.test_trading_portfolio

The per-coin network reads are stubbed so this stays offline. The multi-position
dYdX liq DEGRADE (returning "liquidation unknown" when a subaccount holds >1
position) is additionally verified live against the real book in the session it
was built; here we cover the pure liq formula and the ALL-scope aggregation
(worst health, combined funding, combined unrealized PnL).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.evaluation.tests._executor_env import (  # noqa: E402
    require_framework_deps)

# Before the ainara imports below: they need the framework's dependencies,
# which the executor's virtualenv does not carry. Skips with a reason there
# instead of failing to import.
require_framework_deps()

from ainara.orakle.skills.trading import portfolio as P  # noqa: E402
from ainara.orakle.skills.trading.portfolio import TradingPortfolio  # noqa: E402


def fake_status(coin, health, funding_hr, unrl):
    """Shape a per-coin _status result the way _status_all consumes it."""
    return {
        "action": "status", "coin": coin, "health": health,
        "verdict": f"{coin} {health}", "net_delta": 0.0,
        "economics": {"net_funding_per_hour_usd": funding_hr},
        "combined_unrealized_pnl_usd": unrl,
        "liquidation": {}, "as_of": "t",
    }


class LiquidationMath(unittest.TestCase):
    def test_single_position_liq_matches_executor_formula(self):
        # Reproduces the sign/None contract of the shared formula.
        # A long whose equity exceeds notional is not liquidatable by price alone.
        self.assertIsNone(P._dydx_liquidation_price(1000, 0.01, 100.0, 0.0125))

    def test_short_liquidates_above_mark(self):
        liq = P._dydx_liquidation_price(equity=100, size_signed=-0.5,
                                        mark_px=100.0, mmf=0.0125)
        self.assertIsNotNone(liq)
        self.assertGreater(liq, 100.0)   # a short liquidates ABOVE the mark

    def test_zero_size_is_none(self):
        self.assertIsNone(P._dydx_liquidation_price(100, 0, 100.0, 0.0125))


class BookWideStatus(unittest.TestCase):
    def setUp(self):
        self.p = TradingPortfolio()

    def _patch(self, coins, statuses):
        self.p._open_coins = lambda: coins
        self.p._status = lambda coin, tol: statuses[coin]

    def test_flat_when_no_open_coins(self):
        self.p._open_coins = lambda: []
        r = self.p._status_all(15.0)
        self.assertEqual(r["health"], "flat")
        self.assertEqual(r["positions"], [])

    def test_aggregates_health_funding_and_pnl(self):
        self._patch(
            ["BTC", "ETH", "SOL"],
            {"BTC": fake_status("BTC", "ok", 0.0005, 0.02),
             "ETH": fake_status("ETH", "ok", 0.0004, 0.01),
             "SOL": fake_status("SOL", "ok", 0.001, 0.02)})
        r = self.p._status_all(15.0)
        self.assertEqual(r["scope"], "all_open")
        self.assertEqual(r["health"], "ok")
        self.assertEqual(r["summary"]["open_positions"], 3)
        self.assertAlmostEqual(r["summary"]["net_funding_per_hour_usd"], 0.0019, places=6)
        self.assertAlmostEqual(r["summary"]["combined_unrealized_pnl_usd"], 0.05, places=6)
        self.assertFalse(r["summary"]["attention_needed"])

    def test_worst_health_wins_and_flags_attention(self):
        self._patch(
            ["BTC", "ETH"],
            {"BTC": fake_status("BTC", "ok", 0.0005, 0.0),
             "ETH": fake_status("ETH", "critical", 0.0004, 0.0)})
        r = self.p._status_all(15.0)
        self.assertEqual(r["health"], "critical")
        self.assertTrue(r["summary"]["attention_needed"])

    def test_unmeasurable_funding_leaves_net_none(self):
        self._patch(
            ["BTC", "ETH"],
            {"BTC": fake_status("BTC", "ok", None, 0.0),   # funding unreadable
             "ETH": fake_status("ETH", "ok", 0.0004, 0.0)})
        r = self.p._status_all(15.0)
        self.assertIsNone(r["summary"]["net_funding_per_hour_usd"])
        self.assertIsNotNone(r["summary"]["note"])


class SingleCoinBreadcrumb(unittest.TestCase):
    """A coin-scoped status must never hide the rest of an open book — even when
    the LLM router passes a specific symbol for a general question."""

    def setUp(self):
        self.p = TradingPortfolio()

    def test_surfaces_other_open_positions(self):
        self.p._open_coins = lambda: ["BTC", "ETH", "SOL"]
        self.p._status = lambda coin, tol: fake_status(coin, "ok", 0.0005, 0.0)
        r = self.p.run(action="status", coin="BTC")
        self.assertEqual(r["coin"], "BTC")
        self.assertEqual(r["other_open_positions"], ["ETH", "SOL"])
        self.assertIn("ETH", r["hint"])

    def test_no_breadcrumb_when_that_is_the_only_open_coin(self):
        self.p._open_coins = lambda: ["BTC"]
        self.p._status = lambda coin, tol: fake_status(coin, "ok", 0.0005, 0.0)
        r = self.p.run(action="status", coin="BTC")
        self.assertNotIn("other_open_positions", r)


if __name__ == "__main__":
    unittest.main()
