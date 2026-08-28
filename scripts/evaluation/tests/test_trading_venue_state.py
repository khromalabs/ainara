# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Venue state reads must FAIL LOUD, never look empty (executor venv).

Regression for the 2026-07-27 incident. dydx.state() called
`r.json().get("subaccounts")` with no status check, and `if not subs` treated a
MISSING key exactly like an empty one — so a 429 rate-limit body returned a dict
with no "positions" and every caller read it as a flat account. The watchdog
flattened three healthy Hyperliquid legs and stranded the dYdX longs for 8 hours.

The distinction under test:
  - read failed / unparseable / no "subaccounts"  -> raise VenueStateUnavailable
  - read succeeded, genuinely no subaccount       -> positions: []  (readable+empty)

No network: requests.get and HL's _info are stubbed.

Run (executor venv, as a FILE — the venv lacks ainara's deps):
  executor/.venv/Scripts/python.exe scripts/evaluation/tests/test_trading_venue_state.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import requests  # noqa: E402

from scripts.evaluation.tests._executor_env import (  # noqa: E402
    require_executor_deps)

# Before the executor imports below: they need the venue signing SDKs, which
# live only in the executor's virtualenv. Skips with a reason there instead of
# failing to import.
require_executor_deps()

from executor.errors import VenueStateUnavailable  # noqa: E402
from executor.venues import dydx as D  # noqa: E402
from executor.venues.hyperliquid import HyperliquidExecutor  # noqa: E402


class _Cfg:
    def __init__(self, **settings):
        self._s = settings  # dotted key -> value, e.g. trading.dydx.subaccounts

    def venue(self, name):
        if name == "dydx":
            return "mainnet", {"account_address": "dydx1test",
                               "agent_private_key": "0x" + "1" * 64,
                               "authenticator_id": 1}
        return "mainnet", {"account_address": "0xtest",
                           "agent_private_key": "0x" + "2" * 64}

    def get(self, dotted, default=None):
        return self._s.get(dotted, default)

    def jurisdiction_acknowledged(self):
        return True


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class DydxStateFailsLoud(unittest.TestCase):
    def setUp(self):
        self.dy = D.DydxExecutor(_Cfg())
        self._original_get = D.requests.get

    def tearDown(self):
        D.requests.get = self._original_get

    def _serve(self, payload, status=200):
        D.requests.get = lambda *a, **kw: _Resp(payload, status)

    def test_429_raises_instead_of_reporting_flat(self):
        # THE incident. dYdX indexer rate limit: a JSON error body, HTTP 429.
        self._serve({"errors": [{"msg": "too many requests"}]}, status=429)
        with self.assertRaises(VenueStateUnavailable):
            self.dy.state()

    def test_500_raises(self):
        self._serve({"error": "internal"}, status=500)
        with self.assertRaises(VenueStateUnavailable):
            self.dy.state()

    def test_200_without_a_subaccounts_field_raises(self):
        # A degraded 200 is the nastiest case: raise_for_status alone misses it.
        self._serve({"unexpected": "shape"})
        with self.assertRaises(VenueStateUnavailable) as cm:
            self.dy.state()
        self.assertIn("subaccounts", str(cm.exception))

    def test_unparseable_body_raises(self):
        self._serve(ValueError("not json"))
        with self.assertRaises(VenueStateUnavailable):
            self.dy.state()

    def test_a_genuinely_empty_account_is_readable_and_empty(self):
        # Must NOT raise: this is a real answer, and it carries an explicit empty
        # positions list so callers can distinguish it from a failed read.
        self._serve({"subaccounts": []})
        st = self.dy.state()
        self.assertEqual(st["positions"], [])
        self.assertFalse(st["subaccount_exists"])

    def test_a_real_position_still_parses(self):
        self._serve({"subaccounts": [{
            "subaccountNumber": 0, "equity": "95.7", "freeCollateral": "40.0",
            "openPerpetualPositions": {
                "BTC-USD": {"size": "0.0008", "side": "LONG",
                            "entryPrice": "65130"}}}]})
        self.dy._market_risk = lambda t: (64000.0, 0.012)
        st = self.dy.state()
        self.assertEqual(len(st["positions"]), 1)
        self.assertAlmostEqual(st["positions"][0]["size"], 0.0008)


ISOLATED = {"trading.dydx.subaccounts": {"BTC": 0, "ETH": 1, "SOL": 2}}


def sub(num, equity, **positions):
    """One indexer subaccount entry. positions: market -> (size, side)."""
    return {"subaccountNumber": num, "equity": str(equity),
            "freeCollateral": str(equity),
            "openPerpetualPositions": {
                m: {"size": str(s), "side": side, "entryPrice": "100"}
                for m, (s, side) in positions.items()}}


class SubaccountIsolation(unittest.TestCase):
    """One coin per subaccount, so the liquidation formula is valid again.

    dYdX v4 is cross-margined per SUBACCOUNT. Three positions sharing subaccount 0
    share one liquidation: the maintenance requirement is their sum, one leg's losses
    eat the others' collateral, and liquidation_price() (single-position) stops being
    valid — which is why every multi-coin dYdX leg reported "liquidation unknown" and
    went UNMONITORED. At the 2026-07-28 sizing that hid an 11.5% buffer.

    Isolation buys visibility and blast-radius containment. It does NOT create
    margin: the same equity split three ways leaves each position the same buffer.
    """

    def setUp(self):
        self._original_get = D.requests.get

    def tearDown(self):
        D.requests.get = self._original_get

    def _dydx(self, *subs, **cfg):
        dy = D.DydxExecutor(_Cfg(**cfg))
        D.requests.get = lambda *a, **kw: _Resp({"subaccounts": list(subs)})
        dy._market_risk = lambda t: (100.0, 0.012)
        return dy

    # ---- mapping -------------------------------------------------------

    def test_maps_market_or_bare_coin_to_its_subaccount(self):
        dy = self._dydx(**ISOLATED)
        for symbol, want in (("ETH-USD", 1), ("ETH", 1), ("eth-usd", 1),
                             ("SOL-USD", 2), ("BTC-USD", 0)):
            self.assertEqual(dy.subaccount_for(symbol), want, symbol)

    def test_an_unmapped_coin_and_an_unset_map_both_mean_zero(self):
        self.assertEqual(self._dydx(**ISOLATED).subaccount_for("DOGE-USD"), 0)
        self.assertEqual(self._dydx().subaccount_for("ETH-USD"), 0)

    # ---- reads ---------------------------------------------------------

    def test_state_reads_EVERY_subaccount_not_just_the_first(self):
        # The failure this prevents: an ETH position funded in subaccount 1 read as
        # flat, which would make decide_exit strand it and the watchdog call the
        # hedge broken.
        dy = self._dydx(sub(0, 32, **{"BTC-USD": (0.001, "LONG")}),
                        sub(1, 32, **{"ETH-USD": (0.03, "LONG")}),
                        sub(2, 32, **{"SOL-USD": (0.7, "LONG")}), **ISOLATED)
        st = dy.state()
        self.assertEqual(sorted(st["open_positions"]),
                         ["BTC-USD", "ETH-USD", "SOL-USD"])
        self.assertEqual({p["coin"]: p["subaccount"] for p in st["positions"]},
                         {"BTC-USD": 0, "ETH-USD": 1, "SOL-USD": 2})

    def test_isolation_restores_a_real_liquidation_distance(self):
        # THE point of the change: one position per subaccount -> the formula is
        # exact -> the watchdog can finally see the buffer.
        #
        # Numbers mirror the live 2026-07-28 sizing: ~$239 notional (2.4 @ mark 100)
        # against ~$32 of subaccount equity, which is the ~12% buffer that was
        # invisible while all three coins shared subaccount 0.
        dy = self._dydx(sub(0, 32, **{"BTC-USD": (2.4, "LONG")}),
                        sub(1, 32, **{"ETH-USD": (2.4, "LONG")}), **ISOLATED)
        for p in dy.state()["positions"]:
            self.assertIsNotNone(p["liq_distance_pct"], p["coin"])
            self.assertIsNone(p["liq_note"], p["coin"])
            self.assertAlmostEqual(p["liq_distance_pct"], 12.3, places=1)

    def test_liquidation_is_judged_against_the_holding_subaccounts_equity(self):
        # Not the primary's, and not the book total: that subaccount is the only
        # collateral actually backing the position.
        dy = self._dydx(sub(0, 500, **{"BTC-USD": (2.4, "LONG")}),
                        sub(1, 20, **{"ETH-USD": (2.4, "LONG")}), **ISOLATED)
        pos = {p["coin"]: p for p in dy.state()["positions"]}
        self.assertEqual(pos["ETH-USD"]["subaccount_equity"], 20.0)
        self.assertEqual(pos["BTC-USD"]["subaccount_equity"], 500.0)
        # Identical positions, different backing equity, opposite conclusions. The
        # thin subaccount has a real, reachable liquidation; the fat one cannot be
        # liquidated by price at all. Judging the ETH leg against the primary's $500
        # would have reported it as unliquidatable when it is 4% away.
        self.assertIsNotNone(pos["ETH-USD"]["liq_distance_pct"])
        self.assertIsNone(pos["BTC-USD"]["liq_distance_pct"])
        self.assertIn("not liquidatable by price alone",
                      pos["BTC-USD"]["liq_note"])

    def test_a_shared_subaccount_still_degrades_to_unknown(self):
        # Without isolation nothing is claimed that cannot be computed.
        dy = self._dydx(sub(0, 95, **{"BTC-USD": (2.4, "LONG"),
                                      "ETH-USD": (2.4, "LONG"),
                                      "SOL-USD": (2.4, "LONG")}))
        st = dy.state()
        self.assertFalse(st["isolated"])
        for p in st["positions"]:
            self.assertIsNone(p["liq_distance_pct"])
            self.assertIn("liquidation unknown", p["liq_note"])
            self.assertIn("trading.dydx.subaccounts", p["liq_note"])

    def test_book_totals_and_the_legacy_shape_coexist(self):
        dy = self._dydx(sub(0, 30, **{"BTC-USD": (0.001, "LONG")}),
                        sub(1, 40), sub(2, 25), **ISOLATED)
        st = dy.state()
        self.assertEqual(st["equity"], 30.0)          # primary, as before
        self.assertEqual(st["equity_total"], 95.0)    # book-wide, additive
        self.assertEqual(sorted(st["subaccounts"]), [0, 1, 2])
        self.assertEqual(st["subaccounts"][1]["position_count"], 0)
        self.assertTrue(st["isolated"])

    def test_an_unreadable_read_still_raises_under_isolation(self):
        dy = D.DydxExecutor(_Cfg(**ISOLATED))
        D.requests.get = lambda *a, **kw: _Resp({"errors": ["rate limited"]}, 429)
        with self.assertRaises(VenueStateUnavailable):
            dy.state()

    # ---- writes --------------------------------------------------------

    def test_orders_are_placed_into_the_coins_own_subaccount(self):
        import asyncio
        dy = self._dydx(**ISOLATED)
        seen = {}

        class _Mkt:
            def order_id(self, addr, subaccount, client_id, flags):
                seen["subaccount"] = subaccount
                return "oid"

            def order(self, *a, **kw):
                return "proto"

        dy._market = lambda m: _Mkt()
        dy.oracle_price = lambda m: 100.0

        class _Node:
            async def latest_block_height(self): return 10
            async def place_order(self, *a, **kw): return type(
                "R", (), {"tx_response": type("T", (), {"code": 0})()})()

        async def node():
            return _Node()

        dy._node = node

        async def signer(n):
            return object(), object()

        dy._signer = signer
        asyncio.run(dy.place_market_reduce("SOL-USD", False, 0.1))
        self.assertEqual(seen["subaccount"], 2)  # SOL -> 2, not 0

    def test_open_orders_can_resolve_the_subaccount_from_a_market(self):
        dy = self._dydx(**ISOLATED)
        seen = {}

        def fake_get(url, **kw):
            seen["url"] = url
            return _Resp({"orders": []})

        D.requests.get = fake_get
        dy.open_orders(market="ETH-USD")
        self.assertIn("subaccountNumber=1", seen["url"])


class HyperliquidStateFailsLoud(unittest.TestCase):
    def setUp(self):
        self.hl = HyperliquidExecutor(_Cfg())

    def test_an_unusable_clearinghouse_response_raises(self):
        # The mirror of the dYdX bug: this would have fallen through to
        # assetPositions -> [] -> "HL is flat" -> every dYdX leg looks naked.
        self.hl._info = lambda body: {}
        with self.assertRaises(VenueStateUnavailable):
            self.hl.state()

    def test_a_non_dict_response_raises(self):
        self.hl._info = lambda body: ["nope"]
        with self.assertRaises(VenueStateUnavailable):
            self.hl.state()

    def test_a_valid_response_parses(self):
        def info(body):
            if body["type"] == "clearinghouseState":
                return {"marginSummary": {"accountValue": "97.6",
                                          "totalMarginUsed": "20.0"},
                        "assetPositions": [{"position": {
                            "coin": "BTC", "szi": "-0.0008",
                            "positionValue": "51.8", "entryPx": "65168",
                            "liquidationPx": "80000", "unrealizedPnl": "0.3"}}]}
            return {"balances": [{"coin": "USDC", "total": "5.0"}]}

        self.hl._info = info
        st = self.hl.state()
        self.assertAlmostEqual(st["positions"][0]["szi"], -0.0008)
        self.assertAlmostEqual(st["usdc_spot"], 5.0)

    def test_a_spot_failure_does_not_blind_the_perp_read(self):
        # Spot balance is informational; the perp positions ARE the risk data and
        # they already parsed. Degrade the field, don't discard the read.
        calls = {"n": 0}

        def info(body):
            calls["n"] += 1
            if body["type"] == "clearinghouseState":
                return {"marginSummary": {"accountValue": "97.6",
                                          "totalMarginUsed": "0"},
                        "assetPositions": []}
            raise requests.HTTPError("503 spot down")

        self.hl._info = info
        st = self.hl.state()
        self.assertEqual(st["positions"], [])
        self.assertIsNone(st["usdc_spot"])
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
