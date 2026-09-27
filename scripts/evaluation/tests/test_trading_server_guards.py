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
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.evaluation.tests._executor_env import (  # noqa: E402
    require_executor_deps)

require_executor_deps()

from executor import compliance as C  # noqa: E402
from executor import server as S  # noqa: E402


def _cfg_get(settings):
    """A config.get that returns `settings[key]`, else the caller's default."""
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
    def __init__(self, equity=1000.0, raises=None):
        self._equity = equity
        self._raises = raises
        self.read_subaccounts = []

    def subaccount_for(self, symbol):
        return {"BTC": 0, "ETH": 1, "SOL": 2}.get(
            str(symbol).upper().split("-")[0], 0)

    def state(self, subaccount=None):
        self.read_subaccounts.append(subaccount)
        if self._raises:
            raise self._raises
        st = {"positions": []}
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
            self.assertEqual(S._effective_cap_notional(), 100.0)

    def test_margin_rule_applies_when_unset(self):
        with patch.object(S, "config") as cfg, \
             patch.object(S, "_venue", side_effect=_venues(
                 _FakeHL(100.0), _FakeDydx(100.0))):
            cfg.get.side_effect = _cfg_get(
                {"trading.executor.max_order_notional_usd": None})
            # 20% x 100 x 3 = 60, no hard cap.
            self.assertAlmostEqual(S._effective_cap_notional(), 60.0)


if __name__ == "__main__":
    unittest.main()
