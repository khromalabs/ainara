# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the multi-position watchdog risk assessment.

executor/watchdog.py is stdlib-only, so this runs under ANY venv (it needs only
the project root on sys.path). Covers the per-coin rework that lifted the
watchdog past a single position:
  - assess() groups both venues' positions by coin and assesses each hedge,
  - broken-hedge actions target the exact naked position (coin + venue symbol),
  - the broken-hedge debounce is isolated per coin,
  - a dYdX "liquidation unknown" note raises an alert, never silence.

Plus the protective actions that used to fall into _act's "not_wired_yet" branch:
  - reduce_both shaves BOTH legs by an equal, step-quantized amount,
  - repeated shaves that don't clear the band escalate to closing the hedge,
  - rebalance only ever TRIMS the larger leg,
  - and every critical finding raises an alarm even when nothing can be sent.

Run:  python -m unittest scripts.evaluation.tests.test_trading_watchdog
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from executor import watchdog as W  # noqa: E402


def hl(*positions):
    return {"venue": "hyperliquid", "positions": list(positions)}


def dydx(*positions):
    return {"venue": "dydx", "positions": list(positions)}


def hl_pos(coin, szi, liq_dist=300.0):
    return {"coin": coin, "szi": szi, "liq_distance_pct": liq_dist, "liq_note": None}


def dy_pos(coin, size, liq_dist=None, liq_note="not liquidatable by price alone"):
    return {"coin": coin, "size": size, "liq_distance_pct": liq_dist,
            "liq_note": liq_note}


class _Cfg:
    """Minimal config stub. `overrides` feeds trading.watchdog."""

    def __init__(self, **overrides):
        self._w = overrides

    def get(self, key, default=None):
        if key == "trading.watchdog":
            return self._w
        if key == "trading.notify":
            return {}  # notifier inert: no webhook, no dead-man ping
        return default


class _FakeHL:
    """Records the reduce-only orders the watchdog sends."""

    def __init__(self, *positions, step=1e-5, perp_account_value=None,
                free_collateral=None):
        self._positions = list(positions)
        self._step = step
        # None = omit the key entirely, matching every pre-existing caller that
        # never set these — _assess_book_margin treats a missing key as
        # "nothing to report", so omitting them changes nothing for any test
        # that doesn't ask for book-margin behavior.
        self._perp_account_value = perp_account_value
        self._free_collateral = free_collateral
        self.reduced = []

    def state(self):
        st = hl(*self._positions)
        if self._perp_account_value is not None:
            st["perp_account_value"] = self._perp_account_value
        if self._free_collateral is not None:
            st["free_collateral"] = self._free_collateral
        return st

    def size_increment(self, coin):
        return self._step

    def reduce(self, coin, size=None, dry_run=False):
        self.reduced.append({"coin": coin, "size": size})
        return {"submitted": True, "order": {"coin": coin, "size": size}}

    def flatten(self, coin, dry_run=False):
        return self.reduce(coin, None, dry_run=dry_run)


class _FakeDydx:
    def __init__(self, *positions, step=1e-4):
        self._positions = list(positions)
        self._step = step
        self.reduced = []

    def state(self):
        return dydx(*self._positions)

    def size_increment(self, market):
        return self._step

    async def place_market_reduce(self, market, is_buy, size, slippage=0.1):
        self.reduced.append({"coin": market, "is_buy": is_buy, "size": size})
        return {"submitted": True, "tx_code": 0}


