# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Guards in the executor daemon's order path (executor/server.py).

Runs under the EXECUTOR venv (Flask + venue SDKs installed):
    executor/.venv/Scripts/python.exe -m unittest \
        scripts.evaluation.tests.test_trading_server_guards

No test places an order or reaches a venue: every venue the daemon would build
is replaced with a fake, and config reads are stubbed.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.evaluation.tests._executor_env import (  # noqa: E402
    require_executor_deps)

require_executor_deps()

from executor import compliance as C  # noqa: E402
from executor import server as S  # noqa: E402


# Runtime files (opening leases, the alarm) resolve under data.directory.
# Default it to a scratch directory so no test touches the real data dir.
_DATA_DIR = tempfile.mkdtemp(prefix="ainara-server-tests-")


def _cfg_get(settings):
    """A config.get that returns `settings[key]`, else the caller's default."""
    settings = {"data.directory": _DATA_DIR, **settings}

    def get(key, default=None):
        return settings.get(key, default)
    return get


class _Cfg:
    def __init__(self, **settings):
        self.get = _cfg_get(settings)


class _FakeHL:
    def __init__(self, equity=1000.0):
        self._equity = equity

    def state(self):
        return {"perp_account_value": self._equity, "positions": []}


class _FakeDydx:
    def __init__(self, equity=1000.0, raises=None, funded=(0, 1, 2)):
        self._equity = equity
        self._raises = raises
        self._funded = funded
        self.read_subaccounts = []

    def subaccount_for(self, symbol):
        return {"BTC": 0, "ETH": 1, "SOL": 2}.get(
            str(symbol).upper().split("-")[0], 0)

    def state(self, subaccount=0):
        # Like the real adapter: an unlisted subaccount falls back to the
        # first one rather than raising.
        self.read_subaccounts.append(subaccount)
        if self._raises:
            raise self._raises
        st = {"positions": [],
              "subaccount": subaccount if subaccount in self._funded
              else self._funded[0]}
        if self._equity is not None:
            st["equity"] = self._equity
        return st


def _venues(hl=None, dydx=None):
    hl = hl or _FakeHL()
    dydx = dydx or _FakeDydx()
    return lambda name: {"hyperliquid": hl, "dydx": dydx}.get(name)


class SizingDefaultsMatchTheTemplate(unittest.TestCase):
    """An absent cap key falls back to the template's value, not to no cap."""

    def test_order_cap_defaults_to_the_template_value(self):
        gate = C.check_order_cap(_Cfg(), 150.0, reduce_only=False)
        self.assertEqual(gate["refused"], "order_exceeds_max_notional")
        self.assertIsNone(C.check_order_cap(_Cfg(), 99.0, reduce_only=False))

    def test_explicit_null_order_cap_means_no_cap(self):
        cfg = _Cfg(**{"trading.executor.max_order_notional_usd": None})
        self.assertIsNone(C.check_order_cap(cfg, 1e6, reduce_only=False))

    def test_closes_are_never_capped(self):
        self.assertIsNone(C.check_order_cap(_Cfg(), 1e6, reduce_only=True))

    def test_hedge_opener_cap_uses_both_defaults(self):
        # Equity 1000 on both venues, default leverage 3: margin rule
        # 20% x 1000 x 3 = 600, hard cap 100; the tighter wins.
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", side_effect=_venues()):
            cfg.get.side_effect = _cfg_get({})
            self.assertEqual(S._effective_cap_notional("BTC-USD"), (100.0, None))

    def test_margin_rule_applies_when_unset(self):
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", side_effect=_venues(
                 _FakeHL(100.0), _FakeDydx(100.0))):
            cfg.get.side_effect = _cfg_get(
                {"trading.executor.max_order_notional_usd": None})
            # 20% x 100 x 3 = 60, no hard cap.
            cap, refusal = S._effective_cap_notional("BTC-USD")
            self.assertIsNone(refusal)
            self.assertAlmostEqual(cap, 60.0)


