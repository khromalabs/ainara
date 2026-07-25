# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the carry engine's deterministic maths + funding fetch.

Runs under the ainara (main) venv:
    python -m unittest scripts.evaluation.tests.test_trading_carry_engine

Covers the EMA/backtest/evaluate core (no network) and the Hyperliquid funding
pagination fix (mocked): a single fundingHistory call caps at 500 rows from
startTime, so a wide request used to yield a STALE oldest-500 window ending days
in the past. The paginator must advance past the cap and reach 'now'.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from ainara.orakle.skills.trading import carry_engine as CE  # noqa: E402
from ainara.orakle.skills.trading.carry_engine import (  # noqa: E402
    HOUR_MS, TradingCarryEngine)


class PureMaths(unittest.TestCase):
    def setUp(self):
        self.e = TradingCarryEngine()

    def test_ema_constant_series_is_the_constant(self):
        self.assertAlmostEqual(self.e._ema([0.5] * 50, 10), 0.5, places=9)

    def test_ema_series_same_length(self):
        self.assertEqual(len(self.e._ema_series([1, 2, 3, 4], 3)), 4)

    def test_evaluate_opens_shorting_the_higher_funder(self):
        a = [0.0002] * 400   # hyperliquid funds higher
        b = [0.0] * 400
        r = self.e.evaluate("hyperliquid", "dydx", a, b)
        self.assertEqual(r["action"], "open")
        self.assertEqual(r["short_venue"], "hyperliquid")
        self.assertEqual(r["long_venue"], "dydx")

    def test_evaluate_sits_out_when_spread_flat(self):
        a = b = [0.00005] * 400
        r = self.e.evaluate("hyperliquid", "dydx", a, b)
        self.assertEqual(r["action"], "sit_out")

    def test_backtest_positive_persistent_spread_nets_positive(self):
        a = [0.0002] * 400
        b = [0.0] * 400
        r = self.e.backtest("hyperliquid", "dydx", a, b, span_hours=5)
        self.assertEqual(r["mode"], "backtest_walk_forward")
        self.assertGreater(r["net_annual_pct_notional"], 0)
        self.assertGreater(r["uptime_pct"], 90)  # spread clears threshold ~always

    def test_backtest_needs_enough_samples(self):
        r = self.e.backtest("hyperliquid", "dydx", [0.0001] * 10, [0.0] * 10,
                            span_hours=336)
        self.assertIn("error", r)


class HLFundingPagination(unittest.TestCase):
    """The fix: forward-paginate past HL's 500-row cap so the window reaches now."""

    def _fake_hl(self, total_hours, cap=500):
        now = int(time.time() * 1000) // HOUR_MS * HOUR_MS
        h0 = now - (total_hours - 1) * HOUR_MS
        rows = [{"time": h0 + i * HOUR_MS, "fundingRate": 0.00001}
                for i in range(total_hours)]

        class _Resp:
            def __init__(self, data):
                self._d = data

            def json(self):
                return self._d

        def post(url, json=None, timeout=None):
            start = json["startTime"]
            return _Resp([r for r in rows if r["time"] >= start][:cap])

        return post, now

    def test_collects_more_than_the_500_cap_and_reaches_now(self):
        fake_post, now = self._fake_hl(720, cap=500)
        with patch.object(CE.requests, "post", fake_post):
            hist = TradingCarryEngine()._hl_funding_history("BTC", "mainnet", 720)
        self.assertGreater(len(hist), 500)          # broke past the single-call cap
        self.assertGreaterEqual(max(hist), now - HOUR_MS)  # window ends at 'now'

    def test_short_window_stops_cleanly(self):
        fake_post, now = self._fake_hl(50, cap=500)
        with patch.object(CE.requests, "post", fake_post):
            hist = TradingCarryEngine()._hl_funding_history("BTC", "mainnet", 50)
        self.assertEqual(len(hist), 50)


if __name__ == "__main__":
    unittest.main()
