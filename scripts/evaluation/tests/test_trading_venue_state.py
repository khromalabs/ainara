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

from executor.errors import VenueStateUnavailable  # noqa: E402
from executor.venues import dydx as D  # noqa: E402
from executor.venues.hyperliquid import HyperliquidExecutor  # noqa: E402


class _Cfg:
    def venue(self, name):
        if name == "dydx":
            return "mainnet", {"account_address": "dydx1test",
                               "agent_private_key": "0x" + "1" * 64,
                               "authenticator_id": 1}
        return "mainnet", {"account_address": "0xtest",
                           "agent_private_key": "0x" + "2" * 64}

    def get(self, dotted, default=None):
        return default

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