class AssessMultiPosition(unittest.TestCase):
    def test_single_hedged_pair_is_ok(self):
        r = W.assess(hl(hl_pos("BTC", -0.0008)), dydx(dy_pos("BTC-USD", 0.0008)))
        self.assertEqual(r["risk"], "ok")
        self.assertEqual(r["actions"], [])
        self.assertEqual(r["coins"], ["BTC"])

    def test_fully_flat_is_none(self):
        r = W.assess(hl(), dydx())
        self.assertEqual(r["risk"], "none")
        self.assertEqual(r["actions"], [])

    def test_broken_hedge_targets_only_the_naked_coin(self):
        # BTC hedged, ETH naked on HL. Only ETH should draw a close action.
        r = W.assess(hl(hl_pos("BTC", -0.0008), hl_pos("ETH", -0.02)),
                     dydx(dy_pos("BTC-USD", 0.0008)))
        self.assertEqual(r["risk"], "critical")
        eth = [a for a in r["actions"] if a.get("coin") == "ETH"]
        self.assertEqual(len(eth), 1)
        self.assertEqual(eth[0]["type"], "close_leg")
        self.assertEqual(eth[0]["venue"], "hyperliquid")
        self.assertEqual(eth[0]["symbol"], "ETH")  # venue-native symbol for the actor
        self.assertFalse([a for a in r["actions"] if a.get("coin") == "BTC"])

    def test_dydx_only_naked_targets_usd_symbol(self):
        r = W.assess(hl(), dydx(dy_pos("SOL-USD", 3.0)))
        a = r["actions"][0]
        self.assertEqual((a["venue"], a["symbol"], a["coin"]), ("dydx", "SOL-USD", "SOL"))

    def test_liq_unknown_raises_alert_not_silence(self):
        r = W.assess(
            hl(hl_pos("ETH", -0.02)),
            dydx(dy_pos("ETH-USD", 0.02, liq_dist=None,
                        liq_note="liquidation unknown: market risk params unavailable")))
        self.assertTrue(any(a["reason"] == "liq_unknown" and a["coin"] == "ETH"
                            for a in r["actions"]))

    def test_near_liquidation_is_critical(self):
        r = W.assess(hl(hl_pos("BTC", -0.0008, liq_dist=3.0)),
                     dydx(dy_pos("BTC-USD", 0.0008)))
        self.assertEqual(r["risk"], "critical")
        self.assertTrue(any(a["type"] == "reduce_both" and a["coin"] == "BTC"
                            for a in r["actions"]))


class BookMarginPure(unittest.TestCase):
    """_assess_book_margin: the book-wide HL margin-utilization check, pure."""

    def test_none_when_account_value_missing(self):
        self.assertIsNone(W._assess_book_margin({}))

    def test_none_when_account_value_zero(self):
        self.assertIsNone(W._assess_book_margin(
            {"perp_account_value": 0.0, "free_collateral": 0.0}))

    def test_none_below_warn_threshold(self):
        # 50% used, default warn=70
        st = {"perp_account_value": 1000.0, "free_collateral": 500.0}
        self.assertIsNone(W._assess_book_margin(st))

    def test_warn_at_threshold(self):
        # 70% used, default warn=70/critical=85
        st = {"perp_account_value": 1000.0, "free_collateral": 300.0}
        r = W._assess_book_margin(st)
        self.assertEqual(r["risk"], "warn")
        self.assertEqual(r["action"]["reason"], "hl_book_margin_high")
        self.assertEqual(r["action"]["margin_used_pct"], 70.0)

    def test_critical_above_critical_threshold(self):
        # 90% used
        st = {"perp_account_value": 1000.0, "free_collateral": 100.0}
        r = W._assess_book_margin(st)
        self.assertEqual(r["risk"], "critical")
        self.assertEqual(r["action"]["severity"], "critical")

    def test_custom_thresholds_respected(self):
        st = {"perp_account_value": 1000.0, "free_collateral": 400.0}  # 60%
        self.assertIsNone(W._assess_book_margin(st, warn_pct=70.0))
        r = W._assess_book_margin(st, warn_pct=50.0, critical_pct=90.0)
        self.assertEqual(r["risk"], "warn")