class MarginBackstopFailsClosed(unittest.TestCase):
    """The margin rule reads the coin's own subaccount, and refuses when blind.

    Before: it read subaccount 0 for every coin, and any read failure or
    missing equity returned None, which both callers took as "no cap".
    """

    def _cap(self, coin="ETH-USD", hl=None, dydx=None, settings=None):
        with patch.object(S, "config") as cfg,              patch.object(S, "_venue", side_effect=_venues(hl, dydx)):
            cfg.get.side_effect = _cfg_get(settings or {})
            return S._margin_cap_notional(coin)

    def test_reads_the_subaccount_the_coin_trades_in(self):
        dydx = _FakeDydx()
        cap, refusal = self._cap("ETH-USD", dydx=dydx)
        self.assertIsNone(refusal)
        self.assertEqual(dydx.read_subaccounts, [1])
        dydx = _FakeDydx()
        self._cap("SOL", dydx=dydx)
        self.assertEqual(dydx.read_subaccounts, [2])

    def test_a_venue_read_error_refuses(self):
        cap, refusal = self._cap(dydx=_FakeDydx(raises=RuntimeError("429")))
        self.assertIsNone(cap)
        self.assertEqual(refusal["refused"], "margin_cap_unreadable")

    def test_missing_equity_refuses(self):
        cap, refusal = self._cap(dydx=_FakeDydx(equity=None))
        self.assertEqual(refusal["refused"], "margin_cap_unreadable")
        cap, refusal = self._cap(hl=_FakeHL(equity=None))
        self.assertEqual(refusal["refused"], "margin_cap_unreadable")

    def test_an_unfunded_subaccount_is_not_read_as_another(self):
        # ETH maps to subaccount 1, which does not exist: state() answers
        # with subaccount 0's equity, which the ETH order cannot use.
        cap, refusal = self._cap("ETH-USD", dydx=_FakeDydx(funded=(0,)))
        self.assertEqual(refusal["refused"], "margin_cap_unreadable")

    def test_explicit_null_switches_the_rule_off(self):
        cap, refusal = self._cap(
            dydx=_FakeDydx(raises=RuntimeError("down")),
            settings={"trading.max_account_margin_pct": None})
        self.assertEqual((cap, refusal), (None, None))

    def test_order_route_refuses_an_opening_order_when_blind(self):
        client = S.app.test_client()
        with patch.object(S, "config") as cfg,              patch.object(S, "_venue", side_effect=_venues(
                 dydx=_FakeDydx(raises=RuntimeError("down")))):
            cfg.get.side_effect = _cfg_get({})
            r = client.post("/venues/hyperliquid/order", json={
                "symbol": "ETH", "is_buy": True, "size": 0.01,
                "price": 3000.0, "dry_run": True})
        body = r.get_json()
        self.assertFalse(body["submitted"])
        self.assertEqual(body["gate"]["refused"], "margin_cap_unreadable")

    def test_hedge_open_refuses_when_blind(self):
        client = S.app.test_client()
        with patch.object(S, "config") as cfg,              patch.object(S, "_venue", side_effect=_venues(
                 dydx=_FakeDydx(raises=RuntimeError("down")))):
            cfg.get.side_effect = _cfg_get({})
            r = client.post("/hedge/open", json={
                "short_venue": "hyperliquid", "long_venue": "dydx",
                "short_symbol": "ETH", "long_symbol": "ETH-USD",
                "size": 0.01, "ref_price": 3000.0, "dry_run": True})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["refused"], "margin_cap_unreadable")


