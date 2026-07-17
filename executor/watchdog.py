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
import json
import logging
import os
import tempfile
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
                "liq_note": p.get("liq_note"),
                "coin": p.get("coin")}
    return {"open": False, "size": 0.0, "liq_distance_pct": None,
            "liq_note": None, "coin": None}


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
    #    A `None` distance is skipped — but that is only safe when it means "no
    #    reachable liquidation". If the venue's risk params could not be read we
    #    are flying blind on an open leg, and silence would look identical to
    #    safety, so say so instead.
    for venue, leg in (("hyperliquid", a), ("dydx", b)):
        d = leg["liq_distance_pct"]
        if d is None:
            if leg["open"] and (leg.get("liq_note") or "").startswith(
                    "liquidation unknown"):
                findings.append(
                    f"{venue}: liquidation distance UNKNOWN — risk params"
                    " unavailable; this leg is unmonitored")
                actions.append({"type": "alert", "reason": "liq_unknown",
                                "venue": venue})
            continue
        if d < liq_critical_pct:
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
        # A hedge is TRANSIENTLY broken every time one is opened: leg 1 is on and
        # leg 2 is not, for as long as the second fill takes. dYdX state also comes
        # from the indexer, which lags, so a filled long can read as missing for a
        # moment. Acting on the first sighting means flattening healthy hedges
        # mid-open — on 2026-07-16 the watchdog closed a leg 13s in, while the
        # opener was still working. Require the break to PERSIST before closing.
        self.confirm_polls = int(w.get("confirm_polls", 3))
        self._broken_streak = 0
        # Acting is not the same as fixing. _act used to fire a close, record the
        # venue's answer into a dict, and let run() throw it away — so a close that
        # never filled looked identical to one that worked, and the loop retried in
        # silence forever. On 2026-07-16 that ran for ~30min against an empty dYdX
        # testnet book while the console cheerfully logged "BROKEN HEDGE" as though
        # it were handling it. Count consecutive failures and get loud.
        self.escalate_after = int(w.get("escalate_after", 3))
        self.alarm_file = w.get("alarm_file") or os.path.join(
            tempfile.gettempdir(), "ainara_executor_watchdog_alarm.json")
        # Retry backoff, applied only AFTER escalation. The first few attempts
        # fire every poll — a transient API blip or momentary liquidity gap
        # deserves a fast retry. Past escalate_after the failure is structural
        # (dead book, misconfig, halted market) and hammering fixes nothing: on
        # mainnet every retry is an on-chain tx burning gas on an action that
        # cannot succeed, and escalation means a human is required by definition.
        # Back off exponentially, capped — but NEVER stop: if liquidity returns we
        # still want to flatten without being told to.
        self.backoff_base_seconds = float(w.get("backoff_base_seconds", 30))
        self.backoff_max_seconds = float(w.get("backoff_max_seconds", 300))
        self._close_attempts = {}
        self._escalated = set()
        self._next_attempt_at = {}

    def _debounce_broken_hedge(self, report):
        """Hold back the broken-hedge close until the break persists.

        Only the broken-hedge close is debounced — it is the one that races a
        legitimate open. Liquidation proximity is real and is never delayed.
        Any healthy (or flat) reading resets the streak, so a hedge that finishes
        opening is never touched, while a genuinely naked leg still gets closed
        after confirm_polls * interval seconds.
        """
        broken = [a for a in report["actions"]
                  if a["type"] == "close_leg" and a.get("reason") == "broken_hedge"]
        if not broken:
            self._broken_streak = 0
            if self._close_attempts:
                # We were trying to flatten something and no longer need to —
                # either it worked or it was closed elsewhere. Stand down.
                logger.info("watchdog: hedge no longer broken — clearing alarm")
                self._clear_alarm()
            return report
        self._broken_streak += 1
        if self._broken_streak >= self.confirm_polls:
            return report
        report["actions"] = [a for a in report["actions"] if a not in broken]
        report["debounced"] = {
            "held": "close_leg/broken_hedge",
            "streak": self._broken_streak,
            "confirm_polls": self.confirm_polls,
            "note": "break not confirmed yet (may be a hedge mid-open)",
        }
        logger.info(
            "watchdog: broken hedge seen %s/%s — holding off (may be mid-open)",
            self._broken_streak, self.confirm_polls)
        return report

    @staticmethod
    def _close_failed(res):
        """Did a protective close fail to reach the venue?

        Conservative: only an explicit refusal counts as failed here. A close that
        was accepted but never FILLED (an IOC against an empty book) still looks
        fine at this layer — that one is caught by the leg still being open on the
        next poll, which is why acting is never treated as fixing.
        """
        if isinstance(res, str):
            return False  # "no position to close"
        if not isinstance(res, dict):
            return False
        return res.get("submitted") is False or bool(res.get("error"))

    def _raise_alarm(self, venue, attempts, last_result, findings):
        """Escalate: a leg we are supposed to be protecting is not being fixed.

        The watchdog is the last line of defence, so when it cannot do its job the
        one unacceptable outcome is silence. Logs at ERROR and drops a file the
        daemon surfaces on /health, so the alarm outlives the console scrollback.
        """
        logger.error(
            "WATCHDOG CANNOT FLATTEN %s AFTER %s ATTEMPTS — the leg is STILL OPEN "
            "and this loop is NOT fixing it. Intervene manually. Last venue "
            "response: %s", venue, attempts, last_result)
        payload = {
            "alarm": "watchdog_cannot_flatten",
            "venue": venue,
            "attempts": attempts,
            "findings": findings,
            "last_result": str(last_result)[:500],
            "ts": time.time(),
        }
        try:
            with open(self.alarm_file, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except Exception as e:  # never let alarm plumbing kill the guard loop
            logger.error("watchdog: could not write alarm file %s: %s",
                         self.alarm_file, e)

    def _should_attempt_close(self, venue):
        """Is a close retry due, or are we backing off after escalation?"""
        return time.monotonic() >= self._next_attempt_at.get(venue, 0.0)

    def _schedule_next_attempt(self, venue):
        """Set when this venue may be retried. No delay until we've escalated."""
        attempts = self._close_attempts.get(venue, 0)
        if attempts < self.escalate_after:
            self._next_attempt_at[venue] = 0.0  # still fast-retrying
            return
        over = attempts - self.escalate_after
        delay = min(self.backoff_base_seconds * (2 ** over),
                    self.backoff_max_seconds)
        self._next_attempt_at[venue] = time.monotonic() + delay
        logger.info(
            "watchdog: %s close retries backing off to every %.0fs after %s "
            "failed attempts (still monitoring; will retry if it becomes "
            "fillable)", venue, delay, attempts)

    def _clear_alarm(self):
        """Healthy again — drop the alarm state and the file."""
        self._close_attempts = {}
        self._escalated = set()
        self._next_attempt_at = {}
        try:
            if os.path.exists(self.alarm_file):
                os.remove(self.alarm_file)
        except Exception as e:
            logger.warning("watchdog: could not clear alarm file: %s", e)

    def _record_close_attempt(self, venue, res, findings):
        """Log what the venue actually said, count failures, escalate if stuck."""
        self._close_attempts[venue] = self._close_attempts.get(venue, 0) + 1
        attempts = self._close_attempts[venue]
        if self._close_failed(res):
            logger.error("watchdog: close REFUSED on %s (attempt %s): %s",
                         venue, attempts, res)
        else:
            # Accepted — but accepted is not flat. The next poll decides.
            logger.warning("watchdog: close attempt %s sent on %s -> %s",
                           attempts, venue, res)
        if attempts >= self.escalate_after and venue not in self._escalated:
            self._raise_alarm(venue, attempts, res, findings)
            self._escalated.add(venue)
        self._schedule_next_attempt(venue)

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
        report = self._debounce_broken_hedge(report)
        if report["actions"] and self.mode == "active":
            report["executed"] = self._act(report["actions"], report["findings"])
        elif report["actions"]:
            report["executed"] = {"skipped": "mode=monitor (report only)"}
        if self._escalated:
            report["alarm"] = {"cannot_flatten": sorted(self._escalated),
                               "attempts": dict(self._close_attempts)}
        return report

    def _try_close(self, venue, fn, findings):
        """Run a close and record it — an exception is a FAILED ATTEMPT, not an escape.

        Without this, a raising adapter skips _record_close_attempt entirely and
        bubbles to run()'s catch-all, which just logs and sleeps: no count, no
        alarm, no escalation. That is the same silent-failure bug in a different
        hat — the loop would look busy while protecting nothing.
        """
        try:
            res = fn()
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {e}"}
            logger.error("watchdog: close on %s RAISED: %s", venue, e)
        self._record_close_attempt(venue, res, findings)
        return res

    def _act(self, actions, findings=None):
        """Execute protective actions. 'close_leg' flattens the exposed leg on
        either venue with a reduce-only, aggressively-priced (crossing) order.
        reduce/rebalance are recorded until their order construction lands.

        Every close is recorded and counted: sending an order is not the same as
        flattening a position, and a leg that is still open on the next poll means
        this did NOT work — however cleanly the venue accepted it.
        """
        done = []
        for act in actions:
            if act["type"] == "close_leg" and act["venue"] == "hyperliquid":
                if not self._should_attempt_close("hyperliquid"):
                    done.append({"action": act, "result": "backing off after "
                                 "escalation — see alarm"})
                    continue
                pos = (self.hl.state().get("positions") or [None])[0]
                if pos and abs(pos["szi"]) > 0:
                    # Adapter owns the close pricing (mark -> mid -> refuse), so
                    # this cannot drift from /hedge/close's version.
                    res = self._try_close(
                        "hyperliquid",
                        lambda: self.hl.flatten(pos["coin"]),
                        findings or [])
                    done.append({"action": act, "result": res})
                else:
                    done.append({"action": act, "result": "no position to close"})
            elif act["type"] == "close_leg" and act["venue"] == "dydx":
                if not self._should_attempt_close("dydx"):
                    done.append({"action": act, "result": "backing off after "
                                 "escalation — see alarm"})
                    continue
                pos = (self.dydx.state().get("positions") or [None])[0]
                if pos and abs(pos["size"]) > 0:
                    is_buy = pos["size"] < 0  # buy to close short, sell to close long
                    res = self._try_close(
                        "dydx",
                        lambda: _run_coro(self.dydx.place_market_reduce(
                            pos["coin"], is_buy, abs(pos["size"]))),
                        findings or [])
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