class BookMarginGuardOnce(unittest.TestCase):
    """Wired through guard_once(): merged into the SAME report, findings and
    alarm channel as every other risk — alert-only, so it never adds an
    action to _act's known types (it lands in the generic 'alert' branch)."""

    def _wd(self, perp_account_value=None, free_collateral=None, **cfg):
        hl_adapter = _FakeHL(hl_pos("BTC", -0.0008),
                             perp_account_value=perp_account_value,
                             free_collateral=free_collateral)
        return W.Watchdog(hl_adapter, _FakeDydx(dy_pos("BTC-USD", 0.0008)),
                          _Cfg(**cfg))

    def test_below_warn_adds_nothing(self):
        wd = self._wd(perp_account_value=1000.0, free_collateral=500.0)
        rep = wd.guard_once()
        self.assertFalse(any(a.get("reason") == "hl_book_margin_high"
                             for a in rep["actions"]))

    def test_warn_raises_alert_and_bumps_risk_from_ok(self):
        # BTC hedge alone is "ok"; book margin at 75% (>= default warn 70)
        # must still surface even though nothing else is wrong.
        wd = self._wd(perp_account_value=1000.0, free_collateral=250.0)
        rep = wd.guard_once()
        self.assertEqual(rep["risk"], "warn")
        self.assertTrue(any(a.get("reason") == "hl_book_margin_high"
                            for a in rep["actions"]))

    def test_alert_only_no_order_sent(self):
        wd = self._wd(perp_account_value=1000.0, free_collateral=50.0)  # 95%
        wd.mode = "active"
        rep = wd.guard_once()
        self.assertEqual(rep["risk"], "critical")
        self.assertEqual(wd.hl.reduced, [])  # no order — monitor only

    def test_alarm_file_written_and_clears_when_utilization_drops(self):
        with tempfile.TemporaryDirectory() as d:
            alarm_file = os.path.join(d, "alarm.json")
            wd = self._wd(perp_account_value=1000.0, free_collateral=100.0)  # 90%
            wd.alarm_file = alarm_file
            wd.guard_once()
            with open(alarm_file) as f:
                payload = json.load(f)
            self.assertTrue(any(a["kind"] == "hl_book_margin_high"
                                for a in payload["alarms"]))

            wd.hl = _FakeHL(hl_pos("BTC", -0.0008),
                            perp_account_value=1000.0, free_collateral=900.0)  # 10%
            wd.guard_once()
            self.assertFalse(os.path.exists(alarm_file))

    def test_custom_thresholds_via_config(self):
        wd = self._wd(perp_account_value=1000.0, free_collateral=550.0,  # 45%
                      hl_book_margin_warn_pct=40.0)
        rep = wd.guard_once()
        self.assertTrue(any(a.get("reason") == "hl_book_margin_high"
                            for a in rep["actions"]))


class SizePlans(unittest.TestCase):
    """The arithmetic that decides how much of a live position to sell."""

    def test_floor_to_step_survives_binary_floats(self):
        # 0.0024 / 0.0001 is 23.999999999999996 in binary — a naive floor loses a
        # whole step, i.e. sells less than planned on one venue than the other.
        self.assertAlmostEqual(W.floor_to_step(0.0024, 0.0001), 0.0024)
        self.assertAlmostEqual(W.floor_to_step(0.00025, 0.0001), 0.0002)
        self.assertEqual(W.floor_to_step(0.00005, 0.0001), 0.0)
        self.assertAlmostEqual(W.floor_to_step(0.3, None), 0.3)  # no quantization

    def test_reduce_is_equal_on_both_legs_and_step_quantized(self):
        # Legs of 0.0008; half is 0.0004, already a multiple of the coarser step.
        self.assertAlmostEqual(
            W.plan_reduce(-0.0008, 0.0008, 0.5, step=1e-4), 0.0004)

    def test_reduce_sizes_off_the_smaller_leg(self):
        # Never plan a shave the smaller leg cannot cover.
        qty = W.plan_reduce(-0.01, 0.002, 0.5, step=1e-4)
        self.assertLessEqual(qty, 0.002)
        self.assertAlmostEqual(qty, 0.001)

    def test_reduce_returns_zero_when_under_one_step(self):
        # Caller must escalate to a full close rather than send nothing.
        self.assertEqual(W.plan_reduce(-0.0001, 0.0001, 0.5, step=1e-4), 0.0)

    def test_reduce_fraction_is_clamped(self):
        self.assertAlmostEqual(W.plan_reduce(-1.0, 1.0, 5.0, step=0.1), 1.0)
        self.assertEqual(W.plan_reduce(-1.0, 1.0, -1.0, step=0.1), 0.0)

    def test_rebalance_trims_the_larger_leg_only(self):
        venue, qty = W.plan_rebalance(-0.0012, 0.0008, step=1e-4)
        self.assertEqual(venue, "hyperliquid")
        self.assertAlmostEqual(qty, 0.0004)
        venue, qty = W.plan_rebalance(-0.0008, 0.0012, step=1e-4)
        self.assertEqual(venue, "dydx")
        self.assertAlmostEqual(qty, 0.0004)

    def test_rebalance_noop_when_balanced_or_sub_step(self):
        self.assertEqual(W.plan_rebalance(-0.001, 0.001, 1e-4), (None, 0.0))
        self.assertEqual(W.plan_rebalance(-0.00105, 0.001, 1e-4)[1], 0.0)