class _Book:
    """Two venues' positions, moved by the order functions hedge_open calls.

    `short_fill` / `long_fill` are the fraction of each requested size that
    fills; `trim_lands` controls whether a reduce actually shrinks the leg.
    """

    def __init__(self, short_fill=1.0, long_fill=1.0, trim_lands=True):
        self.pos = {"hyperliquid": 0.0, "dydx": 0.0}
        self.short_fill, self.long_fill = short_fill, long_fill
        self.trim_lands = trim_lands
        self.placed, self.reduced, self.cancelled, self.closed = [], [], [], []

    def signed_position(self, venue, symbol):
        return self.pos[venue]

    def place_leg(self, venue, leg):
        self.placed.append((venue, leg["size"]))
        frac = self.long_fill if leg["is_buy"] else self.short_fill
        filled = round(leg["size"] * frac, 10)
        self.pos[venue] += filled if leg["is_buy"] else -filled
        return {"submitted": True}

    def reduce_leg(self, venue, symbol, qty):
        self.reduced.append((venue, qty))
        if self.trim_lands:
            sign = 1 if self.pos[venue] > 0 else -1
            self.pos[venue] -= sign * qty
        return {"submitted": True}

    def cancel_resting(self, venue, symbol, res):
        self.cancelled.append(venue)
        return None

    def close_leg(self, venue, symbol):
        self.closed.append(venue)
        self.pos[venue] = 0.0
        return {"submitted": True}


class PartialFillsAreNotReportedHedged(unittest.TestCase):
    """A partial fill must shape the other leg, or be reported as imbalanced.

    Before: the long always went out at the planned size and the route
    answered status "hedged" whatever the two legs actually held.
    """

    BODY = {"short_venue": "hyperliquid", "long_venue": "dydx",
            "short_symbol": "BTC", "long_symbol": "BTC-USD", "size": 1.0,
            "ref_price": 50.0, "dry_run": False, "fill_timeout_s": 0.01}

    def _open(self, book):
        client = S.app.test_client()
        with patch.object(S, "config") as cfg,              patch.object(S, "_effective_cap_notional",
                          return_value=(None, None)),              patch.object(S, "_hedge_size_step", return_value=0.001),              patch.object(S, "_hedge_price_tick", return_value=0.01),              patch.object(S, "_book_cap_check", return_value=None),              patch.object(S, "_signed_position", book.signed_position),              patch.object(S, "_place_leg", book.place_leg),              patch.object(S, "_reduce_leg", book.reduce_leg),              patch.object(S, "_cancel_resting", book.cancel_resting),              patch.object(S, "_close_leg", book.close_leg),              patch.object(S.time, "sleep", lambda s: None):
            cfg.get.side_effect = _cfg_get({})
            return client.post("/hedge/open", json=self.BODY).get_json()

    def test_full_fills_are_hedged(self):
        book = _Book()
        res = self._open(book)
        self.assertEqual(res["status"], "hedged")
        self.assertNotIn("resized", res)
        self.assertEqual(book.placed, [("hyperliquid", 1.0), ("dydx", 1.0)])

    def test_partial_short_sizes_the_long_to_the_fill(self):
        book = _Book(short_fill=0.6)
        res = self._open(book)
        self.assertEqual(res["status"], "hedged")
        self.assertEqual(book.placed[1], ("dydx", 0.6))
        self.assertEqual(res["resized"]["long_size"], 0.6)
        # Any resting remainder of the short is cancelled before sizing.
        self.assertIn("hyperliquid", book.cancelled)
        self.assertAlmostEqual(book.pos["hyperliquid"] + book.pos["dydx"], 0.0)

    def test_partial_long_trims_the_short(self):
        book = _Book(long_fill=0.5)
        res = self._open(book)
        self.assertEqual(res["status"], "hedged")
        self.assertEqual(book.reduced, [("hyperliquid", 0.5)])
        self.assertAlmostEqual(res["trim"]["qty"], 0.5)

    def test_a_trim_that_does_not_land_is_reported_imbalanced(self):
        book = _Book(long_fill=0.5, trim_lands=False)
        res = self._open(book)
        self.assertTrue(res["opened"])
        self.assertEqual(res["status"], "hedged_imbalanced")
        self.assertEqual(res["positions"], {"hyperliquid": -1.0, "dydx": 0.5})
        self.assertIn("unequal", res["detail"])

    def test_a_fill_within_tolerance_is_hedged_without_resizing(self):
        # 99% is inside the default 2% tolerance: no resize, no trim.
        book = _Book(long_fill=0.99)
        res = self._open(book)
        self.assertEqual(res["status"], "hedged")
        self.assertEqual(book.reduced, [])

    def test_a_short_fill_under_one_step_is_unwound(self):
        book = _Book(short_fill=0.0005)
        res = self._open(book)
        self.assertFalse(res["opened"])
        self.assertEqual(res["status"], "unwound")
        self.assertEqual(book.placed, [("hyperliquid", 1.0)])
        self.assertIn("hyperliquid", book.closed)


