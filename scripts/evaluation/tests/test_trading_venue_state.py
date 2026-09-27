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

from executor.compliance import check_submission  # noqa: E402
from executor.errors import VenueStateUnavailable  # noqa: E402
from executor.venues import cross_to_tick, tick_decimals  # noqa: E402
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
        asyncio.run(dy.place_market_reduce("SOL-USD", False, 0.1, dry_run=False))
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


class CrossToTick(unittest.TestCase):
    """Protective closes must round onto the tick, and never to zero."""

    def test_sub_dollar_sell_on_a_whole_dollar_tick_is_not_zero(self):
        # floor(0.475 / 1.0) is 0: a sell at 0 would sweep the book.
        self.assertGreater(cross_to_tick(0.475, False, 1.0), 0)
        self.assertEqual(cross_to_tick(0.475, False, 1.0), 0.475)

    def test_buy_ceils_and_sell_floors(self):
        self.assertEqual(cross_to_tick(0.4751, True, 0.001), 0.476)
        self.assertEqual(cross_to_tick(0.4759, False, 0.001), 0.475)
        self.assertEqual(cross_to_tick(101.01, True, 0.1), 101.1)
        self.assertEqual(cross_to_tick(101.09, False, 0.1), 101.0)

    def test_a_price_already_on_the_grid_is_not_nudged(self):
        for is_buy in (True, False):
            self.assertEqual(cross_to_tick(0.475, is_buy, 0.001), 0.475)
            self.assertEqual(cross_to_tick(64000.0, is_buy, 1.0), 64000.0)
            self.assertEqual(cross_to_tick(0.3, is_buy, 0.1), 0.3)

    def test_an_unusable_tick_returns_the_input(self):
        for tick in (None, 0, 0.0, -1, "junk"):
            self.assertEqual(cross_to_tick(0.475, False, tick), 0.475, tick)

    def test_tick_decimals(self):
        self.assertEqual(tick_decimals(0.001), 3)
        self.assertEqual(tick_decimals(1), 0)
        self.assertEqual(tick_decimals(0.5), 1)


class CloseLimitsNeverZero(unittest.TestCase):
    """Both venues' close paths, priced for a market trading under $1.

    Before: HL sent round(limit) and dYdX round(oracle * (1 +/- slip)), both
    integers, so each of these closes went out at a limit of 0 or 1.
    """

    def test_hyperliquid_close_of_a_long_sells_above_zero_on_the_tick(self):
        hl = HyperliquidExecutor(_Cfg())
        hl.state = lambda: {"positions": [
            {"coin": "DOGE", "szi": 100.0, "mark_px": 0.5}]}
        hl._info = lambda body: {"universe": [{"name": "DOGE",
                                               "szDecimals": 0}]}
        sent = {}

        def place_order(coin, is_buy, size, limit_px, **kw):
            sent.update(is_buy=is_buy, px=limit_px, kw=kw)
            return {"submitted": False}

        hl.place_order = place_order
        hl.reduce("DOGE")
        self.assertFalse(sent["is_buy"])
        self.assertTrue(sent["kw"]["reduce_only"])
        # 0.5 * 0.95 = 0.475, floored to HL's 0.00001 grid at that price.
        self.assertAlmostEqual(sent["px"], 0.475, places=9)

    def test_hyperliquid_close_of_a_short_buys_above_the_mark(self):
        hl = HyperliquidExecutor(_Cfg())
        hl.state = lambda: {"positions": [
            {"coin": "DOGE", "szi": -100.0, "mark_px": 0.5}]}
        hl._info = lambda body: {"universe": [{"name": "DOGE",
                                               "szDecimals": 0}]}
        sent = {}
        hl.place_order = lambda coin, is_buy, size, limit_px, **kw: sent.update(
            is_buy=is_buy, px=limit_px) or {}
        hl.reduce("DOGE")
        self.assertTrue(sent["is_buy"])
        self.assertAlmostEqual(sent["px"], 0.525, places=9)

    def test_hyperliquid_close_still_prices_when_meta_is_unreadable(self):
        hl = HyperliquidExecutor(_Cfg())
        hl.state = lambda: {"positions": [
            {"coin": "DOGE", "szi": 100.0, "mark_px": 0.5}]}

        def info(body):
            raise requests.ConnectionError("meta down")

        hl._info = info
        sent = {}
        hl.place_order = lambda coin, is_buy, size, limit_px, **kw: sent.update(
            px=limit_px) or {}
        hl.reduce("DOGE")
        self.assertGreater(sent["px"], 0.4)

    def _dydx_close(self, oracle, tick, is_buy):
        import asyncio
        dy = D.DydxExecutor(_Cfg())
        seen = {}

        class _Mkt:
            def order_id(self, *a):
                return "oid"

            def order(self, oid, otype, side, size, price, *a, **kw):
                seen["price"] = price
                return "proto"

        class _Node:
            async def latest_block_height(self):
                return 10

            async def place_order(self, *a, **kw):
                return type("R", (), {"tx_response":
                                      type("T", (), {"code": 0})()})()

        async def node():
            return _Node()

        async def signer(n):
            return object(), object()

        dy._node, dy._signer = node, signer
        dy._market = lambda m: _Mkt()
        dy.oracle_price = lambda m: oracle
        dy.price_tick = lambda m, ref_price=None: tick
        res = asyncio.run(dy.place_market_reduce(
            "DOGE-USD", is_buy, 100, dry_run=False))
        return seen.get("price"), res

    def test_dydx_close_of_a_long_sells_above_zero_on_the_tick(self):
        px, _ = self._dydx_close(0.5, 0.00001, is_buy=False)
        self.assertAlmostEqual(px, 0.45, places=9)  # 0.5 * 0.9

    def test_dydx_close_of_a_short_buys_on_the_tick(self):
        px, _ = self._dydx_close(0.5, 0.00001, is_buy=True)
        self.assertAlmostEqual(px, 0.55, places=9)  # 0.5 * 1.1

    def test_dydx_close_refuses_without_an_oracle_price(self):
        px, res = self._dydx_close(0.0, 0.00001, is_buy=True)
        self.assertIsNone(px)
        self.assertFalse(res["submitted"])