class ReduceBothIsWired(unittest.TestCase):
    """The near-liquidation path — previously 'not_wired_yet', i.e. a log line."""

    def _wd(self, **cfg):
        self.hl = _FakeHL(hl_pos("BTC", -0.0008, liq_dist=3.0))
        self.dy = _FakeDydx(dy_pos("BTC-USD", 0.0008))
        wd = W.Watchdog(self.hl, self.dy, _Cfg(**cfg))
        wd.mode = "active"
        wd.alarm_file = os.path.join(tempfile.mkdtemp(), "alarm.json")
        return wd

    def test_both_legs_reduced_by_the_same_quantized_amount(self):
        wd = self._wd()
        rep = wd.guard_once()
        res = next(e["result"] for e in rep["executed"]
                   if e["action"]["type"] == "reduce_both")
        self.assertEqual(res["plan"], "reduce")
        self.assertEqual(len(self.hl.reduced), 1)
        self.assertEqual(len(self.dy.reduced), 1)
        # Equal size on both venues, or the de-risking itself creates naked delta.
        self.assertAlmostEqual(self.hl.reduced[0]["size"],
                               self.dy.reduced[0]["size"])
        self.assertAlmostEqual(self.hl.reduced[0]["size"], 0.0004)
        # Buy to reduce the dYdX long? No — the long is reduced by SELLING.
        self.assertFalse(self.dy.reduced[0]["is_buy"])

    def test_threatened_venue_is_derisked_first(self):
        wd = self._wd()
        # dYdX is the leg near liquidation this time.
        self.hl._positions = [hl_pos("BTC", -0.0008)]
        self.dy._positions = [dy_pos("BTC-USD", 0.0008, liq_dist=2.0,
                                     liq_note=None)]
        rep = wd.guard_once()
        res = next(e["result"] for e in rep["executed"]
                   if e["action"]["type"] == "reduce_both")
        self.assertEqual(res["sequence"][0], "dydx")

    def test_cooldown_blocks_a_second_shave(self):
        wd = self._wd()
        wd.guard_once()
        rep = wd.guard_once()  # same poll data, immediately after
        res = next(e["result"] for e in rep["executed"]
                   if e["action"]["type"] == "reduce_both")
        self.assertEqual(res["skipped"], "cooldown")
        self.assertEqual(len(self.hl.reduced), 1)  # not shaved twice

    def test_exhausted_shaves_escalate_to_closing_the_hedge(self):
        wd = self._wd(reduce_max_attempts=2, reduce_cooldown_seconds=0)
        wd.guard_once()
        wd.guard_once()
        rep = wd.guard_once()  # third: over the limit
        res = next(e["result"] for e in rep["executed"]
                   if e["action"]["type"] == "reduce_both")
        self.assertEqual(res["plan"], "close_hedge")
        self.assertIsNone(res["qty"])  # None = the whole leg
        self.assertIsNone(self.hl.reduced[-1]["size"])
        self.assertIn("reduce_exhausted:BTC", wd._risk_alarms)

    def test_sub_step_position_is_closed_not_shaved(self):
        wd = self._wd()
        self.hl._positions = [hl_pos("BTC", -0.0001, liq_dist=3.0)]
        self.dy._positions = [dy_pos("BTC-USD", 0.0001)]
        rep = wd.guard_once()
        res = next(e["result"] for e in rep["executed"]
                   if e["action"]["type"] == "reduce_both")
        self.assertEqual(res["plan"], "close_hedge")

    def test_rebalance_trims_only_the_oversized_leg(self):
        wd = self._wd()
        self.hl._positions = [hl_pos("BTC", -0.0012)]   # 50% bigger than dYdX
        self.dy._positions = [dy_pos("BTC-USD", 0.0008)]
        rep = wd.guard_once()
        res = next(e["result"] for e in rep["executed"]
                   if e["action"]["type"] == "rebalance")
        self.assertEqual(res["venue"], "hyperliquid")
        self.assertAlmostEqual(res["qty"], 0.0004)
        self.assertEqual(len(self.hl.reduced), 1)
        self.assertEqual(self.dy.reduced, [])  # the smaller leg is never touched


