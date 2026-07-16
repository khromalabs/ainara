# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Always-on deterministic guard for the delta-neutral position.

Runs on a fast loop, independent of the (slower) Conductor plan, to catch the two
failure modes that can wipe the strategy out between Conductor runs:

  1. BROKEN HEDGE — one leg is gone (liquidated/closed) while the other is still
     open. You are now naked-directional on leverage. This is THE #1 blow-up risk;
     the fix is to flatten the surviving leg immediately.
  2. LIQUIDATION PROXIMITY — a leg has drifted close to its liquidation price.

assess() is a pure function (no I/O) so the risk logic is unit-testable. The loop
reads live state, assesses, and — only in 'active' mode — acts. Default mode is
'monitor' (report only); acting is opt-in via config trading.watchdog.mode.
"""

import asyncio
import concurrent.futures
import logging
import time

logger = logging.getLogger("executor.watchdog")


def _run_coro(coro):
    """Run a coroutine to completion whether or not a loop is already running in
    this thread. The watchdog's own loop is synchronous, but _act may also be
    invoked from an async caller (tests, a future async host)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # no running loop — simplest path
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def _leg(state):
    """Normalize an adapter state dict to {open, size, liq_distance_pct} for the
    first (single-market MVP) position, or a flat leg. Handles both venues: HL
    positions carry 'szi', dYdX carry 'size' — both signed."""
    positions = state.get("positions")
    if positions:
        p = positions[0]
        size = p.get("szi", p.get("size", 0)) or 0
        return {"open": abs(size) > 0, "size": size,
                "liq_distance_pct": p.get("liq_distance_pct"),
                "coin": p.get("coin")}
    return {"open": False, "size": 0.0, "liq_distance_pct": None, "coin": None}


def assess(hl, dydx, *, liq_critical_pct=5.0, size_tolerance_pct=15.0):
    """Pure risk assessment over two normalized legs. Returns
    {risk, findings, actions}. risk in {none, ok, warn, critical}."""
    a, b = _leg(hl), _leg(dydx)
    findings, actions = [], []

    # 1. Broken hedge — highest priority, short-circuits.
    if a["open"] != b["open"]:
        naked = "hyperliquid" if a["open"] else "dydx"
        findings.append(
            f"BROKEN HEDGE: only {naked} holds a position — naked directional")
        actions.append({"type": "close_leg", "venue": naked,
                        "reason": "broken_hedge"})
        return {"risk": "critical", "findings": findings, "actions": actions}

    if not a["open"] and not b["open"]:
        return {"risk": "none", "findings": ["flat — both legs closed"],
                "actions": []}

    # both legs open ------------------------------------------------------
    # 2. Delta neutrality: sizes should have opposite signs (when both known).
    if a["size"] is not None and b["size"] is not None:
        if (a["size"] > 0) == (b["size"] > 0):
            findings.append("NOT DELTA-NEUTRAL: both legs same direction")
            actions.append({"type": "alert", "reason": "same_direction"})

    # 3. Liquidation proximity on either leg.
    for venue, leg in (("hyperliquid", a), ("dydx", b)):
        d = leg["liq_distance_pct"]
        if d is not None and d < liq_critical_pct:
            findings.append(
                f"{venue} is {d:.1f}% from liquidation (< {liq_critical_pct}%)")
            actions.append({"type": "reduce_both", "trigger": venue,
                            "reason": "near_liquidation"})

    # 4. Size imbalance (only when both sizes known).
    if a["size"] and b["size"]:
        hs, ds = abs(a["size"]), abs(b["size"])
        imb = abs(hs - ds) / max(hs, ds) * 100
        if imb > size_tolerance_pct:
            findings.append(
                f"leg size imbalance {imb:.1f}% (> {size_tolerance_pct}%)")
            actions.append({"type": "rebalance", "reason": "size_imbalance"})

    critical = {"close_leg", "reduce_both"}
    risk = ("critical" if any(x["type"] in critical for x in actions)
            else "warn" if actions else "ok")
    return {"risk": risk,
            "findings": findings or ["both legs open and hedged"],
            "actions": actions}