class OneOpenPerCoin(unittest.TestCase):
    """Two opens for one coin must not both pass the flat check.

    Before: nothing serialized /hedge/open, and the daemon serves requests
    on threads.
    """

    def _post(self, body):
        with patch.object(S, "config") as cfg:
            cfg.get.side_effect = _cfg_get({})
            return S.app.test_client().post("/hedge/open", json=body)

    def test_a_second_open_for_the_same_coin_is_refused(self):
        lock = S._open_lock("BTC")
        lock.acquire()
        try:
            r = self._post({"short_symbol": "btc", "long_symbol": "BTC-USD"})
        finally:
            lock.release()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["refused"], "already_opening")

    def test_another_coin_is_not_blocked(self):
        lock = S._open_lock("BTC")
        lock.acquire()
        try:
            # Reaches the handler (and fails its own validation), rather than
            # being refused by the BTC lock.
            r = self._post({"short_symbol": "ETH"})
        finally:
            lock.release()
        self.assertEqual(r.status_code, 400)

    def test_the_lock_is_released_after_every_outcome(self):
        self._post({"short_symbol": "SOL"})  # 400: missing fields
        self.assertFalse(S._open_lock("SOL").locked())
        with patch.object(S, "_hedge_open", side_effect=RuntimeError("boom")):
            try:
                self._post({"short_symbol": "SOL"})
            except RuntimeError:
                pass
        self.assertFalse(S._open_lock("SOL").locked())

    def test_symbols_for_one_coin_share_a_lock(self):
        self.assertIs(S._open_lock(S._coin_key("eth")),
                      S._open_lock(S._coin_key("ETH-USD")))


class BrowserWritesAreRefused(unittest.TestCase):
    """A web page on the trading host must not be able to place orders.

    Before: no check at all, and every write route parsed its body with
    get_json(force=True), so a CORS-simple text/plain POST reached it.
    """

    def setUp(self):
        self.reached = []
        self._patch = patch.object(
            S, "_hedge_open",
            side_effect=lambda body: self.reached.append(body) or ("ok", 200))
        self._patch.start()
        self.client = S.app.test_client()

    def tearDown(self):
        self._patch.stop()

    def test_a_request_carrying_origin_is_refused(self):
        r = self.client.post("/hedge/open", json={"short_symbol": "BTC"},
                             headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.reached, [])

    def test_a_cors_simple_text_plain_post_is_refused(self):
        r = self.client.post("/hedge/open", data='{"short_symbol": "BTC"}',
                             content_type="text/plain")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(self.reached, [])

    def test_a_form_post_is_refused(self):
        for ctype in ("application/x-www-form-urlencoded",
                      "multipart/form-data"):
            r = self.client.post("/hedge/open", data="a=1", content_type=ctype)
            self.assertEqual(r.status_code, 415, ctype)
        r = self.client.post("/hedge/open", data="{}")  # no Content-Type
        self.assertEqual(r.status_code, 415)
        self.assertEqual(self.reached, [])

    def test_the_order_routes_are_covered_too(self):
        for path in ("/venues/hyperliquid/order", "/venues/dydx/cancel",
                     "/hedge/close"):
            r = self.client.post(path, data="{}", content_type="text/plain")
            self.assertEqual(r.status_code, 415, path)

    def test_a_local_json_client_is_served(self):
        r = self.client.post(
            "/hedge/open", data='{"short_symbol": "BTC"}',
            content_type="application/json; charset=utf-8")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.reached, [{"short_symbol": "BTC"}])

    def test_reads_are_not_affected_by_this_guard(self):
        with patch.object(S, "_watchdog_alarm", return_value=None):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)