class AlarmsAreNeverSilent(unittest.TestCase):
    """A critical finding must reach the alarm file whether or not it is actionable."""

    def _wd(self, hl_state, dy_state, **cfg):
        wd = W.Watchdog(_FakeHL(*hl_state["positions"]),
                        _FakeDydx(*dy_state["positions"]), _Cfg(**cfg))
        wd.alarm_file = os.path.join(tempfile.mkdtemp(), "alarm.json")
        return wd

    def _alarm(self, wd):
        with open(wd.alarm_file, encoding="utf-8") as fh:
            return json.load(fh)

    def test_liq_unknown_writes_an_alarm_with_no_order_involved(self):
        # An open leg whose liquidation distance cannot be computed is UNMONITORED.
        # It emits only an `alert`, so before this it wrote nothing anywhere.
        wd = self._wd(
            hl(hl_pos("ETH", -0.02)),
            dydx(dy_pos("ETH-USD", 0.02, liq_dist=None,
                        liq_note="liquidation unknown: market risk params"
                                 " unavailable")))
        wd.guard_once()
        alarm = self._alarm(wd)
        self.assertEqual([a["kind"] for a in alarm["alarms"]], ["liq_unknown"])
        self.assertEqual(alarm["severity"], "warning")

    def test_near_liquidation_alarms_even_in_monitor_mode(self):
        wd = self._wd(hl(hl_pos("BTC", -0.0008, liq_dist=3.0)),
                      dydx(dy_pos("BTC-USD", 0.0008)))
        self.assertEqual(wd.mode, "monitor")  # nothing will be sent
        rep = wd.guard_once()
        self.assertEqual(rep["executed"], {"skipped": "mode=monitor (report only)"})
        self.assertEqual(self._alarm(wd)["alarm"], "near_liquidation")

    def test_alarm_file_is_refreshed_each_poll_so_it_never_reads_stale(self):
        wd = self._wd(hl(hl_pos("BTC", -0.0008, liq_dist=3.0)),
                      dydx(dy_pos("BTC-USD", 0.0008)))
        wd.guard_once()
        first = self._alarm(wd)["ts"]
        wd.guard_once()
        self.assertGreaterEqual(self._alarm(wd)["ts"], first)

    def test_alarm_clears_when_the_condition_does(self):
        wd = self._wd(hl(hl_pos("BTC", -0.0008, liq_dist=3.0)),
                      dydx(dy_pos("BTC-USD", 0.0008)))
        wd.guard_once()
        self.assertTrue(os.path.exists(wd.alarm_file))
        wd.hl._positions = [hl_pos("BTC", -0.0008, liq_dist=300.0)]  # safe again
        rep = wd.guard_once()
        self.assertEqual(rep["risk"], "ok")
        self.assertFalse(os.path.exists(wd.alarm_file))
        self.assertEqual(wd._risk_alarms, {})

    def test_action_alarms_retire_with_the_condition_that_caused_them(self):
        # A refused shave has no assessment action of its own to disappear, so
        # nothing used to clear it — one failure would pin the alarm file open for
        # the life of the process and the all-clear would never fire.
        wd = self._wd(hl(hl_pos("BTC", -0.0008, liq_dist=3.0)),
                      dydx(dy_pos("BTC-USD", 0.0008)))
        wd._add_alarm("reduce_failed:BTC", "reduce_failed", "critical", "x",
                      coin="BTC")
        wd._reduce_attempts["BTC"] = 2
        wd.hl._positions = [hl_pos("BTC", -0.0008, liq_dist=300.0)]  # band cleared
        wd.guard_once()
        self.assertEqual(wd._risk_alarms, {})
        self.assertNotIn("BTC", wd._reduce_attempts)  # new episode, full budget
        self.assertFalse(os.path.exists(wd.alarm_file))

    def test_per_coin_state_is_swept_when_the_coin_goes_flat(self):
        wd = self._wd(hl(hl_pos("BTC", -0.0008, liq_dist=3.0)),
                      dydx(dy_pos("BTC-USD", 0.0008)))
        wd._add_alarm("reduce_exhausted:BTC", "reduce_exhausted", "critical", "x",
                      coin="BTC")
        wd._reduce_attempts["BTC"] = 3
        wd.hl._positions, wd.dydx._positions = [], []  # closed out entirely
        rep = wd.guard_once()
        self.assertEqual(rep["risk"], "none")
        self.assertEqual(wd._risk_alarms, {})
        self.assertEqual(wd._reduce_attempts, {})

    def test_same_direction_legs_alarm_as_critical(self):
        wd = self._wd(hl(hl_pos("BTC", 0.0008)), dydx(dy_pos("BTC-USD", 0.0008)))
        wd.guard_once()
        alarm = self._alarm(wd)
        self.assertEqual(alarm["alarm"], "not_delta_neutral")
        self.assertEqual(alarm["severity"], "critical")


