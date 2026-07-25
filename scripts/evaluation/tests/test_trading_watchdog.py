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

Run:  python -m unittest scripts.evaluation.tests.test_trading_watchdog
"""

import os
import sys
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
    def get(self, key, default=None):
        return {} if key == "trading.watchdog" else default


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
