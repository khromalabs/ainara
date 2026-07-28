# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the carry-trade ledger (ainara/orakle/skills/trading/_ledger.py).

The ledger's whole purpose is answering "did the strategy earn what the model said
it would", and every realized RATE it reports is divided by the notional it stored.
So a wrong size is not a cosmetic defect — it silently rescales the only output
anyone reads.

That is what happened: record_open stored `decision["size"]`, the size the engine
PLANNED, while the daemon quantizes down to the coarser venue step before placing.
BTC went in as 0.000898 against 0.0008 filled — a 12% overstatement that suppressed
every realized funding rate by 12%.

Writes go to a temp DB (_db_path is patched); the real ledger is never touched.

Run:  venv/Scripts/python.exe -m unittest \
        scripts.evaluation.tests.test_trading_ledger
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from ainara.orakle.skills.trading import _ledger as L  # noqa: E402

# A decide verdict as the carry engine emits it, and the /hedge/open result the
# daemon returns for it. Note the mismatch: the engine planned 0.000898, both venues
# filled 0.0008 (dYdX BTC-USD steps 0.0001, so that is the binding step).
DECISION = {
    "coin": "BTC", "action": "open", "short_venue": "hyperliquid",
    "long_venue": "dydx", "size": 0.000898, "ref_price": 65151.5, "leverage": 3.0,
    "smoothed_spread_annual_pct": 13.664,
    "net_annual_pct_on_capital_if_spread_holds": 27.696,
    "net_after_costs_pct_notional_over_hold": 0.351,
    "expected_hold_days": 14.0,
    "sizing": {"effective_notional_per_leg": 58.53},
}
RESULT = {"opened": True, "status": "hedged",
          "positions": {"hyperliquid": -0.0008, "dydx": 0.0008}}


class FilledSize(unittest.TestCase):
    def test_takes_the_filled_size_from_both_legs(self):
        self.assertAlmostEqual(L._filled_size(RESULT), 0.0008)

    def test_takes_the_smaller_leg_when_they_differ(self):
        # The excess on one side is residual delta, not hedged carry.
        r = {"positions": {"hyperliquid": -0.0009, "dydx": 0.0008}}
        self.assertAlmostEqual(L._filled_size(r), 0.0008)

    def test_a_half_open_hedge_has_no_single_honest_size(self):
        self.assertIsNone(L._filled_size({"positions": {"hyperliquid": -0.0008,
                                                        "dydx": 0.0}}))
        self.assertIsNone(L._filled_size({"positions": {"hyperliquid": -0.0008}}))

    def test_missing_or_junk_results_are_none_not_a_crash(self):
        for bad in (None, {}, {"positions": None}, {"positions": {}},
                    {"positions": {"a": "x", "b": "y"}}):
            self.assertIsNone(L._filled_size(bad), bad)


class RecordOpenUsesFilledSize(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._original = L._db_path
        L._db_path = lambda: os.path.join(self.tmp, "carry_ledger.db")

    def tearDown(self):
        L._db_path = self._original

    def _row(self):
        rows = L.trades()
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_the_regression_filled_size_not_planned_size(self):
        rid = L.record_open(DECISION, RESULT)
        self.assertIsNotNone(rid)
        r = self._row()
        self.assertAlmostEqual(r["size"], 0.0008)          # filled
        self.assertNotAlmostEqual(r["size"], 0.000898)     # not planned

    def test_notional_is_derived_from_the_filled_size(self):
        L.record_open(DECISION, RESULT)
        # 0.0008 * 65151.5 = 52.12, NOT the planned 58.53 which carries the same
        # 12% overstatement.
        self.assertAlmostEqual(self._row()["notional_usd"], 52.12, places=2)

    def test_the_prediction_is_still_recorded_verbatim(self):
        # The point of the row: what the engine PREDICTED, to compare against.
        L.record_open(DECISION, RESULT)
        r = self._row()
        self.assertAlmostEqual(r["pred_smoothed_spread_annual_pct"], 13.664)
        self.assertAlmostEqual(r["pred_net_annual_pct_on_capital"], 27.696)
        self.assertAlmostEqual(r["ref_price"], 65151.5)
        self.assertEqual(r["status"], "open")

    def test_falls_back_to_the_planned_size_when_legs_are_unreported(self):
        # Old daemon payload, or a result that never confirmed both legs: a planned
        # size is better than no size at all.
        L.record_open(DECISION, {"opened": True})
        r = self._row()
        self.assertAlmostEqual(r["size"], 0.000898)
        self.assertAlmostEqual(r["notional_usd"], 58.53)   # planned fallback

    def test_close_records_the_exit_context(self):
        L.record_open(DECISION, RESULT)
        rid = L.record_close("BTC", {"reason": "spread decayed",
                                     "smoothed_spread_annual_pct": 3.2},
                             {"as_of": "2026-07-28T02:35:02+00:00"})
        self.assertIsNotNone(rid)
        r = self._row()
        self.assertEqual(r["status"], "closed")
        self.assertEqual(r["closed_at"], "2026-07-28T02:35:02+00:00")
        self.assertEqual(r["exit_reason"], "spread decayed")
        self.assertAlmostEqual(r["close_smoothed_spread_annual_pct"], 3.2)

    def test_a_close_with_no_open_row_is_a_logged_noop(self):
        self.assertIsNone(L.record_close("ETH", {"reason": "x"}, {}))

    def test_recording_never_raises_into_the_order_path(self):
        # A trade opening is safety-critical; recording it is observability.
        L._db_path = lambda: os.path.join(self.tmp, "no", "such", "dir", "x.db")
        self.assertIsNone(L.record_open(DECISION, RESULT))
        self.assertIsNone(L.record_close("BTC", {}, {}))


if __name__ == "__main__":
    unittest.main()
