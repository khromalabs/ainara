# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the portfolio skill's reporting guards.

Runs under the ainara (main) venv:
    python -m unittest scripts.evaluation.tests.test_trading_portfolio_guards

Each class here covers a case where the reporting layer previously said
something confidently false. They are offline: every venue read is stubbed, and
the guards under test are pure functions of already-fetched data.

The failure each one pins down was observed, not imagined:

  - a review window that caught a trade's CLOSE but not its OPEN reported two
    coins as live positions, with `entry_px` set to the price their closing
    orders filled at, while both venues were flat;
  - the 7-day default could not contain a 14-day hold, which is what put the
    reconstructor in that state in the first place;
  - a hedge that earned two cents was reported as $63.03 at 4577% annualized.
"""

import json
import os
import sys
import tempfile
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


def fill(t, sz, px, buy, fee=0.0):
    """One normalized fill row, shaped as _raw_fills_* produces them."""
    return {"t": t, "sz": sz, "px": px, "buy": buy,
            "signed": sz if buy else -sz, "fee": fee}


class IncompleteWindowEpisodes(unittest.TestCase):
    """A trailing episode the venue says is not there is not an open position."""

    # A single SELL from a zero baseline: the walk reads it as opening a short,
    # because it cannot see the buy that opened the position before the window.
    TRAILING = [fill(1_000, 0.5, 100.0, buy=False, fee=0.05)]

    def test_venue_flat_marks_incomplete_not_open(self):
        eps = P._episodes_from_rows(self.TRAILING, [], "hyperliquid", live_size=0.0)
        self.assertEqual(len(eps), 1)
        ep = eps[0]
        self.assertTrue(ep["incomplete_window"])
        self.assertFalse(ep["open"])

    def test_incomplete_window_withholds_the_fabricated_entry(self):
        # entry_px here was the CLOSING fill's price. Reporting it as an entry is
        # what invented a live position on a flat account.
        ep = P._episodes_from_rows(
            self.TRAILING, [], "hyperliquid", live_size=0.0)[0]
        self.assertIsNone(ep["entry_px"])
        self.assertIsNone(ep["size"])
        self.assertEqual(ep["first_fill_px_in_window"], 100.0)
        self.assertIn("does not reach", ep["note"])

    def test_incomplete_window_reports_no_realized_price_pnl(self):
        # The cash held is one side of a round trip whose other side is outside
        # the window — precisely the number that must not read as a result.
        ep = P._episodes_from_rows(
            self.TRAILING, [], "hyperliquid", live_size=0.0)[0]
        self.assertIsNone(ep["realized_price_pnl_usd"])

    def test_venue_still_holding_is_a_real_open_position(self):
        ep = P._episodes_from_rows(
            self.TRAILING, [], "hyperliquid", live_size=-0.5)[0]
        self.assertTrue(ep["open"])
        self.assertFalse(ep["incomplete_window"])
        self.assertEqual(ep["entry_px"], 100.0)

    def test_unknown_live_size_leaves_reconstruction_unchanged(self):
        # None means "could not read", and a failed read is never allowed to be
        # the reason a review cannot be produced.
        ep = P._episodes_from_rows(
            self.TRAILING, [], "hyperliquid", live_size=None)[0]
        self.assertTrue(ep["open"])
        self.assertFalse(ep["incomplete_window"])

    def test_a_completed_round_trip_is_untouched(self):
        rows = [fill(1_000, 0.5, 100.0, buy=True),
                fill(2_000, 0.5, 110.0, buy=False)]
        ep = P._episodes_from_rows(rows, [], "hyperliquid", live_size=0.0)[0]
        self.assertFalse(ep["open"])
        self.assertFalse(ep["incomplete_window"])
        self.assertEqual(ep["realized_price_pnl_usd"], 5.0)  # 55 in, 50 out


class IncompleteWindowRoundTrip(unittest.TestCase):
    def setUp(self):
        self.p = TradingPortfolio()

    def _ep(self, **over):
        base = {"opened_at": "2026-08-01T00:00:00+00:00", "closed_at": None,
                "open": False, "incomplete_window": False, "funding_usd": 1.0,
                "fees_usd": 0.1, "realized_price_pnl_usd": 0.2}
        base.update(over)
        return base

    def test_incomplete_leg_yields_incomplete_status(self):
        t = self.p._round_trip("BTC", self._ep(incomplete_window=True,
                                               realized_price_pnl_usd=None), None)
        self.assertEqual(t["status"], "incomplete_window")

    def test_incomplete_is_not_reported_as_open(self):
        t = self.p._round_trip("BTC", self._ep(incomplete_window=True,
                                               realized_price_pnl_usd=None), None)
        self.assertNotEqual(t["status"], "open")
        self.assertIn("NOT an open position", t["note"])
        self.assertIn("both venues are flat", t["note"].lower())

    def test_incomplete_withholds_every_realized_figure(self):
        t = self.p._round_trip("BTC", self._ep(incomplete_window=True,
                                               realized_price_pnl_usd=None), None)
        self.assertIsNone(t["realized_net_usd"])
        self.assertIsNone(t["price_pnl_usd"])
        self.assertIsNone(t["closed_at"])
        self.assertIsNone(t["hold_hours"])

    def test_a_genuinely_open_leg_still_wins_over_incomplete(self):
        # One leg open and one incomplete is a live position, not a flat one.
        t = self.p._round_trip("BTC", self._ep(open=True),
                               self._ep(incomplete_window=True))
        self.assertEqual(t["status"], "open")

    def test_closed_pair_is_unaffected(self):
        closed = self._ep(closed_at="2026-08-02T00:00:00+00:00")
        t = self.p._round_trip("BTC", closed, closed)
        self.assertEqual(t["status"], "closed")
        self.assertIsNotNone(t["realized_net_usd"])


class ReviewSummaryCountsIncomplete(unittest.TestCase):
    def setUp(self):
        self.p = TradingPortfolio()
        self.p._live_size = lambda venue, coin: 0.0

    def test_incomplete_counted_separately_from_still_open(self):
        # Both legs present only as trailing fills, both venues flat.
        self.p._episodes_hl = lambda c, s: P._episodes_from_rows(
            [fill(1_000, 0.5, 100.0, buy=False)], [], "hyperliquid", 0.0)
        self.p._episodes_dydx = lambda c, s: P._episodes_from_rows(
            [fill(1_100, 0.5, 100.0, buy=True)], [], "dydx", 0.0)
        s = self.p._review("BTC", 7.0)["summary"]
        self.assertEqual(s["incomplete_window_round_trips"], 1)
        self.assertEqual(s["still_open"], 0)

    def test_summary_note_offers_a_longer_window(self):
        self.p._episodes_hl = lambda c, s: P._episodes_from_rows(
            [fill(1_000, 0.5, 100.0, buy=False)], [], "hyperliquid", 0.0)
        self.p._episodes_dydx = lambda c, s: []
        s = self.p._review("BTC", 7.0)["summary"]
        self.assertIn("lookback_days", s["note"])
        self.assertIn("flat, not", s["note"])

    def test_incomplete_contributes_nothing_to_realized_totals(self):
        self.p._episodes_hl = lambda c, s: P._episodes_from_rows(
            [fill(1_000, 0.5, 100.0, buy=False, fee=9.0)], [], "hyperliquid", 0.0)
        self.p._episodes_dydx = lambda c, s: []
        s = self.p._review("BTC", 7.0)["summary"]
        self.assertIsNone(s["total_realized_net_usd"])
        self.assertIsNone(s["hedge_realized_net_usd"])


class DefaultLookback(unittest.TestCase):
    """The window has to be able to contain the hold it is reconstructing."""

    def setUp(self):
        self._real = P.config.get

    def tearDown(self):
        P.config.get = self._real

    def _hold(self, days):
        P.config.get = lambda key, default=None: (
            days if key == "trading.carry_engine.expected_hold_days" else default)

    def test_floors_at_ninety_days(self):
        # A 14-day hold * 6 = 84, which is below the floor. The old 7.0 default
        # could not see a completed trade at all.
        self._hold(14.0)
        self.assertEqual(P._default_lookback_days(), P.MIN_REVIEW_LOOKBACK_DAYS)
        self.assertGreaterEqual(P._default_lookback_days(), 90.0)

    def test_scales_with_a_longer_configured_hold(self):
        self._hold(28.0)
        self.assertEqual(P._default_lookback_days(), 168)

    def test_survives_a_junk_config_value(self):
        self._hold("not-a-number")
        self.assertEqual(P._default_lookback_days(), P.MIN_REVIEW_LOOKBACK_DAYS)

    def test_review_uses_the_derived_default_when_unset(self):
        self._hold(28.0)
        p = TradingPortfolio()
        seen = {}
        p._review = lambda coin, lb: seen.setdefault("lb", lb) or {"ok": True}
        p.run(action="review", coin="BTC")
        self.assertEqual(seen["lb"], 168)

    def test_an_explicit_lookback_is_still_honoured(self):
        self._hold(28.0)
        p = TradingPortfolio()
        seen = {}
        p._review = lambda coin, lb: seen.setdefault("lb", lb) or {"ok": True}
        p.run(action="review", coin="BTC", lookback_days=3)
        self.assertEqual(seen["lb"], 3.0)


class FillCoverage(unittest.TestCase):
    """A window that counts nothing sums to zero and looks perfectly healthy."""

    def test_complete_when_both_legs_round_trip(self):
        cov = P._fill_coverage({
            "hyperliquid": {"fills": 2, "signed": 0.0, "gross": 1.0},
            "dydx": {"fills": 2, "signed": 0.0, "gross": 1.0}})
        self.assertTrue(cov["complete"])
        self.assertEqual(cov["fills_counted"], 4)
        self.assertEqual(cov["reasons"], [])

    def test_a_leg_with_no_fills_is_incomplete(self):
        cov = P._fill_coverage({
            "hyperliquid": {"fills": 0, "signed": 0.0, "gross": 0.0},
            "dydx": {"fills": 2, "signed": 0.0, "gross": 1.0}})
        self.assertFalse(cov["complete"])
        self.assertIn("no hyperliquid fills", cov["reasons"][0])

    def test_an_empty_window_is_incomplete_not_flat(self):
        # This is the case that sums to $0.00 and passes every magnitude test.
        cov = P._fill_coverage({
            "hyperliquid": {"fills": 0, "signed": 0.0, "gross": 0.0},
            "dydx": {"fills": 0, "signed": 0.0, "gross": 0.0}})
        self.assertFalse(cov["complete"])
        self.assertEqual(cov["fills_counted"], 0)
        self.assertEqual(len(cov["reasons"]), 2)

    def test_fills_that_do_not_return_to_flat_are_incomplete(self):
        cov = P._fill_coverage({
            "hyperliquid": {"fills": 1, "signed": 0.5, "gross": 0.5},
            "dydx": {"fills": 2, "signed": 0.0, "gross": 1.0}})
        self.assertFalse(cov["complete"])
        self.assertIn("do not round-trip", cov["reasons"][0])

    def test_float_dust_does_not_trip_the_residual_check(self):
        cov = P._fill_coverage({
            "hyperliquid": {"fills": 4, "signed": 1e-12, "gross": 40.0},
            "dydx": {"fills": 4, "signed": -1e-12, "gross": 40.0}})
        self.assertTrue(cov["complete"])

    def test_residual_is_judged_relative_to_size_traded(self):
        # The same absolute residual is dust on a large leg and a real gap on a
        # small one, so the test has to scale with what was traded.
        big = P._fill_coverage({
            "hyperliquid": {"fills": 2, "signed": 1e-5, "gross": 1000.0}})
        small = P._fill_coverage({
            "hyperliquid": {"fills": 2, "signed": 1e-5, "gross": 0.001}})
        self.assertTrue(big["complete"])
        self.assertFalse(small["complete"])


class PricePnlFault(unittest.TestCase):
    """Numbers a delta-neutral hedge cannot produce are reported as faults."""

    GOOD_COVERAGE = {"complete": True, "fills_counted": 4, "legs": {}, "reasons": []}

    def _realized(self, price_pnl, coverage=None):
        return {"price_pnl_usd": price_pnl, "funding_usd": 1.0, "fees_usd": 0.1,
                "net_usd": 0.9, "coverage": coverage or self.GOOD_COVERAGE}

    def test_clean_trade_has_no_fault(self):
        self.assertIsNone(
            P._price_pnl_fault(self._realized(1.0), 1000.0, 11.42, True))

    def test_incomplete_coverage_faults_before_anything_else(self):
        # Checked first and without reference to notional: a zero-fill window is
        # a fault at any size, and its numbers look flawless.
        bad = {"complete": False, "fills_counted": 0, "legs": {},
               "reasons": ["no dydx fills fall inside this trade's window"]}
        f = P._price_pnl_fault(self._realized(0.0, bad), 1000.0, 0.0, True)
        self.assertIsNotNone(f)
        self.assertEqual(f["field"], "coverage")
        self.assertIn("no dydx fills", f["detail"])

    def test_coverage_fault_fires_even_with_no_notional(self):
        bad = {"complete": False, "fills_counted": 0, "legs": {}, "reasons": ["x"]}
        f = P._price_pnl_fault(self._realized(0.0, bad), None, None, False)
        self.assertIsNotNone(f)
        self.assertEqual(f["field"], "coverage")

    def test_price_pnl_above_two_percent_of_notional_is_a_fault(self):
        f = P._price_pnl_fault(self._realized(63.03), 1000.0, 50.0, True)
        self.assertIsNotNone(f)
        self.assertEqual(f["field"], "price_pnl_usd")
        self.assertEqual(f["pct_of_notional"], 6.3)

    def test_price_pnl_just_under_the_limit_passes(self):
        f = P._price_pnl_fault(self._realized(19.0), 1000.0, 11.0, True)
        self.assertIsNone(f)

    def test_absurd_annualized_net_is_a_fault(self):
        # The figure that motivated the guard: 4577% on a hedge that earned $0.02.
        f = P._price_pnl_fault(self._realized(0.5), 1000.0, 4577.0, True)
        self.assertIsNotNone(f)
        self.assertEqual(f["field"], "net_annual_pct_notional")

    def test_absurd_annual_is_ignored_over_an_unreliable_hold(self):
        # Annualizing a few hours produces nonsense by construction; that is what
        # `annualized_metrics_reliable` already says, and it is not a data fault.
        self.assertIsNone(
            P._price_pnl_fault(self._realized(0.5), 1000.0, 4577.0, False))

    def test_a_good_quarter_is_not_refused(self):
        # The guard exists to refuse the absurd, not to adjudicate performance.
        self.assertIsNone(
            P._price_pnl_fault(self._realized(1.0), 1000.0, 120.0, True))

    def test_absent_coverage_means_not_asserted_never_asserted_fine(self):
        r = {"price_pnl_usd": 0.0, "funding_usd": 0.0, "fees_usd": 0.0,
             "net_usd": 0.0}
        self.assertIsNone(P._price_pnl_fault(r, 1000.0, 0.0, True))

    def test_the_guard_never_raises_on_junk(self):
        self.assertIsNone(P._price_pnl_fault({}, 0, None, False))
        self.assertIsNone(P._price_pnl_fault(None, None, None, True))


class AnalyticsExcludesFaultedTrades(unittest.TestCase):
    """A total that silently averages in a fabricated figure is the worse total."""

    def setUp(self):
        self.p = TradingPortfolio()
        self._rows = P._ledger.trades
        # No _benchmark stub needed: it is opt-in and these calls do not ask for
        # it, so nothing here reaches the network. See test_trading_benchmark.py.

    def tearDown(self):
        P._ledger.trades = self._rows

    def _ledger(self, rows):
        P._ledger.trades = lambda coin=None, status=None: rows

    ROW = {"coin": "BTC", "opened_at": "2026-08-01T00:00:00+00:00",
           "closed_at": "2026-08-15T00:00:00+00:00", "notional_usd": 1000.0,
           "pred_smoothed_spread_annual_pct": 9.38}

    def test_faulted_trade_is_flagged_and_excluded_from_the_total(self):
        self._ledger([dict(self.ROW)])
        # 63.03 on 1000 notional is 6.3% — impossible for a hedge that cancels.
        self.p._realized_in_window = lambda c, lo, hi: {
            "funding_usd": 0.02, "fees_usd": 0.0, "price_pnl_usd": 63.03,
            "net_usd": 63.05,
            "coverage": {"complete": True, "fills_counted": 4, "legs": {},
                         "reasons": []}}
        out = self.p._analytics("BTC")
        trade = out["trades"][0]
        self.assertFalse(trade["data_quality_ok"])
        self.assertEqual(trade["data_quality_fault"]["field"], "price_pnl_usd")
        self.assertEqual(out["summary"]["total_realized_net_usd"], 0.0)
        self.assertEqual(out["summary"]["data_quality"]["trades_faulted"], 1)

    def test_the_summary_note_says_report_the_fault_not_the_number(self):
        self._ledger([dict(self.ROW)])
        self.p._realized_in_window = lambda c, lo, hi: {
            "funding_usd": 0.02, "fees_usd": 0.0, "price_pnl_usd": 63.03,
            "net_usd": 63.05,
            "coverage": {"complete": True, "fills_counted": 4, "legs": {},
                         "reasons": []}}
        note = self.p._analytics("BTC")["summary"]["note"]
        self.assertIn("FAILED the data-quality guard", note)
        self.assertIn("Report the fault, not the number", note)

    def test_faulted_trade_is_kept_out_of_the_capture_ratio(self):
        self._ledger([dict(self.ROW)])
        self.p._realized_in_window = lambda c, lo, hi: {
            "funding_usd": 0.02, "fees_usd": 0.0, "price_pnl_usd": 63.03,
            "net_usd": 63.05,
            "coverage": {"complete": True, "fills_counted": 4, "legs": {},
                         "reasons": []}}
        out = self.p._analytics("BTC")
        self.assertEqual(out["summary"]["trades_scored"], 0)
        self.assertIsNone(out["summary"]["mean_funding_capture_ratio"])

    def test_a_clean_trade_reports_ok_and_counts_normally(self):
        self._ledger([dict(self.ROW)])
        self.p._realized_in_window = lambda c, lo, hi: {
            "funding_usd": 3.6, "fees_usd": 1.7, "price_pnl_usd": -0.4,
            "net_usd": 1.5,
            "coverage": {"complete": True, "fills_counted": 4, "legs": {},
                         "reasons": []}}
        out = self.p._analytics("BTC")
        self.assertTrue(out["trades"][0]["data_quality_ok"])
        self.assertNotIn("data_quality_fault", out["trades"][0])
        self.assertEqual(out["summary"]["total_realized_net_usd"], 1.5)
        self.assertEqual(out["summary"]["data_quality"]["trades_faulted"], 0)

    def test_both_rate_denominators_are_named(self):
        self._ledger([dict(self.ROW)])
        self.p._realized_in_window = lambda c, lo, hi: {
            "funding_usd": 3.6, "fees_usd": 1.7, "price_pnl_usd": -0.4,
            "net_usd": 1.5,
            "coverage": {"complete": True, "fills_counted": 4, "legs": {},
                         "reasons": []}}
        realized = self.p._analytics("BTC")["trades"][0]["realized"]
        # Quoting one rate against the other's base is a real error, so the base
        # each one used is stated rather than left to be inferred.
        self.assertIn("funding_rate_denominator_usd", realized)
        self.assertIn("net_rate_denominator_usd", realized)
        self.assertEqual(realized["funding_rate_denominator_usd"], 1000.0)

    def test_the_notional_basis_admits_what_it_cannot_account_for(self):
        self._ledger([dict(self.ROW)])
        self.p._realized_in_window = lambda c, lo, hi: {
            "funding_usd": 3.6, "fees_usd": 1.7, "price_pnl_usd": -0.4,
            "net_usd": 1.5,
            "coverage": {"complete": True, "fills_counted": 4, "legs": {},
                         "reasons": []}}
        trade = self.p._analytics("BTC")["trades"][0]
        self.assertIn("NOT accounted for", trade["notional_basis"])
        self.assertIsNone(trade["mark_drift_pct"])


class HyperliquidLiquidationNote(unittest.TestCase):
    """No null liquidation distance may render as 'safe'."""

    def _leg(self, mark_px, liq_px):
        p = TradingPortfolio()
        p._target = lambda venue: ("mainnet", "0xabc")
        pos = {"coin": "BTC", "szi": "0.5",
               "positionValue": str(0.5 * mark_px) if mark_px else "0",
               "entryPx": "100", "unrealizedPnl": "0", "marginUsed": "50"}
        if liq_px is not None:
            pos["liquidationPx"] = str(liq_px)

        class R:
            @staticmethod
            def json():
                return {"marginSummary": {"accountValue": "1000"},
                        "assetPositions": [{"position": pos}]}

        P.requests.post = lambda *a, **k: R()
        return p._hl_leg("BTC")

    def setUp(self):
        self._post = P.requests.post

    def tearDown(self):
        P.requests.post = self._post

    def test_no_liquidation_price_is_benign_and_says_so(self):
        leg = self._leg(mark_px=100.0, liq_px=None)
        self.assertIsNone(leg["liq_distance_pct"])
        self.assertIn("not liquidatable by price alone", leg["liq_note"])

    def test_unreadable_mark_is_reported_as_unmonitored_not_safe(self):
        leg = self._leg(mark_px=0.0, liq_px=None)
        self.assertIsNone(leg["liq_distance_pct"])
        self.assertIn("unmonitored", leg["liq_note"])
        self.assertIn("not safe", leg["liq_note"])

    def test_a_real_liquidation_price_carries_no_note(self):
        leg = self._leg(mark_px=100.0, liq_px=80.0)
        self.assertIsNotNone(leg["liq_distance_pct"])
        self.assertIsNone(leg["liq_note"])


class InheritedWatchdogAlarm(unittest.TestCase):
    """An alarm left by a dead process is not an emergency this loop is raising."""

    def setUp(self):
        from executor import watchdog as W
        self.W = W
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "alarm.json")
        self.wd = W.Watchdog.__new__(W.Watchdog)
        self.wd.alarm_file = self.path
        self.wd._alarm_published = False

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_no_file_is_a_no_op(self):
        self.wd._adopt_inherited_alarm()
        self.assertFalse(self.wd._alarm_published)
        self.assertFalse(os.path.exists(self.path))

    def test_existing_alarm_is_marked_inherited_not_deleted(self):
        # Deleting it would discard information about why the last process died.
        self._write({"alarm": "broken_hedge", "ts": 1_700_000_000.0})
        self.wd._adopt_inherited_alarm()
        with open(self.path, encoding="utf-8") as fh:
            got = json.load(fh)
        self.assertTrue(got["inherited_from_previous_process"])
        self.assertIn("no longer", got["inherited_note"])
        self.assertEqual(got["alarm"], "broken_hedge")

    def test_the_original_timestamp_is_preserved(self):
        # The age of the alarm is the whole basis on which /health decides it is
        # stale. Refreshing `ts` would make a dead process's alarm read as live.
        self._write({"alarm": "broken_hedge", "ts": 1_700_000_000.0})
        self.wd._adopt_inherited_alarm()
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["ts"], 1_700_000_000.0)

    def test_adoption_arms_the_all_clear_path(self):
        # _alarm_published is what lets the first clean poll retire the file.
        self._write({"alarm": "broken_hedge", "ts": 1.0})
        self.wd._adopt_inherited_alarm()
        self.assertTrue(self.wd._alarm_published)

    def test_an_unreadable_alarm_file_is_still_adopted(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.wd._adopt_inherited_alarm()
        self.assertTrue(self.wd._alarm_published)

    def test_a_non_dict_payload_is_still_adopted(self):
        self._write(["not", "a", "dict"])
        self.wd._adopt_inherited_alarm()
        self.assertTrue(self.wd._alarm_published)


if __name__ == "__main__":
    unittest.main()