class UnreadableVenueFailsClosed(unittest.TestCase):
    """Regression for the 2026-07-27 incident.

    dydx.state() returned a dict with NO "positions" key for any unexpected indexer
    reply (a 429, a 5xx, a degraded body), and `state.get("positions") or []` read
    that as "flat". Three fully-hedged coins were assessed as three BROKEN HEDGES,
    every Hyperliquid leg was flattened at 18:34 UTC, and because the dYdX read
    stayed broken the watchdog could not see the three long legs it had stranded.
    They ran unhedged for eight hours: -$4.64 on a hedge that was +$0.08 while intact.

    An unreadable venue must be UNKNOWN, never empty.
    """

    # Exactly what the old dydx.state() returned on a failed read.
    STALE_DYDX = {"venue": "dydx", "network": "mainnet", "address": "dydx1...",
                  "subaccount_exists": False,
                  "note": "no subaccount yet (fund it before trading)"}

    HEDGED_HL = hl(hl_pos("BTC", -0.0008), hl_pos("ETH", -0.03),
                   hl_pos("SOL", -0.7))

    def test_the_incident_no_longer_produces_close_actions(self):
        r = W.assess(self.HEDGED_HL, self.STALE_DYDX)
        self.assertEqual(r["risk"], "critical")
        self.assertEqual(r["unreadable"], ["dydx"])
        self.assertEqual([a["type"] for a in r["actions"]], ["alert"])
        self.assertEqual(r["actions"][0]["reason"], "venue_unreadable")
        # The whole point: not one order.
        self.assertFalse([a for a in r["actions"] if a["type"] != "alert"])
        self.assertIn("UNREADABLE", r["findings"][0])

    def test_unreadable_hyperliquid_is_equally_fatal(self):
        # The mirror case: a 200 with an unexpected body would have made HL look
        # flat and every dYdX leg look naked.
        r = W.assess({"venue": "hyperliquid", "unreadable": "HTTPError: 502"},
                     dydx(dy_pos("BTC-USD", 0.0008)))
        self.assertEqual(r["unreadable"], ["hyperliquid"])
        self.assertEqual([a["type"] for a in r["actions"]], ["alert"])

    def test_a_genuinely_empty_but_READABLE_venue_still_works(self):
        # The legitimate "no subaccount yet" answer now carries positions: [] — a
        # real reading of an empty account, so a naked HL leg is still caught.
        empty = {"venue": "dydx", "subaccount_exists": False, "positions": [],
                 "note": "no subaccount yet (fund it before trading)"}
        r = W.assess(hl(hl_pos("BTC", -0.0008)), empty)
        self.assertNotIn("unreadable", r)
        self.assertEqual([a["type"] for a in r["actions"]], ["close_leg"])

    def test_read_state_converts_a_raise_into_unreadable(self):
        class Boom:
            def state(self):
                raise RuntimeError("indexer 429")

        wd = W.Watchdog(Boom(), _FakeDydx(), _Cfg())
        st = wd._read_state(wd.hl, "hyperliquid")
        self.assertIn("429", st["unreadable"])
        self.assertFalse(W._venue_readable(st))

    def test_read_state_rejects_a_payload_with_no_position_list(self):
        class NoPositions:
            def state(self):
                return {"venue": "dydx", "subaccount_exists": False}

        wd = W.Watchdog(_FakeHL(), NoPositions(), _Cfg())
        st = wd._read_state(wd.dydx, "dydx")
        self.assertEqual(st["unreadable"], "response carried no position list")

    def test_a_blind_poll_acts_on_nothing_and_alarms(self):
        class Boom:
            def state(self):
                raise RuntimeError("indexer 429")

        wd = W.Watchdog(_FakeHL(hl_pos("BTC", -0.0008)), Boom(), _Cfg())
        wd.mode = "active"
        wd.alarm_file = os.path.join(tempfile.mkdtemp(), "alarm.json")
        rep = wd.guard_once()
        self.assertEqual(rep["unreadable"], ["dydx"])
        self.assertEqual(wd.hl.reduced, [])  # nothing sent, in ACTIVE mode
        with open(wd.alarm_file, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["alarm"], "venue_unreadable")

    def test_a_blind_poll_never_clears_a_real_alarm(self):
        # A leg near liquidation must not be "resolved" by the outage that stopped
        # us watching it.
        class Flaky:
            def __init__(self): self.blind = False
            def state(self):
                if self.blind:
                    raise RuntimeError("indexer 429")
                return dydx(dy_pos("BTC-USD", 0.0008))
            def size_increment(self, m): return 1e-4

        dy = Flaky()
        wd = W.Watchdog(_FakeHL(hl_pos("BTC", -0.0008, liq_dist=3.0)), dy, _Cfg())
        wd.alarm_file = os.path.join(tempfile.mkdtemp(), "alarm.json")
        wd.guard_once()
        self.assertIn("near_liquidation:BTC", wd._risk_alarms)
        dy.blind = True
        wd.guard_once()
        self.assertIn("near_liquidation:BTC", wd._risk_alarms)  # still there
        self.assertIn("venue_unreadable:dydx", wd._risk_alarms)