class OnlyLoopbackHostsAreServed(unittest.TestCase):
    """A page that rebinds its domain to 127.0.0.1 must not read the book.

    Before: no Host check, so every read route answered to any name.
    """

    def _get(self, host):
        with patch.object(S, "_watchdog_alarm", return_value=None):
            return S.app.test_client().get(
                "/health", environ_overrides={"HTTP_HOST": host})

    def test_foreign_and_lookalike_hosts_are_refused(self):
        for host in ("evil.example", "localhost.evil.example",
                     "127.0.0.1.evil.example", "evil.example:8130",
                     "[::1]:8130", "[127.0.0.1]:8130", ""):
            self.assertEqual(self._get(host).status_code, 403, host)

    def test_a_missing_host_is_refused(self):
        self.assertFalse(S.host_is_expected(None))
        self.assertFalse(S.host_is_expected(""))

    def test_loopback_names_are_served(self):
        for host in ("127.0.0.1:8140", "localhost:8140", "127.0.0.1",
                     "LOCALHOST:8130"):
            self.assertTrue(S.host_is_expected(host), host)
            self.assertEqual(self._get(host).status_code, 200, host)

    def test_writes_are_checked_for_host_first(self):
        # Both guards would refuse this; the Host guard answers.
        r = S.app.test_client().post(
            "/hedge/open", data="{}", content_type="text/plain",
            environ_overrides={"HTTP_HOST": "evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("Host", r.get_json()["error"])


class HealthReadsTheWatchdogsAlarmFile(unittest.TestCase):
    """The daemon reads the alarm where the watchdog writes it."""

    def test_alarm_is_read_from_the_shared_path(self):
        import json
        import time
        from executor import runtime as R
        base = __import__("tempfile").mkdtemp()
        settings = {"data.directory": base}
        path = R.alarm_path(_Cfg(**settings))
        R.write_text_atomic(path, json.dumps({"alarm": "broken_hedge",
                                              "ts": time.time()}))
        with patch.object(S, "config") as cfg:
            cfg.get.side_effect = _cfg_get(settings)
            self.assertEqual(S._watchdog_alarm()["alarm"], "broken_hedge")


class LiveOpensHoldALease(unittest.TestCase):
    """/hedge/open tells the watchdog which coin it is building."""

    def _post(self, body, settings, seen):
        from executor import runtime as R

        class Cfg:
            def get(self, key, default=None):
                return settings.get(key, default)

        def fake_open(b):
            seen.append(R.active_leases(Cfg()))
            return {"opened": False}

        with patch.object(S, "config") as cfg,              patch.object(S, "_hedge_open", side_effect=fake_open):
            cfg.get.side_effect = _cfg_get(settings)
            S.app.test_client().post("/hedge/open", json=body)
        return R.active_leases(Cfg())

    def test_a_live_open_holds_the_lease_until_it_returns(self):
        seen = []
        settings = {"data.directory": __import__("tempfile").mkdtemp()}
        after = self._post({"short_symbol": "ETH", "dry_run": False},
                           settings, seen)
        self.assertEqual(seen, [{"ETH"}])
        self.assertEqual(after, set())

    def test_a_dry_run_takes_no_lease(self):
        seen = []
        settings = {"data.directory": __import__("tempfile").mkdtemp()}
        self._post({"short_symbol": "ETH"}, settings, seen)
        self.assertEqual(seen, [set()])

    def test_an_unwritable_lease_does_not_block_the_open(self):
        seen = []
        with patch.object(S, "acquire_lease", side_effect=OSError("ro")):
            self._post({"short_symbol": "ETH", "dry_run": False},
                       {"data.directory": __import__("tempfile").mkdtemp()},
                       seen)
        self.assertEqual(len(seen), 1)  # the open still ran


if __name__ == "__main__":
    unittest.main()
