# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the held-hedge benchmark.

Runs under the ainara (main) venv:
    python -m unittest scripts.evaluation.tests.test_trading_benchmark

The benchmark answers the one question that establishes whether the decision
rule earns its place: did choosing WHEN to be positioned beat simply opening the
hedge once and holding it? Nothing here touches the network — the public funding
series and the carry engine are stubbed.

Three things it has to get right, because getting them wrong is how a timing
layer flatters itself, and there is a test class for each:

  - the direction is CAUSAL (the side the first trade took, not the better one);
  - the denominator is the WHOLE window (carry forgone while flat is a real cost
    of timing, and charging the rule only for the hours it showed up hides it);
  - both sides pay the SAME execution basis (charging the rule its real fees and
    slippage against a benchmark charged one modelled fee is a handicap, not a
    comparison, and the bias scales with the number of round trips).

And one it has to refuse: a verdict is the output nobody re-derives, so it is
withheld whenever its inputs or its subject are absent.
"""

import datetime
import os
import sys
import unittest
from unittest.mock import patch

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

HOUR_MS = 3_600_000


def _iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).isoformat()


class BenchmarkBase(unittest.TestCase):
    """A 10-day window with a flat, positive funding spread.

    Hyperliquid pays 0.0001/hour, dYdX pays nothing, so a hedge short on
    Hyperliquid collects the difference. The default fixture is two 2-day trades
    inside that window, which is 40% occupancy — low enough for a verdict.
    """

    T0 = 1_750_000_000_000 // HOUR_MS * HOUR_MS
    GOOD_COVERAGE = {"complete": True, "fills_counted": 4, "legs": {},
                     "reasons": []}

    def setUp(self):
        self.lo = self.T0
        self.hi = self.T0 + 240 * HOUR_MS
        self.hl = {self.T0 + i * HOUR_MS: 0.0001 for i in range(241)}
        self.dy = {self.T0 + i * HOUR_MS: 0.0 for i in range(241)}
        self.p = TradingPortfolio()

    def trade(self, open_ms, close_ms, hold_days, *, net=5.0, fees=1.0,
              price_pnl=-0.5, short_venue="hyperliquid", notional=1000.0,
              coverage=None):
        return {
            "opened_at": _iso(open_ms), "closed_at": _iso(close_ms),
            "short_venue": short_venue, "hold_days": hold_days,
            "notional_usd": notional, "size": 0.01,
            "realized": {
                "net_usd": net, "fees_usd": fees, "price_pnl_usd": price_pnl,
                "net_annual_pct_notional": 11.0,
                "coverage": self.GOOD_COVERAGE if coverage is None else coverage,
            },
        }

    def _engine(self, hl=None, dy=None, raises=None, fee_fraction=0.002):
        outer = self

        class FakeEngine:
            def _hl_funding_history(self, coin, network, hours):
                if raises:
                    raise raises
                return outer.hl if hl is None else hl

            def _dydx_funding_history(self, coin, network, hours):
                return outer.dy if dy is None else dy

            def _round_trip_cost_fraction(self, a, b):
                return fee_fraction

        return FakeEngine

    def bench(self, trades, **kw):
        with patch("ainara.orakle.skills.trading.carry_engine."
                   "TradingCarryEngine", self._engine(**kw)):
            return self.p._benchmark("BTC", trades)

    def two_trades(self, **kw):
        """Two 2-day trades inside the 10-day window -> 40% occupancy."""
        return [self.trade(self.lo, self.lo + 48 * HOUR_MS, 2.0, **kw),
                self.trade(self.lo + 100 * HOUR_MS, self.hi, 2.0, **kw)]


class BenchmarkComparison(BenchmarkBase):
    """The arithmetic, checked against hand-computed values."""

    def test_held_hedge_accrues_the_public_spread_over_the_whole_window(self):
        # 241 inclusive hourly stamps * 0.0001 * $1000 notional.
        b = self.bench(self.two_trades())
        self.assertEqual(b["window"]["funding_hours"], 241)
        self.assertAlmostEqual(b["held"]["gross_funding_usd"], 24.1, places=4)

    def test_funding_comes_from_the_public_series_not_account_payments(self):
        # The account has no funding rows for the hours it sat flat, which are
        # exactly the hours the benchmark is being paid for. 241 hours of public
        # history against 96 hours positioned.
        b = self.bench(self.two_trades())
        self.assertGreater(b["window"]["funding_hours"],
                           b["decision_rule"]["hours_positioned"])

    def test_both_sides_are_charged_the_same_execution_basis(self):
        # The rule paid $2.00 fees and $1.00 slippage over 2 round trips, so one
        # round trip cost $1.50 — and that is exactly what the held hedge pays
        # for its single round trip.
        b = self.bench(self.two_trades())
        self.assertAlmostEqual(b["execution_cost_per_round_trip_usd"], 1.5)
        self.assertEqual(b["held"]["round_trips"], 1)
        self.assertEqual(b["decision_rule"]["round_trips"], 2)
        self.assertAlmostEqual(b["held"]["fees_usd"], 1.0)
        self.assertAlmostEqual(b["decision_rule"]["fees_usd"], 2.0)
        self.assertIn("measured cost per round trip", b["execution_cost_basis"])

    def test_the_gap_is_the_difference_between_the_two_nets(self):
        b = self.bench(self.two_trades())
        self.assertAlmostEqual(b["held"]["net_usd"], 22.6, places=4)
        self.assertAlmostEqual(b["decision_rule"]["net_usd"], 10.0, places=4)
        self.assertAlmostEqual(b["gap_usd"], -12.6, places=4)

    def test_the_decomposition_sums_exactly_to_the_gap(self):
        # A decomposition that does not add up invites the reader to trust
        # whichever term suits them.
        b = self.bench(self.two_trades())
        d = b["gap_decomposition"]
        total = (d["funding_usd"] + d["fees_usd"] + d["slippage_usd"]
                 + d.get("rounding_usd", 0.0))
        self.assertAlmostEqual(total, b["gap_usd"], places=4)

    def test_the_funding_basis_admits_the_missing_mark_series(self):
        # It is the one term here that is knowably approximate.
        b = self.bench(self.two_trades())
        self.assertIn("NOT accounted for", b["funding_basis"])

    def test_modelled_fees_are_used_and_declared_when_nothing_was_measured(self):
        # Falling back is fine; falling back silently is not, because the two
        # sides then stop being charged alike.
        trades = self.two_trades()
        for t in trades:
            t["realized"]["fees_usd"] = None
            t["realized"]["price_pnl_usd"] = None
        b = self.bench(trades)
        self.assertAlmostEqual(b["execution_cost_per_round_trip_usd"], 2.0)
        self.assertIn("NOT charged alike", b["execution_cost_basis"])
        self.assertNotIn("gap_decomposition", b)


class BenchmarkCausalDirection(BenchmarkBase):
    """The side is the one the first trade took, not the one that wins."""

    def test_direction_follows_the_first_trade_even_when_it_is_the_worse_one(self):
        # First trade short dYdX — the losing side against this spread — and a
        # later one short Hyperliquid. Picking the better side after the fact
        # would benchmark against hindsight and flatter almost any rule.
        trades = [
            self.trade(self.lo, self.lo + 48 * HOUR_MS, 2.0, short_venue="dydx"),
            self.trade(self.lo + 100 * HOUR_MS, self.hi, 2.0,
                       short_venue="hyperliquid"),
        ]
        b = self.bench(trades)
        self.assertEqual(b["side"], "short_dydx")
        self.assertLess(b["held"]["gross_funding_usd"], 0)

    def test_first_is_by_time_not_by_list_order(self):
        trades = [
            self.trade(self.lo + 100 * HOUR_MS, self.hi, 2.0,
                       short_venue="hyperliquid"),
            self.trade(self.lo, self.lo + 48 * HOUR_MS, 2.0, short_venue="dydx"),
        ]
        self.assertEqual(self.bench(trades)["side"], "short_dydx")

    def test_short_hyperliquid_collects_a_positive_spread(self):
        b = self.bench(self.two_trades())
        self.assertEqual(b["side"], "short_hyperliquid")
        self.assertGreater(b["held"]["gross_funding_usd"], 0)


class BenchmarkOccupancy(BenchmarkBase):
    """Carry forgone while flat is a cost of timing, so the window is the base."""

    def test_denominator_is_the_whole_window_not_the_time_positioned(self):
        b = self.bench(self.two_trades())
        self.assertAlmostEqual(b["decision_rule"]["hours_positioned"], 96.0)
        self.assertAlmostEqual(b["decision_rule"]["window_hours"], 240.0)
        self.assertAlmostEqual(b["decision_rule"]["occupancy_pct"], 40.0)

    def test_occupancy_never_exceeds_one_hundred_percent(self):
        # hold_days is measured over fills and the window over the ledger's two
        # stamps; mixing them once let occupancy round above 100%.
        b = self.bench([self.trade(self.lo, self.hi, 99.0)])
        self.assertLessEqual(b["decision_rule"]["occupancy_pct"], 100.0)


class BenchmarkVerdict(BenchmarkBase):
    """A verdict is the one output nobody re-derives."""

    def test_verdict_is_rendered_when_the_rule_actually_sat_out(self):
        b = self.bench(self.two_trades())
        self.assertIn("beat_holding", b)
        self.assertFalse(b["beat_holding"])
        self.assertIn("LOST", b["verdict"])
        self.assertNotIn("verdict_withheld", b)

    def test_beat_holding_is_true_when_the_rule_wins(self):
        b = self.bench(self.two_trades(net=500.0))
        self.assertTrue(b["beat_holding"])
        self.assertIn("BEAT", b["verdict"])

    def test_verdict_withheld_when_the_rule_held_the_whole_window(self):
        # It never chose to sit out, so there is no timing decision to judge and
        # `beat_holding` would be a claim about execution wearing the
        # benchmark's clothes. One trade spans its own window exactly, which is
        # why this is judged on occupancy rather than by counting trades.
        b = self.bench([self.trade(self.lo, self.hi, 10.0)])
        self.assertEqual(b["decision_rule"]["occupancy_pct"], 100.0)
        self.assertNotIn("beat_holding", b)
        self.assertNotIn("verdict", b)
        self.assertIn("never chose to sit out", b["verdict_withheld"][0])

    def test_a_withheld_verdict_still_reports_the_comparison(self):
        # Refusing the conclusion is not refusing the evidence.
        b = self.bench([self.trade(self.lo, self.hi, 10.0)])
        self.assertIn("held", b)
        self.assertIn("gap_usd", b)
        self.assertIn("deliberately ABSENT", b["note"])


class BenchmarkRefusesBadInput(BenchmarkBase):
    """It refuses on its own evidence rather than trusting an upstream flag."""

    def test_implausible_price_pnl_yields_an_error_and_no_verdict(self):
        b = self.bench(self.two_trades(price_pnl=63.03))
        self.assertIn("error", b)
        self.assertNotIn("beat_holding", b)
        self.assertNotIn("verdict", b)
        self.assertEqual(b["data_quality"][0]["field"], "price_pnl_usd")
        self.assertIn("deliberately ABSENT", b["note"])

    def test_an_incomplete_window_is_refused_though_it_looks_clean(self):
        # $0.00 from a window that counted no fills is what a healthy hedge also
        # reports, so no magnitude test would catch it.
        bad = {"complete": False, "fills_counted": 0, "legs": {},
               "reasons": ["no dydx fills fall inside this trade's window"]}
        b = self.bench(self.two_trades(net=0.0, price_pnl=0.0, coverage=bad))
        self.assertIn("error", b)
        self.assertEqual(b["data_quality"][0]["field"], "coverage")
        self.assertNotIn("beat_holding", b)

    def test_it_refuses_even_when_the_upstream_flag_was_never_set(self):
        # _benchmark_input_faults re-derives the test, so a caller that forgot
        # to run the guard cannot buy a verdict by omission.
        faults = P._benchmark_input_faults([
            {"opened_at": "a", "closed_at": "b", "notional_usd": 1000.0,
             "hold_days": 14.0,
             "realized": {"price_pnl_usd": 63.03, "net_usd": 63.05,
                          "fees_usd": 0.0}}])
        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0]["field"], "price_pnl_usd")

    def test_a_clean_trade_produces_no_input_faults(self):
        self.assertEqual(P._benchmark_input_faults(self.two_trades()), [])


class BenchmarkNeverRaises(BenchmarkBase):
    """Analytics that cannot fetch a benchmark must still report the trades."""

    def test_a_funding_fetch_failure_is_reported_not_raised(self):
        b = self.bench(self.two_trades(), raises=RuntimeError("indexer 503"))
        self.assertIn("could not read public funding history", b["error"])
        self.assertNotIn("beat_holding", b)

    def test_no_aligned_funding_history_is_a_note_not_a_verdict(self):
        b = self.bench(self.two_trades(), hl={}, dy={})
        self.assertIn("no aligned public funding history", b["note"])
        self.assertNotIn("beat_holding", b)

    def test_no_trades_with_a_notional_is_a_note(self):
        self.assertIn("nothing to compare", self.bench([])["note"])

    def test_a_zero_length_window_is_a_note(self):
        b = self.bench([self.trade(self.lo, self.lo, 0.0)])
        self.assertIn("span no time", b["note"])
        self.assertNotIn("beat_holding", b)


class ExecutionCost(unittest.TestCase):
    """Slippage is signed, and 'nothing measured' is not 'free'."""

    def _t(self, fees, price_pnl):
        return {"realized": {"fees_usd": fees, "price_pnl_usd": price_pnl}}

    def test_slippage_is_the_price_pnl_with_its_sign_flipped(self):
        cost, fees, slippage = P._execution_cost([self._t(1.0, -0.5)])
        self.assertAlmostEqual(fees, 1.0)
        self.assertAlmostEqual(slippage, 0.5)
        self.assertAlmostEqual(cost, 1.5)

    def test_a_favourable_fill_is_a_credit_not_a_charge(self):
        # Charging a round trip that filled well as though it cost something
        # would be the same error as ignoring slippage, in the other direction.
        _, _, slippage = P._execution_cost([self._t(1.0, 0.5)])
        self.assertAlmostEqual(slippage, -0.5)

    def test_cost_is_per_round_trip(self):
        cost, _, _ = P._execution_cost([self._t(1.0, -0.5), self._t(1.0, -0.5)])
        self.assertAlmostEqual(cost, 1.5)

    def test_nothing_measured_returns_none_rather_than_zero(self):
        self.assertIsNone(P._execution_cost([self._t(None, None)]))
        self.assertIsNone(P._execution_cost([]))

    def test_a_measured_zero_is_a_real_answer_and_is_honoured(self):
        self.assertIsNotNone(P._execution_cost([self._t(0.0, 0.0)]))


class AnnualPct(unittest.TestCase):
    def test_annualizes_over_the_hold(self):
        # $10 on $1000 held for 365 days is 1%/yr.
        self.assertAlmostEqual(P._annual_pct(10.0, 1000.0, 365.0), 1.0)

    def test_returns_none_rather_than_dividing_by_zero(self):
        self.assertIsNone(P._annual_pct(10.0, 0, 14.0))
        self.assertIsNone(P._annual_pct(10.0, 1000.0, 0))
        self.assertIsNone(P._annual_pct(None, 1000.0, 14.0))


class BenchmarkTally(unittest.TestCase):
    """The book-wide view counts verdicts; it does not manufacture one."""

    BY_COIN = {
        "BTC": {"benchmark": {"beat_holding": True}},
        "ETH": {"benchmark": {"beat_holding": False}},
        "SOL": {"benchmark": {"verdict_withheld": ["held the whole window"]}},
        "DOGE": {"benchmark": {"error": "could not read public funding history"}},
        "XRP": {"benchmark": {"note": "no closed trade with a notional yet"}},
    }

    def test_each_coin_lands_in_exactly_one_group(self):
        t = P._benchmark_tally(self.BY_COIN)
        self.assertEqual(t["beat_holding"], ["BTC"])
        self.assertEqual(t["lost_to_holding"], ["ETH"])
        self.assertEqual(t["verdict_withheld"], ["SOL"])
        self.assertEqual(t["not_measured"], ["DOGE", "XRP"])

    def test_a_withheld_verdict_is_not_counted_as_a_loss(self):
        # "we could not judge" and "it lost" are different findings.
        t = P._benchmark_tally({"SOL": self.BY_COIN["SOL"]})
        self.assertEqual(t["lost_to_holding"], [])
        self.assertEqual(t["verdict_withheld"], ["SOL"])

    def test_an_errored_benchmark_is_not_counted_as_a_loss(self):
        t = P._benchmark_tally({"DOGE": self.BY_COIN["DOGE"]})
        self.assertEqual(t["lost_to_holding"], [])
        self.assertEqual(t["not_measured"], ["DOGE"])

    def test_no_combined_verdict_is_offered(self):
        t = P._benchmark_tally(self.BY_COIN)
        self.assertNotIn("beat", t.keys() - {"beat_holding"})
        self.assertNotIn("verdict", t)
        self.assertIn("deliberately not combined", t["note"])

    def test_a_missing_benchmark_key_does_not_raise(self):
        self.assertEqual(P._benchmark_tally({"BTC": {}})["not_measured"], ["BTC"])


if __name__ == "__main__":
    unittest.main()
