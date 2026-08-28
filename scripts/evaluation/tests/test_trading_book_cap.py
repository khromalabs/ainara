# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the book-wide exposure gate (executor/server.py).

Runs under the EXECUTOR venv (Flask + venue SDKs installed):
    executor/.venv/Scripts/python.exe -m unittest \
        scripts.evaluation.tests.test_trading_book_cap

Covers _book_totals (pure aggregation over HL's position list — HL is always
one of the two legs of every hedge, so its positions ARE the book-wide view)
and _book_cap_check (the live-state gate /hedge/open calls right after the
"only open from flat" preflight, independent of the per-order caps).
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.evaluation.tests._executor_env import (  # noqa: E402
    require_executor_deps)

# Before the executor imports below: they need the venue signing SDKs, which
# live only in the executor's virtualenv. Skips with a reason there instead of
# failing to import.
require_executor_deps()

from executor import server as S  # noqa: E402
from executor.server import _book_totals  # noqa: E402


class BookTotals(unittest.TestCase):
    def test_empty_book(self):
        self.assertEqual(_book_totals([]), (0, 0.0))
        self.assertEqual(_book_totals(None), (0, 0.0))

    def test_counts_and_sums_open_positions(self):
        positions = [
            {"coin": "BTC", "szi": -0.001, "mark_px": 65000.0},
            {"coin": "ETH", "szi": 0.05, "mark_px": 3000.0},
        ]
        count, notional = _book_totals(positions)
        self.assertEqual(count, 2)
        self.assertAlmostEqual(notional, 0.001 * 65000.0 + 0.05 * 3000.0)

    def test_flat_positions_excluded(self):
        positions = [{"coin": "BTC", "szi": 0.0, "mark_px": 65000.0}]
        self.assertEqual(_book_totals(positions), (0, 0.0))

    def test_missing_mark_price_still_counted_not_priced(self):
        # An unpriceable leg must not be able to hide from the COUNT gate —
        # only the notional sum is best-effort.
        positions = [{"coin": "BTC", "szi": -0.001, "mark_px": None}]
        count, notional = _book_totals(positions)
        self.assertEqual(count, 1)
        self.assertEqual(notional, 0.0)


class _FakeVenue:
    def __init__(self, positions=None, raises=None):
        self._positions = positions or []
        self._raises = raises

    def state(self):
        if self._raises:
            raise self._raises
        return {"positions": self._positions}


class BookCapCheck(unittest.TestCase):
    def _cfg(self, max_positions=5, max_notional=None):
        def get(key, default=None):
            if key == "trading.max_concurrent_positions":
                return max_positions
            if key == "trading.max_book_notional_usd":
                return max_notional
            return default
        return get

    def test_no_caps_configured_always_allows(self):
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", return_value=_FakeVenue([])):
            cfg.get.side_effect = self._cfg(max_positions=None, max_notional=None)
            self.assertIsNone(S._book_cap_check(0.001, 65000.0))

    def test_allows_within_position_count_cap(self):
        positions = [{"coin": "BTC", "szi": -0.001, "mark_px": 65000.0}]
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", return_value=_FakeVenue(positions)):
            cfg.get.side_effect = self._cfg(max_positions=3)
            self.assertIsNone(S._book_cap_check(0.03, 3000.0))

    def test_refuses_over_position_count_cap(self):
        # 2 already open, cap is 2 -> a 3rd is refused.
        positions = [
            {"coin": "BTC", "szi": -0.001, "mark_px": 65000.0},
            {"coin": "ETH", "szi": 0.03, "mark_px": 3000.0},
        ]
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", return_value=_FakeVenue(positions)):
            cfg.get.side_effect = self._cfg(max_positions=2)
            result = S._book_cap_check(0.7, 150.0)
            self.assertIsNotNone(result)
            self.assertIn("max_concurrent_positions", result["detail"])

    def test_refuses_over_notional_cap(self):
        # $65 already open + $100 new = $165, over a $100 cap.
        positions = [{"coin": "BTC", "szi": -0.001, "mark_px": 65000.0}]
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", return_value=_FakeVenue(positions)):
            cfg.get.side_effect = self._cfg(max_positions=None, max_notional=100.0)
            result = S._book_cap_check(1.0, 100.0)
            self.assertIsNotNone(result)
            self.assertIn("max_book_notional_usd", result["detail"])

    def test_allows_within_notional_cap(self):
        # $65 already open + $50 new = $115, under a $200 cap.
        positions = [{"coin": "BTC", "szi": -0.001, "mark_px": 65000.0}]
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", return_value=_FakeVenue(positions)):
            cfg.get.side_effect = self._cfg(max_positions=None, max_notional=200.0)
            self.assertIsNone(S._book_cap_check(0.5, 100.0))

    def test_unreadable_venue_refuses_rather_than_assuming_empty(self):
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue",
                          return_value=_FakeVenue(raises=RuntimeError("boom"))):
            cfg.get.side_effect = self._cfg(max_positions=1)
            result = S._book_cap_check(0.001, 65000.0)
            self.assertIsNotNone(result)
            self.assertIn("book-wide exposure cap", result["detail"])


if __name__ == "__main__":
    unittest.main()
