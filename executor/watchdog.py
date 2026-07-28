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
  2. LIQUIDATION PROXIMITY — a leg has drifted close to its liquidation price. The
     fix is to shave BOTH legs equally, which moves the liquidation price away while
     keeping the position delta-neutral.

assess() is a pure function (no I/O) so the risk logic is unit-testable — as are the
reduce/rebalance size plans (plan_reduce, plan_rebalance). The loop reads live state,
assesses, and — only in 'active' mode — acts. Default mode is 'monitor' (report
only); acting is opt-in via config trading.watchdog.mode.

Nothing here is allowed to fail SILENTLY. Every critical finding raises an alarm even
when the watchdog cannot act on it, the alarm file is refreshed while the condition
holds (so a real alarm never ages into looking stale), and both are pushed off-box
via notify.py — because a log line, a temp file and a /health field all go quiet
together the moment the machine does.
"""

import asyncio
import concurrent.futures
import json
import logging
import math
import os
import tempfile
import time

from executor.notify import Notifier

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


def _base_coin(symbol):
    """Common key for the two venue symbols of one asset: HL 'BTC' and dYdX
    'BTC-USD' both normalize to 'BTC', so the two legs of a hedge line up."""
    return (symbol or "").split("-")[0].upper()


def _norm_leg(p, venue):
    """Normalize one adapter position dict to a leg. HL carries 'szi', dYdX
    'size' — both signed."""
    size = p.get("szi", p.get("size", 0)) or 0
    return {"open": abs(size) > 0, "size": size,
            "liq_distance_pct": p.get("liq_distance_pct"),
            "liq_note": p.get("liq_note"),
            "coin": p.get("coin"),  # venue-native symbol (HL 'BTC' / dYdX 'BTC-USD')
            "venue": venue}


_FLAT_LEG = {"open": False, "size": 0.0, "liq_distance_pct": None,
             "liq_note": None, "coin": None, "venue": None}


def _legs_by_coin(hl_state, dydx_state):
    """Group both venues' OPEN positions by base coin.

    Returns {base_coin: {"hyperliquid": leg|absent, "dydx": leg|absent}}. Only
    open legs are included, so a hedge with a missing leg surfaces as a coin
    present on one venue only — exactly the broken-hedge signal. A fully flat
    coin never appears. This is what lifts the watchdog past a single position:
    each asset is assessed against its own opposite leg, not positions[0].
    """
    out = {}
    for venue, state in (("hyperliquid", hl_state), ("dydx", dydx_state)):
        for p in (state.get("positions") or []):
            size = p.get("szi", p.get("size", 0)) or 0
            if abs(size) <= 0:
                continue
            out.setdefault(_base_coin(p.get("coin")), {})[venue] = _norm_leg(p, venue)
    return out


def _venue_readable(state):
    """Does this state actually carry a position list we are entitled to trust?

    A venue that could not be READ must never be mistaken for a venue holding
    NOTHING. dydx.state() used to return a dict with no "positions" key for any
    unexpected indexer reply (a 429, a 5xx, a degraded body), and
    `state.get("positions") or []` silently turned that into "flat" — so on
    2026-07-27 three fully-hedged coins were assessed as three BROKEN HEDGES and
    every Hyperliquid leg was flattened, stranding the dYdX longs unhedged for eight
    hours. Both adapters now raise instead (executor/errors.py), and this is the
    second line of defence: readable-and-empty is a list, unreadable is not.
    """
    return (isinstance(state, dict) and not state.get("unreadable")
            and isinstance(state.get("positions"), list))


_SEVERITY = {"none": 0, "ok": 1, "warn": 2, "critical": 3}


def _assess_pair(coin, a, b, *, liq_critical_pct=5.0, size_tolerance_pct=15.0):
    """Pure risk assessment of ONE asset's two legs. Findings/actions are tagged
    with `coin` (and the venue-native `symbol` on close actions) so the actor can
    flatten the exact position rather than positions[0]."""
    findings, actions = [], []

    # 1. Broken hedge — highest priority for this coin, short-circuits.
    if a["open"] != b["open"]:
        naked = "hyperliquid" if a["open"] else "dydx"
        symbol = a["coin"] if a["open"] else b["coin"]
        findings.append(
            f"{coin}: BROKEN HEDGE — only {naked} holds a position — naked"
            " directional")
        actions.append({"type": "close_leg", "venue": naked, "coin": coin,
                        "symbol": symbol, "reason": "broken_hedge"})
        return {"risk": "critical", "findings": findings, "actions": actions}

    if not a["open"] and not b["open"]:
        return {"risk": "none", "findings": [f"{coin}: flat"], "actions": []}

    # both legs open ------------------------------------------------------
    # 2. Delta neutrality: sizes should have opposite signs (when both known).
    if a["size"] is not None and b["size"] is not None:
        if (a["size"] > 0) == (b["size"] > 0):
            findings.append(f"{coin}: NOT DELTA-NEUTRAL — both legs same direction")
            actions.append({"type": "alert", "coin": coin,
                            "reason": "same_direction"})

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
                    f"{coin}/{venue}: liquidation distance UNKNOWN — risk params"
                    " unavailable; this leg is unmonitored")
                actions.append({"type": "alert", "coin": coin,
                                "reason": "liq_unknown", "venue": venue})
            continue
        if d < liq_critical_pct:
            findings.append(
                f"{coin}/{venue} is {d:.1f}% from liquidation"
                f" (< {liq_critical_pct}%)")
            actions.append({"type": "reduce_both", "coin": coin, "trigger": venue,
                            "reason": "near_liquidation"})

    # 4. Size imbalance (only when both sizes known).
    if a["size"] and b["size"]:
        hs, ds = abs(a["size"]), abs(b["size"])
        imb = abs(hs - ds) / max(hs, ds) * 100
        if imb > size_tolerance_pct:
            findings.append(
                f"{coin}: leg size imbalance {imb:.1f}% (> {size_tolerance_pct}%)")
            actions.append({"type": "rebalance", "coin": coin,
                            "reason": "size_imbalance"})

    critical = {"close_leg", "reduce_both"}
    risk = ("critical" if any(x["type"] in critical for x in actions)
            else "warn" if actions else "ok")
    return {"risk": risk,
            "findings": findings or [f"{coin}: both legs open and hedged"],
            "actions": actions}


def assess(hl, dydx, *, liq_critical_pct=5.0, size_tolerance_pct=15.0):
    """Pure risk assessment across EVERY open asset, not just positions[0].

    Groups both venues' positions by coin and assesses each asset's hedge
    independently, then aggregates: overall risk is the worst across assets and
    findings/actions from all of them are concatenated (each tagged with its
    coin). With a single hedged pair this returns exactly what the old
    single-position assess did (bar the coin prefix on strings).

    FAILS CLOSED on a blind read: if EITHER venue's positions cannot be trusted,
    this returns a critical alert and NO destructive action. Every conclusion here
    is comparative — "a leg is naked" means "the other venue does not have it" — so
    half the book supports no conclusion at all. Acting on half is precisely the
    2026-07-27 failure. A genuinely naked leg during an outage therefore gets
    alarmed rather than auto-closed; that is the deliberate trade, because the
    alarm is loud and off-box while a wrong close costs real money."""
    blind = [name for name, st in (("hyperliquid", hl), ("dydx", dydx))
             if not _venue_readable(st)]
    if blind:
        why = "; ".join(
            f"{name}: {(st.get('unreadable') if isinstance(st, dict) else None) or 'response carried no position list'}"
            for name, st in (("hyperliquid", hl), ("dydx", dydx))
            if name in blind)
        return {
            "risk": "critical",
            "findings": [
                f"POSITION STATE UNREADABLE on {', '.join(blind)} — the book is"
                f" UNGUARDED and no protective action can be trusted ({why})"],
            "actions": [{"type": "alert", "reason": "venue_unreadable",
                         "venue": name, "coin": None} for name in blind],
            "coins": [],
            "unreadable": blind,
        }
    by_coin = _legs_by_coin(hl, dydx)
    if not by_coin:
        return {"risk": "none", "findings": ["flat — both legs closed"],
                "actions": [], "coins": []}

    findings, actions, worst = [], [], "none"
    for coin in sorted(by_coin):
        legs = by_coin[coin]
        r = _assess_pair(coin, legs.get("hyperliquid", _FLAT_LEG),
                         legs.get("dydx", _FLAT_LEG),
                         liq_critical_pct=liq_critical_pct,
                         size_tolerance_pct=size_tolerance_pct)
        findings.extend(r["findings"])
        actions.extend(r["actions"])
        if _SEVERITY[r["risk"]] > _SEVERITY[worst]:
            worst = r["risk"]
    return {"risk": worst, "findings": findings, "actions": actions,
            "coins": sorted(by_coin)}


# --------------------------------------------------------------------------
# Size planning for the protective actions. Pure, for the same reason assess() is:
# these decide how much of a live position to sell, and that arithmetic must be
# testable without a venue.
# --------------------------------------------------------------------------

def floor_to_step(qty, step):
    """Largest multiple of `step` that is <= qty. `step` None/0 = no quantization.

    Floors rather than rounds: every size here is a ceiling (never reduce MORE than
    planned on one venue than the other). Binary floats make the naive version wrong
    — 0.0024/0.0001 is 23.999999999999996, which floors to 23 and silently loses a
    whole step — hence the epsilon, and the final re-round onto the step's own
    decimal grid so a venue never sees 0.30000000000000004.
    """
    q = max(0.0, float(qty or 0))
    if not step or float(step) <= 0:
        return q
    n = math.floor(q / float(step) + 1e-9)
    return round(n * float(step), 12) if n > 0 else 0.0


def plan_reduce(hl_size, dydx_size, fraction, step=None):
    """Pure: the EQUAL amount to shave off both legs of a hedge, quantized.

    Equal on both sides, or the de-risking itself creates naked delta — the exact
    failure this watchdog exists to prevent. Sized off the SMALLER leg so the shave
    can never exceed either position, and floored to the coarsest common step so both
    venues fill the same quantity (each rounds independently; see
    server._hedge_size_step).

    Returns 0.0 when no step-compliant shave exists (a position smaller than one
    step). That is not "do nothing" — the caller must escalate to a full close,
    because a leg near liquidation that cannot be trimmed still has to be dealt with.
    """
    hedged = min(abs(float(hl_size or 0)), abs(float(dydx_size or 0)))
    if hedged <= 0:
        return 0.0
    want = hedged * max(0.0, min(1.0, float(fraction)))
    return floor_to_step(min(want, hedged), step)


def plan_rebalance(hl_size, dydx_size, step=None):
    """Pure: (venue_to_trim, qty) that restores delta neutrality, or (None, 0.0).

    Always trims the LARGER leg toward the smaller one, never adds to the smaller.
    A reduce-only trim cannot increase exposure, so the worst case of acting on a
    stale read is a slightly smaller position that is still hedged; the worst case of
    'fixing' an imbalance by BUYING more of the small leg is more exposure, on a read
    that was already wrong.
    """
    h, d = abs(float(hl_size or 0)), abs(float(dydx_size or 0))
    if h <= 0 or d <= 0 or h == d:
        return None, 0.0
    venue = "hyperliquid" if h > d else "dydx"
    return venue, floor_to_step(abs(h - d), step)


class Watchdog:
    def __init__(self, hl_adapter, dydx_adapter, config, notifier=None):
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
        # Per-coin now: a broken BTC hedge and a healthy ETH open no longer share
        # one streak counter, so confirming one never resets the other.
        self._broken_streak = {}
        # Acting is not the same as fixing. _act used to fire a close, record the
        # venue's answer into a dict, and let run() throw it away — so a close that
        # never filled looked identical to one that worked, and the loop retried in
        # silence forever. On 2026-07-16 that ran for ~30min against an empty dYdX
        # testnet book while the console cheerfully logged "BROKEN HEDGE" as though
        # it were handling it. Count consecutive failures and get loud.
        self.escalate_after = int(w.get("escalate_after", 3))
        self.alarm_file = w.get("alarm_file") or os.path.join(
            tempfile.gettempdir(), "ainara_executor_watchdog_alarm.json")
        # Liveness heartbeat. The watchdog has no HTTP surface, so a supervisor
        # (the scheduler's managed-services layer) can only tell it is alive by a
        # file it freshens every loop. A silently-dead watchdog otherwise looks
        # exactly like a healthy quiet one — the very failure this guard exists to
        # avoid. Written every iteration, even when guard_once raises, because it
        # means "the loop is turning", not "the last assessment succeeded".
        self.heartbeat_file = w.get("heartbeat_file") or os.path.join(
            tempfile.gettempdir(), "ainara_executor_watchdog_heartbeat.txt")
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
        # --- liquidation-proximity response --------------------------------
        # assess() has flagged a leg inside liq_critical_pct as CRITICAL since the
        # liquidation math was wired, and emitted `reduce_both` — which _act dropped
        # into its "not_wired_yet" branch. So the single case where acting matters
        # MOST degraded to a logger.warning, and because no close was attempted it
        # never reached the escalation path either: no alarm file, nothing on
        # /health. Wired now: shave both legs equally (plan_reduce), which lifts the
        # liquidation price away while keeping the hedge delta-neutral.
        self.reduce_fraction = float(w.get("reduce_fraction", 0.5))
        # A shave does not necessarily leave the danger band, and dYdX state comes
        # from a lagging indexer. Without a cooldown a 5s loop would shave 50% six
        # times in thirty seconds and unwind the book by accident.
        self.reduce_cooldown_seconds = float(w.get("reduce_cooldown_seconds", 300))
        # Still inside the band after this many shaves means price is running away
        # from the hedge, not that the shave was too small. Stop trimming and close
        # the coin outright — no carry is worth riding into a liquidation.
        self.reduce_max_attempts = int(w.get("reduce_max_attempts", 3))
        self._reduce_at = {}
        self._reduce_attempts = {}
        self._rebalance_at = {}
        # Off-box alerting. Everything above escalates LOCALLY — a log line, the
        # alarm file, a /health field — and all three go quiet together when the box
        # sleeps, loses network, or the supervisor dies. See notify.py: push covers
        # "something is wrong", the dead-man heartbeat covers "the guard is gone",
        # which is the failure a local guard structurally cannot report.
        self.notifier = notifier if notifier is not None else Notifier(config)
        # Active alarm conditions, keyed stably so one ongoing problem stays ONE
        # entry: {key: {kind, severity, detail, since, origin, ...}}.
        self._risk_alarms = {}
        self._alarm_published = False

    def _debounce_broken_hedge(self, report):
        """Hold back each coin's broken-hedge close until its break persists.

        Only the broken-hedge close is debounced — it is the one that races a
        legitimate open. Liquidation proximity is real and is never delayed.
        Debounced PER COIN: a healthy (or flat) reading for one asset resets only
        that asset's streak, so a hedge that finishes opening is never touched
        while a genuinely naked leg on another asset still gets closed after
        confirm_polls * interval seconds.
        """
        if report.get("unreadable"):
            # Blind. A blind poll proves nothing about any streak, and standing down
            # here would clear a real close-retry alarm on the strength of a failed
            # read. Freeze all debounce/alarm state until we can see again.
            return report
        broken = [a for a in report["actions"]
                  if a["type"] == "close_leg" and a.get("reason") == "broken_hedge"]
        broken_coins = {a.get("coin") for a in broken}
        # Reset the streak for any coin no longer broken this poll.
        for coin in list(self._broken_streak):
            if coin not in broken_coins:
                self._broken_streak.pop(coin, None)
        if not broken:
            if self._close_attempts:
                # We were trying to flatten something and no longer need to —
                # either it worked or it was closed elsewhere. Stand down.
                logger.info("watchdog: no hedges broken — clearing alarm")
                self._clear_alarm()
            return report

        held = []
        for a in broken:
            coin = a.get("coin")
            self._broken_streak[coin] = self._broken_streak.get(coin, 0) + 1
            if self._broken_streak[coin] < self.confirm_polls:
                held.append(a)
        if held:
            report["actions"] = [a for a in report["actions"] if a not in held]
            report["debounced"] = {
                "held": "close_leg/broken_hedge",
                "streaks": {a.get("coin"): self._broken_streak[a.get("coin")]
                            for a in held},
                "confirm_polls": self.confirm_polls,
                "note": "break not confirmed yet (may be a hedge mid-open)",
            }
            logger.info(
                "watchdog: broken hedge held off for %s (confirm_polls=%s)",
                ", ".join(f"{a.get('coin')}={self._broken_streak[a.get('coin')]}"
                          for a in held), self.confirm_polls)
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

    # ---- alarms (recorded here, published once per poll) ------------------

    _ALARM_SEVERITY = {"info": 0, "warning": 1, "critical": 2}

    def _add_alarm(self, key, kind, severity, detail, origin="action", **extra):
        """Record/refresh one alarm condition. Publishing is _publish_alarms' job.

        Keyed so a condition that persists across polls stays a single entry with a
        stable `since` — the difference between "this has been broken for 40 minutes"
        and 480 indistinguishable alarms.
        """
        entry = self._risk_alarms.get(key)
        if entry is None:
            entry = {"key": key, "kind": kind, "since": time.time()}
            self._risk_alarms[key] = entry
            logger.error("WATCHDOG ALARM [%s] %s: %s", severity, kind, detail)
        entry.update({"severity": severity, "detail": detail, "origin": origin,
                      "ts": time.time(), **extra})
        return entry

    def _raise_alarm(self, venue, attempts, last_result, findings):
        """Escalate: a leg we are supposed to be protecting is not being fixed.

        The watchdog is the last line of defence, so when it cannot do its job the
        one unacceptable outcome is silence. Logs at ERROR, records an alarm the
        daemon surfaces on /health, and pushes off-box — so it outlives both the
        console scrollback and the machine.
        """
        logger.error(
            "WATCHDOG CANNOT FLATTEN %s AFTER %s ATTEMPTS — the leg is STILL OPEN "
            "and this loop is NOT fixing it. Intervene manually. Last venue "
            "response: %s", venue, attempts, last_result)
        self._add_alarm(
            f"cannot_flatten:{venue}", "watchdog_cannot_flatten", "critical",
            f"cannot flatten {venue} after {attempts} attempts — the leg is STILL"
            f" OPEN and the loop is not fixing it. Last venue response:"
            f" {str(last_result)[:300]}",
            venue=venue, attempts=attempts, last_result=str(last_result)[:500],
            findings=findings)

    def _sync_assessment_alarms(self, report):
        """Raise an alarm for every risk in the assessment — actionable or not.

        This is where the silence was. `reduce_both` (near liquidation) and `alert`
        (liquidation distance unknown, legs same-direction) never produced an order,
        so they never reached _record_close_attempt, so they never wrote the alarm
        file: a leg 4% from liquidation was visible ONLY to whoever happened to be
        tailing the log. Raising here decouples "can the watchdog fix it" from "does
        anyone find out", which were never the same question.

        Conditions that have cleared are dropped, so the alarm state always reflects
        THIS poll rather than accumulating history.
        """
        seen = set()
        for act in report.get("actions", []):
            coin, t, reason = act.get("coin"), act.get("type"), act.get("reason")
            venue = act.get("venue") or act.get("trigger")
            spec = None
            if t == "reduce_both":
                spec = (f"near_liquidation:{coin}", "near_liquidation", "critical",
                        f"{coin}: a leg is inside {self.liq_critical_pct}% of its"
                        f" liquidation price (trigger: {venue})")
            elif t == "close_leg" and reason == "broken_hedge":
                spec = (f"broken_hedge:{coin}", "broken_hedge", "critical",
                        f"{coin}: only {venue} holds a position — naked directional"
                        f" on leverage")
            elif t == "rebalance":
                spec = (f"size_imbalance:{coin}", "size_imbalance", "warning",
                        f"{coin}: leg sizes differ by more than"
                        f" {self.size_tolerance_pct}% — residual delta")
            elif t == "alert" and reason == "liq_unknown":
                spec = (f"liq_unknown:{coin}:{venue}", "liq_unknown", "warning",
                        f"{coin}/{venue}: liquidation distance UNKNOWN — this open"
                        f" leg is UNMONITORED")
            elif t == "alert" and reason == "same_direction":
                spec = (f"not_delta_neutral:{coin}", "not_delta_neutral", "critical",
                        f"{coin}: both legs point the SAME WAY — this is not a hedge")
            elif t == "alert" and reason == "venue_unreadable":
                spec = (f"venue_unreadable:{venue}", "venue_unreadable", "critical",
                        f"{venue}: position state UNREADABLE — the watchdog is BLIND"
                        f" and will take NO protective action until it clears. If a"
                        f" hedge breaks now, nothing will fix it automatically.")
            if spec:
                key, kind, severity, detail = spec
                seen.add(key)
                self._add_alarm(key, kind, severity, detail, origin="assessment",
                                coin=coin, venue=venue)
        if report.get("unreadable"):
            # Blind: `seen` holds only the venue_unreadable keys, so clearing here
            # would retire every REAL alarm — a leg near liquidation would be
            # "resolved" by the very outage that stopped us watching it. Add the
            # blindness alarm and change nothing else.
            return
        for key, a in list(self._risk_alarms.items()):
            if a.get("origin") == "assessment" and key not in seen:
                logger.info("watchdog: alarm cleared — %s", key)
                self._risk_alarms.pop(key, None)
                self.notifier.forget_event(key)
        self._clear_resolved_action_alarms(report, seen)

    def _clear_resolved_action_alarms(self, report, seen):
        """Retire the alarms and counters that belong to a risk that has passed.

        The alarms raised while ACTING (a refused shave, an exhausted shave budget)
        have no assessment action of their own to disappear, so nothing would ever
        clear them: one refused reduce would pin the alarm file open for the life of
        the process and the all-clear would never fire. They are owned by the
        underlying condition, so they retire with it.

        The per-coin shave counter resets the same way — a coin that leaves the band
        and re-enters an hour later is a NEW episode, and must not arrive with its
        budget already spent. The cooldown stamp deliberately survives: it is what
        bounds shaving to one per cooldown even if liq distance flaps across the
        threshold poll after poll.
        """
        for coin in report.get("coins") or []:
            if f"near_liquidation:{coin}" not in seen:
                if self._reduce_attempts.pop(coin, None):
                    logger.info("watchdog: %s left the liquidation band — shave"
                                " budget reset", coin)
                for key in (f"reduce_failed:{coin}", f"reduce_exhausted:{coin}"):
                    if self._risk_alarms.pop(key, None):
                        self.notifier.forget_event(key)
            if f"size_imbalance:{coin}" not in seen:
                if self._risk_alarms.pop(f"rebalance_failed:{coin}", None):
                    self.notifier.forget_event(f"rebalance_failed:{coin}")
        # A coin that has gone FLAT no longer appears in `coins` at all, so sweep any
        # leftover per-coin state for coins that are simply not there any more.
        live = set(report.get("coins") or [])
        for coin in [c for c in self._reduce_attempts if c not in live]:
            self._reduce_attempts.pop(coin, None)
        for key, a in list(self._risk_alarms.items()):
            if a.get("origin") == "action" and a.get("coin") \
                    and a["coin"] not in live:
                self._risk_alarms.pop(key, None)
                self.notifier.forget_event(key)

    def _alarm_payload(self, report):
        """The alarm file's contents. Keeps the original watchdog_cannot_flatten
        shape at the top level (server._watchdog_alarm and anything reading /health
        predate the multi-alarm rework) and adds the full list under `alarms`."""
        cf = next((a for a in self._risk_alarms.values()
                   if a["kind"] == "watchdog_cannot_flatten"), None)
        head = cf or max(
            self._risk_alarms.values(),
            key=lambda a: (self._ALARM_SEVERITY.get(a.get("severity"), 0),
                           -a["since"]))
        payload = {
            "alarm": head["kind"],
            "severity": head.get("severity"),
            "risk": report.get("risk"),
            "findings": report.get("findings"),
            "ts": time.time(),
            "alarms": sorted(self._risk_alarms.values(), key=lambda a: a["key"]),
        }
        if cf:
            payload.update({"venue": cf.get("venue"), "attempts": cf.get("attempts"),
                            "last_result": cf.get("last_result")})
        return payload

    def _write_alarm_file(self, payload):
        try:
            with open(self.alarm_file, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, default=str)
        except Exception as e:  # never let alarm plumbing kill the guard loop
            logger.error("watchdog: could not write alarm file %s: %s",
                         self.alarm_file, e)

    def _publish_alarms(self, report):
        """Refresh the alarm file and push off-box. Runs EVERY poll.

        Rewritten while any alarm is active rather than written once: server.py
        discards an alarm older than five minutes on the stated assumption that "a
        live watchdog rewrites it every poll", which was not true — so a real,
        ongoing alarm aged into looking stale, and /health started reporting a
        genuine emergency as historical noise.

        Pushes are throttled per alarm key (notify.send_event), so an ongoing
        condition nags on the repeat interval instead of 12 times a minute.
        """
        if self._risk_alarms:
            payload = self._alarm_payload(report)
            self._write_alarm_file(payload)
            report["alarm"] = payload
            for key, a in sorted(self._risk_alarms.items()):
                self.notifier.send_event(
                    key,
                    f"[{a.get('severity', 'critical').upper()}] Ainara watchdog:"
                    f" {a['kind']}",
                    (a.get("detail") or "") + (
                        f"\n\nrisk={report.get('risk')}"
                        f"\nfindings: {'; '.join(report.get('findings') or [])}"),
                    severity=a.get("severity", "critical"),
                    data={"key": key, "alarm": a["kind"],
                          "risk": report.get("risk"),
                          "findings": report.get("findings")})
        elif self._alarm_published:
            logger.info("watchdog: all alarm conditions cleared")
            self._remove_alarm_file()
            self.notifier.send(
                "[RESOLVED] Ainara watchdog: all clear",
                "Every alarm condition has cleared. Current risk:"
                f" {report.get('risk')}.", severity="info")
        self._alarm_published = bool(self._risk_alarms)

    def _remove_alarm_file(self):
        try:
            if os.path.exists(self.alarm_file):
                os.remove(self.alarm_file)
        except Exception as e:
            logger.warning("watchdog: could not clear alarm file: %s", e)

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
        """Healthy again — drop the close-retry state and its alarms.

        The FILE is not touched here: _publish_alarms owns it, and other conditions
        (a leg near liquidation, an unmonitored leg) may still be alarming even
        though nothing needs flattening any more."""
        self._close_attempts = {}
        self._escalated = set()
        self._next_attempt_at = {}
        for key in [k for k in self._risk_alarms if k.startswith("cannot_flatten:")]:
            self._risk_alarms.pop(key, None)
            self.notifier.forget_event(key)

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

    def _read_state(self, adapter, venue):
        """Read one venue's state, turning ANY failure into an explicit UNREADABLE
        marker rather than an empty book.

        Catches broadly on purpose. To a safety guard a rate limit, a 5xx, a DNS
        failure and a bug in the adapter all mean the same single thing — I do not
        know what this venue holds — and the one unacceptable response to not
        knowing is to proceed as though the answer were "nothing".
        """
        try:
            st = adapter.state()
        except Exception as e:
            logger.error("watchdog: %s state read FAILED (%s: %s) — treating as"
                         " UNREADABLE, not flat", venue, type(e).__name__, e)
            return {"venue": venue, "unreadable": f"{type(e).__name__}: {e}"}
        if not _venue_readable(st):
            logger.error("watchdog: %s state carries no position list — treating as"
                         " UNREADABLE, not flat", venue)
            return {**(st if isinstance(st, dict) else {}), "venue": venue,
                    "unreadable": "response carried no position list"}
        return st

    def guard_once(self):
        """Read both legs, assess, and (in active mode) act. Returns the report."""
        hl_state = self._read_state(self.hl, "hyperliquid")
        dydx_state = self._read_state(self.dydx, "dydx")
        report = assess(hl_state, dydx_state,
                        liq_critical_pct=self.liq_critical_pct,
                        size_tolerance_pct=self.size_tolerance_pct)
        if report["risk"] in ("warn", "critical"):
            logger.warning("watchdog risk=%s: %s", report["risk"],
                           "; ".join(report["findings"]))
        report = self._debounce_broken_hedge(report)
        # Alarm on what was FOUND, before (and regardless of) acting on it: in
        # monitor mode nothing is executed at all, and even in active mode some
        # findings have no order that fixes them.
        self._sync_assessment_alarms(report)
        if report["actions"] and self.mode == "active":
            report["executed"] = self._act(report["actions"], report["findings"])
        elif report["actions"]:
            report["executed"] = {"skipped": "mode=monitor (report only)"}
        if self._escalated:
            report["escalated"] = {"cannot_flatten": sorted(self._escalated),
                                   "attempts": dict(self._close_attempts)}
        # Last, so alarms raised while acting land in the same poll's file/push.
        self._publish_alarms(report)
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

    def _safe(self, fn, venue, what):
        """Run one venue call, turning a raise into a recorded failure.

        Deliberately does NOT touch the close-retry/escalation counters — those track
        flattening a naked leg. A reduce that fails is its own alarm; folding it into
        the flatten backoff would make one back the other off.
        """
        try:
            return fn()
        except Exception as e:
            logger.error("watchdog: %s on %s RAISED: %s", what, venue, e)
            return {"error": f"{type(e).__name__}: {e}"}

    def _legs_for(self, coin):
        """Fresh (hl_pos, dydx_pos) for one base coin, read straight from the venues.

        Re-read rather than reusing the assessment's snapshot: sizing an order is the
        one place a stale position is expensive, and a debounced action can be several
        polls old by the time it is released.
        """
        hl = next((p for p in (self.hl.state().get("positions") or [])
                   if _base_coin(p.get("coin")) == coin
                   and abs(p.get("szi") or 0) > 0), None)
        dy = next((p for p in (self.dydx.state().get("positions") or [])
                   if _base_coin(p.get("coin")) == coin
                   and abs(p.get("size") or 0) > 0), None)
        return hl, dy

    def _common_step(self, hl_symbol, dydx_symbol):
        """Coarsest size step across both venues, or None if unreadable.

        Mirrors server._hedge_size_step, which this cannot import: watchdog.py stays
        stdlib-only so its risk logic runs (and is tested) under any venv. None means
        "could not quantize" — a reduce still goes out, because an unquantized reduce
        risks one step of imbalance while skipping it risks the liquidation.
        """
        steps = []
        for adapter, symbol in ((self.hl, hl_symbol), (self.dydx, dydx_symbol)):
            try:
                s = adapter.size_increment(symbol)
            except Exception as e:
                logger.warning("watchdog: size_increment failed for %s: %s",
                               symbol, e)
                s = None
            if s:
                steps.append(float(s))
        return max(steps) if steps else None

    def _cooldown_left(self, stamps, coin, seconds):
        """Seconds until `coin` may be acted on again, or 0 if it is due now."""
        last = stamps.get(coin)
        if last is None:
            return 0.0
        left = seconds - (time.monotonic() - last)
        return round(left, 1) if left > 0 else 0.0

    def _reduce_leg(self, venue, pos, qty):
        """Send one reduce-only order: `qty` (None = the whole leg) off `pos`."""
        if venue == "hyperliquid":
            return self._safe(
                lambda: self.hl.reduce(pos["coin"], qty), venue, "reduce")
        size = abs(float(pos["size"])) if qty is None else qty
        is_buy = float(pos["size"]) < 0  # buy to reduce a short
        return self._safe(
            lambda: _run_coro(self.dydx.place_market_reduce(
                pos["coin"], is_buy, size)), venue, "reduce")

    def _reduce_both(self, act, findings):
        """De-risk a hedge whose leg is near liquidation, keeping it delta-neutral.

        Shaves an EQUAL, step-quantized amount off both legs — reducing notional
        moves the liquidation price away, and doing it symmetrically means the
        de-risking never creates the naked delta this whole loop exists to prevent.
        The threatened venue goes first: if the second leg then fails, the position is
        imbalanced (which the rebalance action fixes) rather than still one bad tick
        from a liquidation.
        """
        coin = act.get("coin")
        left = self._cooldown_left(self._reduce_at, coin,
                                   self.reduce_cooldown_seconds)
        if left:
            return {"skipped": "cooldown", "seconds_remaining": left,
                    "note": "a shave is already in flight or just settled"}
        hl_pos, dy_pos = self._legs_for(coin)
        if not hl_pos or not dy_pos:
            return {"skipped": "not a two-leg hedge — the broken-hedge path owns"
                                " this coin"}
        attempts = self._reduce_attempts.get(coin, 0)
        step = self._common_step(hl_pos.get("coin"), dy_pos.get("coin"))
        qty = plan_reduce(hl_pos.get("szi"), dy_pos.get("size"),
                          self.reduce_fraction, step)
        plan = "reduce"
        if attempts >= self.reduce_max_attempts:
            # Shaved this coin repeatedly and it is STILL in the band: price is
            # running, not mis-sized. Close it rather than salami-slice into a
            # liquidation.
            plan, qty = "close_hedge", None
            self._add_alarm(
                f"reduce_exhausted:{coin}", "reduce_exhausted", "critical",
                f"{coin}: still near liquidation after {attempts} shaves — closing"
                f" BOTH legs instead of reducing again", coin=coin)
        elif qty <= 0:
            # Smaller than one tradable step: a partial shave is not expressible, so
            # the only real options are close it or leave it in the band.
            plan, qty = "close_hedge", None

        order = ["hyperliquid", "dydx"]
        if act.get("trigger") == "dydx":
            order.reverse()  # de-risk the threatened venue first
        positions = {"hyperliquid": hl_pos, "dydx": dy_pos}
        results = {}
        for venue in order:
            results[venue] = self._reduce_leg(venue, positions[venue], qty)
        self._reduce_at[coin] = time.monotonic()
        self._reduce_attempts[coin] = attempts + 1

        failed = sorted(v for v, r in results.items() if self._close_failed(r))
        out = {"plan": plan, "qty": qty, "size_step": step, "sequence": order,
               "attempt": attempts + 1, "results": results}
        if failed:
            out["failed"] = failed
            self._add_alarm(
                f"reduce_failed:{coin}", "reduce_failed", "critical",
                f"{coin}: {plan} REFUSED on {', '.join(failed)} — the leg is still"
                f" near liquidation at full size", coin=coin,
                results={k: str(v)[:200] for k, v in results.items()})
        else:
            logger.warning("watchdog: %s %s qty=%s sent (attempt %s)", coin, plan,
                           qty, attempts + 1)
            self.notifier.send_event(
                f"acted:reduce:{coin}:{attempts + 1}",
                f"[ACTION] Ainara watchdog: {plan} on {coin}",
                f"{coin} is near liquidation; sent {plan}"
                f"{'' if qty is None else f' of {qty} per leg'} across both venues"
                f" (attempt {attempts + 1}/{self.reduce_max_attempts}).",
                severity="critical", data=out)
        return out

    def _rebalance(self, act, findings):
        """Trim the LARGER leg back to the smaller one, restoring delta neutrality.

        Reduce-only and one-sided by construction: it can only ever shrink exposure,
        so acting on a stale or lagging read costs a slightly smaller hedge instead of
        a bigger one.
        """
        coin = act.get("coin")
        left = self._cooldown_left(self._rebalance_at, coin,
                                   self.reduce_cooldown_seconds)
        if left:
            return {"skipped": "cooldown", "seconds_remaining": left,
                    "note": "dYdX state lags; re-trimming now would over-trim"}
        hl_pos, dy_pos = self._legs_for(coin)
        if not hl_pos or not dy_pos:
            return {"skipped": "not a two-leg hedge — the broken-hedge path owns"
                                " this coin"}
        step = self._common_step(hl_pos.get("coin"), dy_pos.get("coin"))
        venue, qty = plan_rebalance(hl_pos.get("szi"), dy_pos.get("size"), step)
        if not venue or qty <= 0:
            return {"skipped": "imbalance is under one size step — trimming cannot"
                                " fix it", "size_step": step}
        pos = hl_pos if venue == "hyperliquid" else dy_pos
        res = self._reduce_leg(venue, pos, qty)
        self._rebalance_at[coin] = time.monotonic()
        out = {"plan": "trim", "venue": venue, "qty": qty, "size_step": step,
               "result": res}
        if self._close_failed(res):
            out["failed"] = [venue]
            self._add_alarm(
                f"rebalance_failed:{coin}", "rebalance_failed", "critical",
                f"{coin}: trim of {qty} REFUSED on {venue} — residual delta stands",
                coin=coin, venue=venue)
        else:
            logger.warning("watchdog: %s trim %s on %s sent", coin, qty, venue)
            self.notifier.send_event(
                f"acted:trim:{coin}", f"[ACTION] Ainara watchdog: trim {coin}",
                f"Trimmed {qty} off the larger {venue} leg to restore delta"
                f" neutrality on {coin}.", severity="warning", data=out)
        return out

    def _act(self, actions, findings=None):
        """Execute protective actions:
          close_leg    — flatten the exposed leg with a reduce-only crossing order
          reduce_both  — shave both legs equally (near liquidation)
          rebalance    — trim the larger leg back to the smaller (residual delta)
          alert        — nothing to send; _sync_assessment_alarms already raised it

        Every close is recorded and counted: sending an order is not the same as
        flattening a position, and a leg that is still open on the next poll means
        this did NOT work — however cleanly the venue accepted it.
        """
        done = []
        for act in actions:
            if act["type"] == "close_leg" and act["venue"] == "hyperliquid":
                # Key retry/escalation state per (venue, coin) so backing off on
                # one stuck asset never silences another's protective close.
                key = f"hyperliquid:{act.get('coin')}"
                if not self._should_attempt_close(key):
                    done.append({"action": act, "result": "backing off after "
                                 "escalation — see alarm"})
                    continue
                # Flatten the EXACT position named by the action, not positions[0]
                # — with several open coins [0] could be the wrong (healthy) one.
                symbol = act.get("symbol")
                pos = next((p for p in (self.hl.state().get("positions") or [])
                            if p.get("coin") == symbol and abs(p["szi"]) > 0), None)
                if pos:
                    # Adapter owns the close pricing (mark -> mid -> refuse), so
                    # this cannot drift from /hedge/close's version.
                    res = self._try_close(
                        key,
                        lambda p=pos: self.hl.flatten(p["coin"]),
                        findings or [])
                    done.append({"action": act, "result": res})
                else:
                    done.append({"action": act, "result": "no position to close"})
            elif act["type"] == "close_leg" and act["venue"] == "dydx":
                key = f"dydx:{act.get('coin')}"
                if not self._should_attempt_close(key):
                    done.append({"action": act, "result": "backing off after "
                                 "escalation — see alarm"})
                    continue
                symbol = act.get("symbol")
                pos = next((p for p in (self.dydx.state().get("positions") or [])
                            if p.get("coin") == symbol and abs(p["size"]) > 0), None)
                if pos:
                    is_buy = pos["size"] < 0  # buy to close short, sell to close long
                    res = self._try_close(
                        key,
                        lambda p=pos: _run_coro(self.dydx.place_market_reduce(
                            p["coin"], is_buy, abs(p["size"]))),
                        findings or [])
                    done.append({"action": act, "result": res})
                else:
                    done.append({"action": act, "result": "no position to close"})
            elif act["type"] == "reduce_both":
                done.append({"action": act,
                             "result": self._reduce_both(act, findings or [])})
            elif act["type"] == "rebalance":
                done.append({"action": act,
                             "result": self._rebalance(act, findings or [])})
            elif act["type"] == "alert":
                # Nothing to send — but never silent: the alarm is already raised and
                # published, which is the entire remedy for an alert.
                done.append({"action": act, "result": "alarm raised"})
            else:
                done.append({"action": act, "result": "not_wired_yet"})
        return done

    def _write_heartbeat(self):
        """Freshen the LOCAL liveness file. Best-effort — heartbeat IO must never be
        able to kill the guard loop.

        Means "the loop is turning", not "the last assessment succeeded" — the
        supervisor uses it to decide restarts, and restarting on a venue-API blip
        would throw away the retry/backoff state for no gain. The off-box dead-man
        ping is the opposite: see run().
        """
        try:
            with open(self.heartbeat_file, "w", encoding="utf-8") as fh:
                fh.write(str(time.time()))
        except Exception as e:
            logger.warning("watchdog: could not write heartbeat %s: %s",
                           self.heartbeat_file, e)

    def run(self):
        logger.info("watchdog starting: mode=%s interval=%ss heartbeat=%s",
                    self.mode, self.interval, self.heartbeat_file)
        logger.info("watchdog: %s", self.notifier.describe())
        # Send one on startup: it confirms the channel actually works, which you want
        # to learn now rather than during the first emergency.
        self.notifier.send(
            "Ainara watchdog: started",
            f"mode={self.mode}, poll={self.interval}s,"
            f" liq_critical={self.liq_critical_pct}%,"
            f" reduce={self.reduce_fraction:.0%} per shave.", severity="info")
        self.notifier.heartbeat(force=True)
        while True:
            ok, report = True, None
            try:
                report = self.guard_once()
            except Exception as e:  # never let the guard die silently
                ok = False
                logger.error("watchdog loop error: %s", e)
                # A loop that cannot ASSESS is a loop that is not guarding, and the
                # local heartbeat below still reads healthy — so this push, and the
                # withheld dead-man ping, are the only signals that say so.
                self.notifier.send_event(
                    "guard_loop_error",
                    "[CRITICAL] Ainara watchdog: guard loop failing",
                    f"guard_once raised {type(e).__name__}: {e}. The position is"
                    f" UNGUARDED until this clears.")
            self._write_heartbeat()  # after guard, so it reflects a live loop
            # Only ping the dead-man switch after an assessment that actually SAW
            # both venues. Pinging unconditionally would tell the external monitor
            # "all good" while the loop spins blind against a dead venue API —
            # turning the one check that survives this machine into a rubber stamp.
            # A blind loop is a loop that is not guarding, so it withholds the ping
            # exactly like a crashed one: silence is the alarm.
            if ok and not (report or {}).get("unreadable"):
                self.notifier.heartbeat()
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
    if not wd.notifier.enabled:
        logger.warning(
            "no off-box alerting configured (trading.notify.webhook_url /"
            " heartbeat_url) — every alarm this loop raises stays on THIS machine."
            " If it sleeps, drops its network or dies, silence will be"
            " indistinguishable from a healthy book.")
    elif not wd.notifier.deadman_enabled:
        logger.warning(
            "trading.notify.heartbeat_url is unset — alerts can be pushed, but"
            " nothing off-box will notice if this watchdog DIES. A local guard"
            " cannot report its own death.")
    try:
        wd.run()
    except KeyboardInterrupt:
        logger.info("watchdog stopped")


if __name__ == "__main__":
    main()