class _NoAckCfg(_Cfg):
    def jurisdiction_acknowledged(self):
        return False


def _stub_dydx_order_path(dy, seen):
    """Stub the node/market/signer so an order reaches a recorder, not a venue."""
    class _Mkt:
        def order_id(self, *a):
            return "oid"

        def order(self, *a, **kw):
            seen["sent"] = True
            return "proto"

    class _Node:
        async def latest_block_height(self):
            return 10

        async def place_order(self, *a, **kw):
            return type("R", (), {"tx_response":
                                  type("T", (), {"code": 0})()})()

    async def node():
        return _Node()

    async def signer(n):
        return object(), object()

    dy._node, dy._signer = node, signer
    dy._market = lambda m: _Mkt()
    dy.oracle_price = lambda m: 100.0
    dy.price_tick = lambda m, ref_price=None: 1.0
    dy.mode = "permissioned"


class ReduceOnlyJurisdictionGate(unittest.TestCase):
    """A close must reach both venues or neither.

    Before: HL's close went through check_submission and was refused on
    mainnet without the acknowledgement, while dYdX's close never called the
    gate. A watchdog flatten then closed dYdX and left HL naked.
    """

    def test_gate_exempts_reduce_only_from_the_jurisdiction_check(self):
        cfg = _NoAckCfg()
        self.assertEqual(check_submission(cfg, "mainnet", False)["refused"],
                         "jurisdiction_not_acknowledged")
        self.assertIsNone(check_submission(cfg, "mainnet", False,
                                           reduce_only=True))

    def test_gate_still_refuses_reduce_only_in_dry_run(self):
        for net in ("mainnet", "testnet"):
            gate = check_submission(_Cfg(), net, True, reduce_only=True)
            self.assertEqual(gate["refused"], "dry_run", net)

    def test_hyperliquid_opening_refused_close_allowed(self):
        hl = HyperliquidExecutor(_NoAckCfg())
        sent = []
        hl._exchange = lambda: type("X", (), {
            "order": lambda self, *a, **kw: sent.append(kw) or {"ok": 1}})()
        opening = hl.place_order("BTC", True, 0.001, 50000.0, dry_run=False)
        self.assertEqual(opening["gate"]["refused"],
                         "jurisdiction_not_acknowledged")
        self.assertEqual(sent, [])
        closing = hl.place_order("BTC", True, 0.001, 50000.0,
                                 reduce_only=True, tif="Ioc", dry_run=False)
        self.assertTrue(closing["submitted"])
        self.assertEqual(sent, [{"reduce_only": True}])

    def test_dydx_opening_refused_close_allowed(self):
        import asyncio
        dy = D.DydxExecutor(_NoAckCfg())
        seen = {}
        _stub_dydx_order_path(dy, seen)
        opening = asyncio.run(dy.place_order("BTC-USD", True, 0.001, 50000.0,
                                             dry_run=False))
        self.assertEqual(opening["gate"]["refused"],
                         "jurisdiction_not_acknowledged")
        self.assertNotIn("sent", seen)
        closing = asyncio.run(dy.place_market_reduce("BTC-USD", True, 0.001,
                                                     dry_run=False))
        self.assertTrue(closing["submitted"])
        self.assertTrue(seen["sent"])

    def test_dydx_close_honours_dry_run(self):
        # This path used to submit whatever dry_run said: it had no gate.
        import asyncio
        dy = D.DydxExecutor(_Cfg())
        seen = {}
        _stub_dydx_order_path(dy, seen)
        res = asyncio.run(dy.place_market_reduce("BTC-USD", True, 0.001,
                                                 dry_run=True))
        self.assertFalse(res["submitted"])
        self.assertEqual(res["gate"]["refused"], "dry_run")
        self.assertNotIn("sent", seen)

    def test_dydx_close_requires_an_explicit_dry_run(self):
        import asyncio
        dy = D.DydxExecutor(_Cfg())
        with self.assertRaises(TypeError):
            asyncio.run(dy.place_market_reduce("BTC-USD", True, 0.001))

    def test_hyperliquid_close_honours_dry_run(self):
        hl = HyperliquidExecutor(_Cfg())
        sent = []
        hl._exchange = lambda: type("X", (), {
            "order": lambda self, *a, **kw: sent.append(kw)})()
        res = hl.place_order("BTC", True, 0.001, 50000.0, reduce_only=True,
                             tif="Ioc", dry_run=True)
        self.assertEqual(res["gate"]["refused"], "dry_run")
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
