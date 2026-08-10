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

    def test_backtest_defaults_mirror_old_single_threshold_behavior(self):
        a = [0.0002] * 400
        b = [0.0] * 400
        r = self.e.backtest("hyperliquid", "dydx", a, b, span_hours=5,
                            threshold_annual_pct=4.0)
        # Unset exit_threshold/min_hold must report as "same as entry" / "no
        # floor" — the exact values that reproduce the pre-hysteresis behavior.
        self.assertEqual(r["exit_threshold_annual_pct"], 4.0)
        self.assertEqual(r["min_hold_hours"], 0.0)


class BacktestHysteresisAndMinHold(unittest.TestCase):
    """A separate (lower) exit threshold and a minimum-hold floor are new knobs
    on top of the walk-forward backtest — this tests they actually cut fee
    churn on a spread that oscillates near the entry line, which is exactly
    what real dYdX funding does (single-hour outliers that bounce back)."""

    def setUp(self):
        self.e = TradingCarryEngine()

    def test_lower_exit_threshold_reduces_churn(self):
        # span_hours=1 makes the EMA track the raw spread exactly each hour
        # (alpha = 2/(1+1) = 1), so the smoothed signal is fully controllable.
        # Alternate HIGH (clears both thresholds) / MIDDLE (clears the exit
        # threshold but not the entry threshold) blocks: a single-threshold
        # run must exit-then-reenter every block; hysteresis should stay
        # positioned through the MIDDLE blocks instead.
        high, middle = 0.0002, 0.000005
        block = [high] * 5 + [middle] * 5
        a = block * 20  # 200 hours
        b = [0.0] * len(a)

        baseline = self.e.backtest("hyperliquid", "dydx", a, b, span_hours=1,
                                   threshold_annual_pct=10.0)
        hysteresis = self.e.backtest("hyperliquid", "dydx", a, b, span_hours=1,
                                     threshold_annual_pct=10.0,
                                     exit_threshold_annual_pct=2.0)

        self.assertLess(hysteresis["entries_per_year"], baseline["entries_per_year"])
        self.assertLess(hysteresis["fees_annual_pct_notional"],
                        baseline["fees_annual_pct_notional"])
        # Confirms it actually stayed positioned through the MIDDLE blocks
        # rather than merely entering less often for some other reason.
        self.assertGreater(hysteresis["uptime_pct"], baseline["uptime_pct"])

    def test_min_hold_suppresses_a_premature_exit(self):
        # Enter on an initial HIGH hour, dip LOW for 2 hours (shorter than the
        # min_hold floor), then HIGH again. Without a floor this exits at the
        # first LOW hour and re-enters at the next HIGH hour (2 entries);
        # with a floor spanning the dip it never leaves position (1 entry).
        high, low = 0.0002, 0.0
        a = [high] * 3 + [low] * 2 + [high] * 15
        b = [0.0] * len(a)

        baseline = self.e.backtest("hyperliquid", "dydx", a, b, span_hours=1,
                                   threshold_annual_pct=4.0)
        held = self.e.backtest("hyperliquid", "dydx", a, b, span_hours=1,
                               threshold_annual_pct=4.0, min_hold_hours=6.0)

        self.assertGreater(baseline["entries_per_year"], held["entries_per_year"])
        self.assertEqual(held["min_hold_hours"], 6.0)


class BookState(unittest.TestCase):
    """_book_state's public clearinghouseState read (mocked, no network) — the
    book-wide exposure gate's data source. HL is always one of the two legs of
    every hedge, so its position list is the whole book's aggregate view."""

    @staticmethod
    def _fake_post(asset_positions):
        class _Resp:
            def __init__(self, data):
                self._d = data

            def json(self):
                return self._d

        def post(url, json=None, timeout=None):
            if json and json.get("type") == "clearinghouseState":
                return _Resp({"assetPositions": asset_positions})
            return _Resp({})
        return post

    def test_counts_and_sums_excluding_given_coin(self):
        positions = [
            {"position": {"coin": "BTC", "szi": "-0.001",
                          "positionValue": "65.0"}},
            {"position": {"coin": "ETH", "szi": "0.03", "positionValue": "90.0"}},
        ]
        with patch.object(CE.requests, "post", self._fake_post(positions)):
            count, notional = TradingCarryEngine()._book_state(exclude_coin="ETH")
        self.assertEqual(count, 1)
        self.assertAlmostEqual(notional, 65.0)

    def test_flat_positions_excluded(self):
        positions = [{"position": {"coin": "BTC", "szi": "0.0",
                                   "positionValue": "0.0"}}]
        with patch.object(CE.requests, "post", self._fake_post(positions)):
            count, notional = TradingCarryEngine()._book_state()
        self.assertEqual((count, notional), (0, 0.0))

    def test_unreadable_returns_none_none(self):
        def raising_post(*a, **k):
            raise RuntimeError("boom")
        with patch.object(CE.requests, "post", raising_post):
            count, notional = TradingCarryEngine()._book_state()
        self.assertEqual((count, notional), (None, None))


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
