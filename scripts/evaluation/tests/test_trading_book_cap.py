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


class _OrderVenue(_FakeVenue):
    """A venue that records orders instead of placing them."""

    def __init__(self, positions=None):
        super().__init__(positions)
        self.orders = []

    def place_order(self, symbol, is_buy, size, price, **kw):
        self.orders.append((symbol, size, kw))
        return {"submitted": False, "gate": {"refused": "dry_run"}}


class OrderRouteAppliesTheBookCap(unittest.TestCase):
    """/venues/<v>/order must not walk the book past its ceilings.

    Before: the route checked only the per-order caps, so the book-wide
    position-count and notional limits could be exceeded one order at a time.
    """

    HELD = [{"coin": "BTC", "szi": -0.001, "mark_px": 65000.0},
            {"coin": "ETH", "szi": 0.03, "mark_px": 3000.0}]

    def _order(self, venue, body, max_positions=2, max_notional=None):
        fake = _OrderVenue(self.HELD)

        def get(key, default=None):
            if key == "trading.max_concurrent_positions":
                return max_positions
            if key == "trading.max_book_notional_usd":
                return max_notional
            return default

        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", return_value=fake), \
             patch.object(S, "_margin_cap_notional",
                          return_value=(None, None)):
            cfg.get.side_effect = get
            r = S.app.test_client().post(f"/venues/{venue}/order", json={
                "is_buy": True, "dry_run": True, **body})
        return r.get_json(), fake

    def test_a_new_coin_past_the_count_cap_is_refused(self):
        res, fake = self._order("hyperliquid", {"symbol": "SOL", "size": 0.1,
                                                "price": 150.0})
        self.assertEqual(res["gate"]["refused"], "book_cap")
        self.assertEqual(fake.orders, [])

    def test_topping_up_a_held_coin_is_not_a_new_position(self):
        for venue, symbol in (("hyperliquid", "ETH"), ("dydx", "ETH-USD")):
            res, fake = self._order(venue, {"symbol": symbol, "size": 0.01,
                                            "price": 3000.0})
            self.assertNotEqual((res.get("gate") or {}).get("refused"),
                                "book_cap", venue)
            self.assertEqual(len(fake.orders), 1, venue)

    def test_the_notional_cap_is_applied_per_order(self):
        # $65 + $90 already open; $60 more crosses a $200 ceiling.
        res, fake = self._order("hyperliquid",
                                {"symbol": "ETH", "size": 0.02, "price": 3000.0},
                                max_positions=None, max_notional=200.0)
        self.assertEqual(res["gate"]["refused"], "book_cap")
        self.assertIn("max_book_notional_usd", res["gate"]["detail"])

    def test_reduce_only_orders_are_never_book_capped(self):
        res, fake = self._order("hyperliquid", {"symbol": "SOL", "size": 0.1,
                                                "price": 150.0,
                                                "reduce_only": True})
        self.assertEqual(len(fake.orders), 1)


if __name__ == "__main__":
    unittest.main()