class Watchdog:
    def __init__(self, hl_adapter, dydx_adapter, config):
        self.hl = hl_adapter
        self.dydx = dydx_adapter
        self.config = config
        w = config.get("trading.watchdog", {}) or {}
        self.mode = w.get("mode", "monitor")  # 'monitor' | 'active'
        self.interval = float(w.get("interval_seconds", 5))
        self.liq_critical_pct = float(w.get("liq_critical_pct", 5.0))
        self.size_tolerance_pct = float(w.get("size_tolerance_pct", 15.0))

    def guard_once(self):
        """Read both legs, assess, and (in active mode) act. Returns the report."""
        hl_state = self.hl.state()
        dydx_state = self.dydx.state()
        report = assess(hl_state, dydx_state,
                        liq_critical_pct=self.liq_critical_pct,
                        size_tolerance_pct=self.size_tolerance_pct)
        if report["risk"] in ("warn", "critical"):
            logger.warning("watchdog risk=%s: %s", report["risk"],
                           "; ".join(report["findings"]))
        if report["actions"] and self.mode == "active":
            report["executed"] = self._act(report["actions"])
        elif report["actions"]:
            report["executed"] = {"skipped": "mode=monitor (report only)"}
        return report

    def _act(self, actions):
        """Execute protective actions. 'close_leg' flattens the exposed leg on
        either venue with a reduce-only, aggressively-priced (crossing) order.
        reduce/rebalance are recorded until their order construction lands."""
        done = []
        for act in actions:
            if act["type"] == "close_leg" and act["venue"] == "hyperliquid":
                pos = (self.hl.state().get("positions") or [None])[0]
                if pos and abs(pos["szi"]) > 0:
                    is_buy = pos["szi"] < 0  # buy to close short, sell to close long
                    px = pos["mark_px"] or 0
                    limit = px * (1.05 if is_buy else 0.95)
                    res = self.hl.place_order(pos["coin"], is_buy, abs(pos["szi"]),
                                              round(limit), reduce_only=True,
                                              tif="Ioc", dry_run=False)
                    done.append({"action": act, "result": res})
                else:
                    done.append({"action": act, "result": "no position to close"})
            elif act["type"] == "close_leg" and act["venue"] == "dydx":
                pos = (self.dydx.state().get("positions") or [None])[0]
                if pos and abs(pos["size"]) > 0:
                    is_buy = pos["size"] < 0  # buy to close short, sell to close long
                    res = _run_coro(self.dydx.place_market_reduce(
                        pos["coin"], is_buy, abs(pos["size"])))
                    done.append({"action": act, "result": res})
                else:
                    done.append({"action": act, "result": "no position to close"})
            else:
                done.append({"action": act, "result": "not_wired_yet"})
        return done

    def run(self):
        logger.info("watchdog starting: mode=%s interval=%ss", self.mode,
                    self.interval)
        while True:
            try:
                self.guard_once()
            except Exception as e:  # never let the guard die silently
                logger.error("watchdog loop error: %s", e)
            time.sleep(self.interval)


def main():
    """Standalone entry point: python -m executor.watchdog

    Wires the two venue adapters and runs the guard loop. Mode comes from config
    (trading.watchdog.mode): 'monitor' (default) logs warnings only; 'active'
    auto-flattens the exposed leg on a broken hedge.
    """
    import logging as _logging

    from executor.config import ExecutorConfig
    from executor.venues.dydx import DydxExecutor
    from executor.venues.hyperliquid import HyperliquidExecutor

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = ExecutorConfig()
    wd = Watchdog(HyperliquidExecutor(config), DydxExecutor(config), config)
    if wd.mode != "active":
        logger.warning(
            "watchdog mode is '%s' — it will REPORT risks but NOT auto-close."
            " Set trading.watchdog.mode: active in ainara.yaml to enable"
            " automatic leg flattening.", wd.mode,
        )
    try:
        wd.run()
    except KeyboardInterrupt:
        logger.info("watchdog stopped")


if __name__ == "__main__":
    main()