class DebounceIsolation(unittest.TestCase):
    def setUp(self):
        self.wd = W.Watchdog(hl_adapter=None, dydx_adapter=None, config=_Cfg())
        self.wd.confirm_polls = 3

    def _eth_broken(self):
        return W.assess(hl(hl_pos("BTC", -0.0008), hl_pos("ETH", -0.02)),
                        dydx(dy_pos("BTC-USD", 0.0008)))

    def test_broken_hedge_held_then_released_per_coin(self):
        for i in (1, 2):
            rep = self.wd._debounce_broken_hedge(self._eth_broken())
            passed = [a for a in rep["actions"] if a.get("reason") == "broken_hedge"]
            self.assertEqual(passed, [], f"ETH should be held on poll {i}")
            self.assertEqual(self.wd._broken_streak["ETH"], i)
        rep = self.wd._debounce_broken_hedge(self._eth_broken())
        passed = [a for a in rep["actions"] if a.get("reason") == "broken_hedge"]
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0]["coin"], "ETH")

    def test_streak_resets_when_coin_heals(self):
        self.wd._debounce_broken_hedge(self._eth_broken())
        self.assertIn("ETH", self.wd._broken_streak)
        # ETH now hedged on both venues -> its streak clears, nothing else touched.
        healed = W.assess(hl(hl_pos("BTC", -0.0008), hl_pos("ETH", -0.02)),
                          dydx(dy_pos("BTC-USD", 0.0008), dy_pos("ETH-USD", 0.02)))
        self.wd._debounce_broken_hedge(healed)
        self.assertNotIn("ETH", self.wd._broken_streak)


if __name__ == "__main__":
    unittest.main()
