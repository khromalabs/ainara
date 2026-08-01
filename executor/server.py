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

"""HTTP surface for the trading executor daemon.

Orakle-side skills drive execution through these endpoints. The daemon binds to
localhost only — it is never exposed. Adapters mix sync (HL SDK) and async (dYdX
node) calls; _resolve() normalizes both.

Safety: POST /venues/<v>/order defaults dry_run=True. A caller must send
dry_run=false explicitly to reach the venue, and even then the adapter's
compliance gate applies (mainnet needs jurisdiction ack). Every order/cancel
request is logged.
"""

import asyncio
import inspect
import json
import logging
import math
import os
import re
import tempfile
import time

from flask import Flask, jsonify, request

from executor.config import ExecutorConfig
from executor.notify import Notifier
from executor.venues.dydx import DydxExecutor
from executor.venues.hyperliquid import HyperliquidExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("executor.server")


class QuietHealthProbes(logging.Filter):
    """Drop werkzeug's access line for SUCCESSFUL /health probes.

    The scheduler polls /health every 10 seconds. That was ~700 KB/day of
    `"GET /health HTTP/1.1" 200` in the one log whose reason for existing is telling
    you what happened to your orders — and a log you have to page past is a log you
    stop reading.

    Successful probes ONLY. A /health that returns non-200 means the daemon is
    failing its own liveness check, which is exactly the line you want to find
    later, so those are kept. Every other path is untouched.
    """

    # Anchored on the space (or query string) after /health, so a future /healthz or
    # /healthcheck route is NOT silently swallowed by this filter.
    _OK_HEALTH = re.compile(r'"GET /health(?:\?[^"]*)? [^"]*" 2\d\d')

    def filter(self, record):
        try:
            return not self._OK_HEALTH.search(record.getMessage())
        except Exception:
            return True  # never let log filtering swallow a real line


# Attached at import, not in main(), so it applies however the app is launched.
logging.getLogger("werkzeug").addFilter(QuietHealthProbes())

app = Flask(__name__)
config = ExecutorConfig()
VENUES = {"hyperliquid": HyperliquidExecutor, "dydx": DydxExecutor}


def _resolve(value):
    """Run a coroutine to completion if needed; pass through plain values."""
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _venue(name):
    cls = VENUES.get(name)
    return cls(config) if cls else None


_NOTIFIER = None


def _notifier():
    """Lazily-built shared Notifier. Reads the same trading.notify config as the
    watchdog, so both channels are configured in one place."""
    global _NOTIFIER
    if _NOTIFIER is None:
        _NOTIFIER = Notifier(config)
    return _NOTIFIER


def _margin_cap_notional():
    """Max notional per leg allowed by the margin rule, from BOTH live balances.
    None if the rule isn't configured or balances can't be read.

    Uses EQUITY (account value), not free collateral: equity is stable as the two
    legs open, so the cap doesn't tighten after leg 1 and wrongly refuse leg 2
    (which would strand a naked leg). When flat, equity == free collateral, so it
    matches the carry engine's sizing.
    """
    pct = config.get("trading.max_account_margin_pct")
    if pct is None:
        return None
    try:
        hl_eq = _venue("hyperliquid").state().get("perp_account_value")
        dy_eq = _resolve(_venue("dydx").state()).get("equity")
        if hl_eq is None or dy_eq is None:
            return None
        leverage = float(config.get("trading.carry_engine.leverage", 3.0))
        return float(pct) / 100.0 * min(float(hl_eq), float(dy_eq)) * leverage
    except Exception as e:
        logger.warning("margin-cap read failed: %s", e)
        return None


def _watchdog_alarm():
    """The position watchdog's alarm, if it has raised one.

    The watchdog is a separate process, so it escalates through a file rather than
    shared memory. Surfacing it here means "the watchdog cannot flatten a leg" is
    something you can QUERY, instead of a line that scrolled off a console an hour
    ago. Stale alarms (>5min) are ignored: a live watchdog rewrites it every poll.
    """
    path = (config.get("trading.watchdog.alarm_file")
            or os.path.join(tempfile.gettempdir(),
                            "ainara_executor_watchdog_alarm.json"))
    try:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            alarm = json.load(fh)
        if time.time() - float(alarm.get("ts", 0)) > 300:
            return {**alarm, "stale": True}
        return alarm
    except Exception as e:
        logger.warning("could not read watchdog alarm file: %s", e)
        return None


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        venues=list(VENUES),
        jurisdiction_acknowledged=config.jurisdiction_acknowledged(),
        watchdog_alarm=_watchdog_alarm(),
    )


@app.get("/venues/<name>/validate")
def validate(name):
    v = _venue(name)
    if not v:
        return jsonify(error=f"unknown venue '{name}'"), 404
    return jsonify(_resolve(v.validate()))


@app.get("/venues/<name>/state")
def state(name):
    v = _venue(name)
    if not v:
        return jsonify(error=f"unknown venue '{name}'"), 404
    return jsonify(_resolve(v.state()))


@app.get("/venues/<name>/orders")
def orders(name):
    v = _venue(name)
    if not v:
        return jsonify(error=f"unknown venue '{name}'"), 404
    if not hasattr(v, "open_orders"):
        return jsonify(error=f"{name} open_orders not implemented"), 501
    return jsonify(_resolve(v.open_orders()))


@app.post("/venues/<name>/order")
def order(name):
    v = _venue(name)
    if not v:
        return jsonify(error=f"unknown venue '{name}'"), 404
    body = request.get_json(force=True, silent=True) or {}
    # Default SAFE: only an explicit dry_run == false can reach the venue.
    dry_run = body.get("dry_run", True) is not False
    symbol = body.get("symbol")
    is_buy = bool(body.get("is_buy"))
    size = body.get("size")
    price = body.get("price")
    reduce_only = bool(body.get("reduce_only", False))
    if not symbol or size is None or price is None:
        return jsonify(error="symbol, size and price are required"), 400
    # Deterministic margin backstop: refuse any OPENING order above the margin rule,
    # regardless of what the carry engine sized or the LLM agent requested. Closes
    # are never capped.
    if not reduce_only:
        mcap = _margin_cap_notional()
        notional = float(size) * float(price)
        if mcap is not None and notional > mcap:
            logger.info("ORDER REFUSED (margin cap): %s notional=%.2f cap=%.2f",
                        name, notional, mcap)
            return jsonify({
                "submitted": False,
                "order": {"venue": name, "symbol": symbol, "size": size,
                          "price": price, "reduce_only": reduce_only},
                "gate": {
                    "refused": "order_exceeds_margin_cap",
                    "detail": (f"notional ${notional:,.2f} exceeds the margin-rule "
                               f"cap ${mcap:,.2f} (trading.max_account_margin_pct)."),
                },
            })
    logger.info(
        "ORDER %s %s %s size=%s px=%s reduce_only=%s dry_run=%s",
        name, symbol, "buy" if is_buy else "sell", size, price, reduce_only, dry_run,
    )
    if name == "hyperliquid":
        result = v.place_order(symbol, is_buy, float(size), float(price),
                               reduce_only=reduce_only, dry_run=dry_run)
    else:
        result = _resolve(v.place_order(symbol, is_buy, float(size), float(price),
                                        reduce_only=reduce_only, dry_run=dry_run))
    return jsonify(result)


@app.post("/venues/<name>/cancel")
def cancel(name):
    v = _venue(name)
    if not v:
        return jsonify(error=f"unknown venue '{name}'"), 404
    if not hasattr(v, "cancel_order"):
        return jsonify(error=f"{name} cancel not implemented"), 501
    body = request.get_json(force=True, silent=True) or {}
    symbol = body.get("symbol")
    if not symbol:
        return jsonify(error="symbol is required"), 400
    if name == "dydx":
        # dYdX stateful cancel needs the client_id + good_til_block_time from place
        cid, gtbt = body.get("client_id"), body.get("good_til_block_time")
        if cid is None or gtbt is None:
            return jsonify(error="dydx cancel needs client_id and "
                                 "good_til_block_time"), 400
        logger.info("CANCEL dydx %s client_id=%s", symbol, cid)
        return jsonify(result=_resolve(v.cancel_order(symbol, cid, gtbt)))
    oid = body.get("oid")
    if oid is None:
        return jsonify(error="oid is required"), 400
    logger.info("CANCEL %s %s oid=%s", name, symbol, oid)
    return jsonify(result=_resolve(v.cancel_order(symbol, oid)))


# ---- deterministic two-leg hedge open ----------------------------------------
#
# The carry engine's verdict is already a complete instruction (venues, symbols,
# size, ref_price), so opening the hedge needs no judgement — only correct
# sequencing and an unwind that always runs. Keeping it here, in the process that
# owns the SDKs and the gates, means the unwind cannot be lost to a dead caller.


def _hedge_size_step(short_venue, short_symbol, long_venue, long_symbol):
    """Coarsest size increment across both venues, or None if unreadable.

    The venues quantize differently — dYdX BTC-USD steps 0.0001, Hyperliquid BTC
    0.00001 — and each silently rounds whatever we send. Sending one size to both
    therefore fills two DIFFERENT sizes, and the difference is unhedged
    directional exposure. Quantizing to the coarsest step first makes both legs
    exactly equal.

    The error is bounded by one step regardless of position size, so it hurts
    proportionally more the smaller you trade: at $60/leg it was ~3.2% of the
    position (~$1.94 naked), against an expected edge of ~$0.20 over a two-week
    hold — noise larger than the signal.
    """
    steps = []
    for venue, symbol in ((short_venue, short_symbol), (long_venue, long_symbol)):
        try:
            s = _venue(venue).size_increment(symbol)
        except Exception as e:
            logger.warning("size_increment failed for %s/%s: %s", venue, symbol, e)
            s = None
        if s:
            steps.append(float(s))
    return max(steps) if steps else None


def _hedge_price_tick(short_venue, short_symbol, long_venue, long_symbol,
                      ref_price):
    """Coarsest PRICE tick across both venues, or None if unreadable.

    Same idea as _hedge_size_step but for price: the sell goes to one venue and
    the buy to the other, so a single crossing price must be valid on both. Venue
    ticks are decimal-nested, so a multiple of the COARSER tick is also a valid
    multiple of the finer — round both legs to the coarser and both venues accept
    them. None -> plan_hedge_legs falls back to its $1 default (fine for majors,
    refuses sub-$1). HL's tick depends on the price, hence ref_price."""
    ticks = []
    for venue, symbol in ((short_venue, short_symbol), (long_venue, long_symbol)):
        try:
            t = _venue(venue).price_tick(symbol, ref_price)
        except Exception as e:
            logger.warning("price_tick failed for %s/%s: %s", venue, symbol, e)
            t = None
        if t:
            ticks.append(float(t))
    return max(ticks) if ticks else None


def _tick_decimals(tick):
    """Decimal places implied by a price tick (0.001 -> 3, 1 -> 0).

    Used only to strip the float-division fuzz that math.floor(x/tick)*tick
    leaves behind. Assumes decimal ticks (powers of ten), which is what both
    venues use for these markets (dYdX tickSize, HL's sig-fig grid)."""
    s = ("%.12f" % float(tick)).rstrip("0")
    return len(s.split(".")[1]) if ("." in s and not s.endswith(".")) else 0


def plan_hedge_legs(short_symbol, long_symbol, size, ref_price, cross_pct,
                    cap_notional=None, size_step=None, price_tick=1.0):
    """Pure: build the two crossing limit orders for a delta-neutral open.

    A taker fill needs the limit to cross the book — sell BELOW ref, buy ABOVE.
    (The carry engine prices its edge with taker fees, so both legs must cross;
    resting at/inside ref would quietly turn the open into a maker order that may
    never fill and leave the hedge half-built.)

    `cap_notional` is the binding per-leg ceiling (the tighter of the hard cap and
    the margin rule). The size is floored so the WORSE-priced leg — the buy, which
    crosses up — still fits it. Both legs keep the same size, so shaving cannot
    break delta-neutrality, and the size can only ever shrink.

    Sizing to a cap exactly is what broke run 331efb33: the engine's size was
    within the cap at ref but over it once the buy leg crossed up, so the venue
    refused the long AFTER the short had already filled.

    Prices are rounded to `price_tick`, but DIRECTIONALLY — floor the sell, ceil
    the buy — so rounding always keeps each leg on its crossing side. Nearest
    round() breaks on lower-priced majors: SOL at ref ~74.25 rounds BOTH legs to
    74, and a buy limit of 74 sits BELOW the market, so the long rests and never
    fills (that half-built the SOL hedge on run f160529d, then unwound). The
    0.05% cross is only ~$0.04 at SOL's price — smaller than a $1 tick — so the
    tick, not the cross, must decide the side. floor/ceil guarantee sell <= ref <
    buy.

    `price_tick` defaults to 1.0 (whole dollars — the original behaviour, correct
    for BTC/ETH/SOL). Pass the actual venue price tick to support any asset: a
    $1 tick floors a sub-$1 sell to zero and cannot express a crossing limit,
    which is why cheap tokens were refused. Use the COARSER of the two venues'
    ticks so a single rounded price is valid on both legs (venue ticks are
    decimal-nested, so a multiple of the coarser tick is also a multiple of the
    finer). The crossing price is a worst-case CAP that fills at the book, so a
    coarser tick costs nothing.
    """
    size = float(size)
    ref_price = float(ref_price)
    cross = float(cross_pct) / 100.0
    if size <= 0:
        raise ValueError("size must be > 0")
    if ref_price <= 0:
        raise ValueError("ref_price must be > 0")

    tick = float(price_tick)
    if tick <= 0:
        raise ValueError(f"price_tick must be > 0 (got {price_tick})")
    dec = _tick_decimals(tick)
    # Round each leg to the venue price tick, DIRECTIONALLY: floor the sell, ceil
    # the buy, so rounding can only keep a leg on its crossing side.
    sell_px = round(math.floor(ref_price * (1 - cross) / tick) * tick, dec)
    buy_px = round(math.ceil(ref_price * (1 + cross) / tick) * tick, dec)
    # Defensive: a zero cross, or a ref sitting exactly on the grid, could leave a
    # leg on the wrong side of ref. Nudge it one tick so the cross is guaranteed.
    if sell_px >= ref_price:
        sell_px = round(sell_px - tick, dec)
    if buy_px <= ref_price:
        buy_px = round(buy_px + tick, dec)
    # If the tick is too coarse to express a crossing sell above zero (e.g. a $1
    # tick on a sub-$1 asset), refuse rather than send a zero or non-crossing
    # price — the caller must supply the real, finer venue tick.
    if sell_px <= 0 or sell_px >= buy_px:
        raise ValueError(
            f"cannot build crossing limits at ref ${ref_price:,.6f} with price"
            f" tick {tick} (sell={sell_px}, buy={buy_px}); tick too coarse for"
            " this asset — pass the real venue price tick")

    shaved = None
    if cap_notional is not None:
        cap_notional = float(cap_notional)
        worst_px = max(sell_px, buy_px)
        if size * worst_px > cap_notional:
            fitted = math.floor(cap_notional / worst_px * 1e6) / 1e6
            if fitted <= 0:
                raise ValueError(
                    f"cap ${cap_notional:,.2f} is too small for one unit at "
                    f"${worst_px:,.0f}"
                )
            shaved = {"requested_size": size, "capped_size": fitted,
                      "cap_notional": cap_notional,
                      "reason": "size floored to fit the per-leg notional cap "
                                "at the crossing price"}
            size = fitted

    # Quantize LAST, to the coarsest venue step: both legs must be a size each
    # venue can express exactly, or they fill different amounts and the residual
    # is naked delta. Flooring here keeps us under any cap applied above.
    quantized = None
    if size_step:
        size_step = float(size_step)
        stepped = math.floor(size / size_step) * size_step
        # Re-round: float division leaves 0.00089999... artefacts that would then
        # be truncated by the venue anyway.
        stepped = round(stepped, 10)
        if stepped <= 0:
            raise ValueError(
                f"size {size} is smaller than one venue step ({size_step}); "
                "increase capital or the notional cap"
            )
        if stepped != size:
            quantized = {"pre_quantize_size": size, "size_step": size_step,
                         "reason": "size floored to the coarsest venue step so "
                                   "both legs fill exactly equal"}
        size = stepped

    return {
        "short": {"symbol": short_symbol, "is_buy": False,
                  "price": sell_px, "size": size},
        "long": {"symbol": long_symbol, "is_buy": True,
                 "price": buy_px, "size": size},
        "shaved": shaved,
        "quantized": quantized,
    }


def _effective_cap_notional():
    """The binding per-leg notional ceiling: tighter of hard cap and margin rule.

    /venues/<v>/order applies the margin backstop in the route, but the hedge
    opener calls the adapters directly — so it must apply the same rule here or
    the two-leg path would silently be the weaker gate. None = uncapped.
    """
    caps = []
    hard = config.get("trading.executor.max_order_notional_usd")
    if hard is not None:
        caps.append(float(hard))
    margin = _margin_cap_notional()
    if margin is not None:
        caps.append(float(margin))
    return min(caps) if caps else None


def _leg_refused(res):
    """True when the adapter refused a leg outright (gate/cap/error).

    A refusal is final — there is nothing to wait for. Polling for a fill that
    can never arrive just holds the other leg naked for the timeout, which is how
    run 331efb33 sat exposed for 13s until the watchdog stepped in.
    """
    if not isinstance(res, dict):
        return False
    return bool(res.get("gate")) or res.get("submitted") is False \
        or bool(res.get("error"))


def _signed_position(venue_name, symbol):
    """Signed position size for `symbol` on `venue_name`; 0.0 when flat.

    HL reports it as 'szi', dYdX as 'size' — both signed, both keyed by 'coin'.
    """
    st = _resolve(_venue(venue_name).state())
    for p in st.get("positions") or []:
        if p.get("coin") == symbol:
            return float(p.get("szi", p.get("size", 0)) or 0)
    return 0.0


def _await_position(venue_name, symbol, want_buy, timeout_s, poll_s=1.0):
    """Poll until a position with the expected direction appears. 0.0 on timeout.

    Position state is the ground truth: HL's place_order reports submitted=True
    once the request goes out, which says nothing about whether the venue
    accepted or filled it.
    """
    deadline = time.monotonic() + float(timeout_s)
    while True:
        sz = _signed_position(venue_name, symbol)
        if sz and (sz > 0) == bool(want_buy):
            return sz
        if time.monotonic() >= deadline:
            return 0.0
        time.sleep(poll_s)


def _place_leg(venue_name, leg):
    """Submit one opening leg live. Returns the adapter's raw result."""
    v = _venue(venue_name)
    if venue_name == "hyperliquid":
        # Ioc: fills what it can and cancels the rest, so there is never an
        # unknown resting remainder to reconcile.
        return v.place_order(leg["symbol"], leg["is_buy"], leg["size"],
                             leg["price"], reduce_only=False, tif="Ioc",
                             dry_run=False)
    return _resolve(v.place_order(leg["symbol"], leg["is_buy"], leg["size"],
                                  leg["price"], reduce_only=False,
                                  dry_run=False))


def _close_leg(venue_name, symbol):
    """Flatten `symbol` with a reduce-only crossing order. Mirrors watchdog._act.

    Closes are never margin-capped — reducing exposure must always be allowed.
    """
    v = _venue(venue_name)
    if venue_name == "hyperliquid":
        # Pricing lives in the adapter so this and watchdog._act cannot drift.
        return v.flatten(symbol)
    pos = next((p for p in (_resolve(v.state()).get("positions") or [])
                if p.get("coin") == symbol), None)
    if not pos or not abs(float(pos["size"])):
        return {"closed": True, "note": "no position to close"}
    is_buy = float(pos["size"]) < 0
    return _resolve(v.place_market_reduce(symbol, is_buy,
                                          abs(float(pos["size"]))))


def _cancel_resting(venue_name, symbol, leg_res):
    """Cancel a leg's order if the open left one RESTING on the book.

    Hyperliquid opens with Ioc, so it never rests — only dYdX's LONG_TERM open leg
    does, and its place result carries the client_id + good_til_block_time that
    cancel_order needs. Returns the cancel result, or None when there is nothing to
    cancel: an Ioc leg, or a refused leg that never reached the book (neither
    carries those handles).

    This closes the gap that left an unpaired dYdX long on 2026-07-22: a timed-out
    open whose short was unwound while its dYdX buy sat resting, then filled minutes
    later. Abandoning a leg is not the same as cancelling it — a stateful order
    outlives the request that placed it.
    """
    if not isinstance(leg_res, dict):
        return None
    client_id = leg_res.get("client_id")
    gtbt = leg_res.get("good_til_block_time")
    if client_id is None or gtbt is None:
        return None
    try:
        return _resolve(_venue(venue_name).cancel_order(symbol, client_id, gtbt))
    except Exception as e:
        logger.error("resting-order cancel raised for %s/%s: %s",
                     venue_name, symbol, e)
        return {"cancelled": False, "error": str(e)}


@app.post("/hedge/open")
def hedge_open():
    """Open both legs of a delta-neutral hedge, or leave the account flat.

    Sequence: refuse unless flat -> place short -> confirm it filled -> place
    long -> confirm it filled -> unwind the short if the long did not. The only
    accepted outcomes are 'both legs on' or 'nothing on'.

    Defaults to dry_run=True like /venues/<v>/order; a caller must send
    dry_run=false explicitly to reach a venue.
    """
    body = request.get_json(force=True, silent=True) or {}
    dry_run = body.get("dry_run", True) is not False

    short_venue = body.get("short_venue")
    long_venue = body.get("long_venue")
    short_symbol = body.get("short_symbol")
    long_symbol = body.get("long_symbol")
    size = body.get("size")
    ref_price = body.get("ref_price")

    missing = [k for k in ("short_venue", "long_venue", "short_symbol",
                           "long_symbol", "size", "ref_price")
               if body.get(k) in (None, "")]
    if missing:
        return jsonify(error=f"missing required field(s): {', '.join(missing)}"), 400
    for name in (short_venue, long_venue):
        if name not in VENUES:
            return jsonify(error=f"unknown venue '{name}'"), 404
    if short_venue == long_venue:
        return jsonify(error="short_venue and long_venue must differ"), 400

    cross_pct = float(body.get("cross_pct",
                               config.get("trading.executor.cross_pct", 0.05)))
    fill_timeout = float(body.get("fill_timeout_s",
                                  config.get("trading.executor.fill_timeout_s", 15)))
    try:
        cap = _effective_cap_notional()
        step = _hedge_size_step(short_venue, short_symbol, long_venue, long_symbol)
        tick = _hedge_price_tick(short_venue, short_symbol, long_venue,
                                 long_symbol, ref_price)
        # None -> plan_hedge_legs keeps its $1 default (majors unchanged; sub-$1
        # would refuse). A real tick lets any-priced asset build crossing limits.
        kw = {"cap_notional": cap, "size_step": step}
        if tick:
            kw["price_tick"] = tick
        legs = plan_hedge_legs(short_symbol, long_symbol, size, ref_price,
                               cross_pct, **kw)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if legs["shaved"]:
        logger.info("HEDGE size shaved to fit cap: %s", legs["shaved"])
    if legs["quantized"]:
        logger.info("HEDGE size quantized to venue step: %s", legs["quantized"])

    # 1. Preflight — only open from flat. Stacking onto an existing position
    #    would silently change the size the engine sized for.
    try:
        pre = {short_venue: _signed_position(short_venue, short_symbol),
               long_venue: _signed_position(long_venue, long_symbol)}
    except Exception as e:
        logger.error("hedge preflight state read failed: %s", e)
        return jsonify(opened=False, status="refused",
                       detail=f"could not read account state: {e}"), 503
    if any(pre.values()):
        logger.info("HEDGE REFUSED (not flat): %s", pre)
        return jsonify(opened=False, status="refused",
                       detail="account is not flat; close existing positions first",
                       positions=pre)

    if dry_run:
        return jsonify(opened=False, dry_run=True, status="planned",
                       plan={"short_venue": short_venue, "long_venue": long_venue,
                             "cross_pct": cross_pct, "cap_notional": cap,
                             "legs": legs},
                       positions=pre,
                       detail="dry run — no orders sent; resend with dry_run=false")

    logger.info("HEDGE OPEN short=%s/%s long=%s/%s size=%s ref=%s cross=%s%%",
                short_venue, short_symbol, long_venue, long_symbol,
                size, ref_price, cross_pct)

    # 2. Short leg first, then confirm by position (not by the place response).
    #    A refusal is final, so don't wait on it — nothing was sent.
    short_res = _place_leg(short_venue, legs["short"])
    if _leg_refused(short_res):
        logger.info("HEDGE ABORTED: short leg refused; account still flat")
        return jsonify(opened=False, status="aborted_flat",
                       detail="short leg was refused; nothing opened, account flat",
                       legs={"short": short_res, "long": None},
                       positions={short_venue: 0.0, long_venue: 0.0})
    # A state read can now RAISE when the venue is unreadable (executor/errors.py)
    # instead of quietly reporting flat. That is correct — but it must not escape
    # here: the short may be LIVE, and an uncaught raise would skip the unwind below
    # and return a 500 with a naked leg on. Treat "cannot confirm" as "did not
    # confirm" and fall into the cancel/flatten path.
    try:
        short_pos = _await_position(short_venue, short_symbol, False, fill_timeout)
    except Exception as e:
        logger.error("HEDGE: could not confirm the short leg (%s) — unwinding", e)
        short_pos = 0.0
    if not short_pos:
        # Mirror the long path: if the short was a dYdX LONG_TERM order it may be
        # RESTING, not gone — cancel it, then confirm flat (a fill can race the
        # cancel). "aborted_flat" must mean the account is ACTUALLY flat, or the
        # resting order fills later into a naked short.
        cancel_short = _cancel_resting(short_venue, short_symbol, short_res)
        try:
            leftover = _signed_position(short_venue, short_symbol)
        except Exception as e:
            # Cannot read whether anything is left. "aborted_flat" would be a claim
            # we have no basis for, and claiming flat while a leg is on is the exact
            # shape of the 2026-07-27 loss. Send the reduce-only close anyway (it is
            # a no-op against a flat account) and report the truth: indeterminate.
            logger.error("HEDGE abort: could not read %s for leftovers (%s) —"
                         " sending a blind reduce-only close", short_venue, e)
            try:
                blind_close = _close_leg(short_venue, short_symbol)
            except Exception as ce:
                blind_close = {"error": f"{type(ce).__name__}: {ce}"}
            return jsonify(
                opened=False, status="INDETERMINATE_UNREADABLE",
                detail=(f"the short leg did not confirm AND {short_venue} state is"
                        f" unreadable ({e}). A reduce-only close was sent blind."
                        " VERIFY THE ACCOUNT MANUALLY — this may be a naked leg."),
                legs={"short": short_res, "long": None},
                cancel_short=cancel_short, blind_close=blind_close), 500
        if leftover:
            _close_leg(short_venue, short_symbol)
            leftover = _await_flat(short_venue, short_symbol, fill_timeout)
        if leftover:
            logger.error("NAKED LEG: %s holds %s after abort cancel/flatten",
                         short_venue, leftover)
            return jsonify(opened=False, status="NAKED_LEG_UNWIND_FAILED",
                           detail=(f"short leg did not confirm and {short_venue} "
                                   f"{leftover} could not be flattened. The position "
                                   "watchdog should flatten it; verify now."),
                           legs={"short": short_res, "long": None},
                           cancel_short=cancel_short,
                           positions={short_venue: leftover, long_venue: 0.0}), 500
        logger.info("HEDGE ABORTED: short leg did not fill; account still flat")
        return jsonify(opened=False, status="aborted_flat",
                       detail="short leg did not fill; any resting order cancelled; "
                              "nothing opened, account flat",
                       legs={"short": short_res, "long": None},
                       cancel_short=cancel_short,
                       positions={short_venue: 0.0, long_venue: 0.0})

    # 3. Long leg. From here the short is LIVE — every failure path must unwind.
    #    Skip the fill wait when the leg was refused outright: there is no fill
    #    coming, and every second spent waiting is a second held naked.
    try:
        long_res = _place_leg(long_venue, legs["long"])
        if _leg_refused(long_res):
            logger.error("HEDGE: long leg refused (%s) — unwinding short now",
                         (long_res.get("gate") or long_res.get("error")))
            long_pos = 0.0
        else:
            long_pos = _await_position(long_venue, long_symbol, True, fill_timeout)
    except Exception as e:
        logger.error("HEDGE long leg raised: %s — unwinding short", e)
        long_res, long_pos = {"error": str(e)}, 0.0

    if long_pos:
        logger.info("HEDGE OPEN OK short=%s long=%s", short_pos, long_pos)
        return jsonify(opened=True, status="hedged",
                       legs={"short": short_res, "long": long_res},
                       positions={short_venue: short_pos, long_venue: long_pos})

    # 4. Long leg did not confirm within the fill window. Before unwinding, CANCEL
    #    it — a dYdX LONG_TERM open leg is still resting on the book and WILL fill
    #    if price reaches it (the unpaired long of 2026-07-22). The cancel can lose
    #    a race to a fill, so RE-CHECK: if the long actually filled, the hedge is
    #    on and we must NOT unwind it. A short window lets the lagging indexer
    #    surface a just-landed fill without holding the short naked much longer.
    cancel_long = _cancel_resting(long_venue, long_symbol, long_res)
    long_pos = _await_position(long_venue, long_symbol, True, min(3.0, fill_timeout))
    if long_pos:
        logger.info("HEDGE OPEN OK (long filled while cancelling) short=%s long=%s",
                    short_pos, long_pos)
        return jsonify(opened=True, status="hedged",
                       legs={"short": short_res, "long": long_res},
                       cancel_long=cancel_long,
                       positions={short_venue: short_pos, long_venue: long_pos})

    # Long is confirmed off the book -> unwind the short so we never hold a naked leg.
    logger.error("HEDGE BROKEN: long leg not filled — resting order cancelled, "
                 "unwinding %s short", short_venue)
    unwind_res, unwind_err = None, None
    try:
        unwind_res = _close_leg(short_venue, short_symbol)
    except Exception as e:
        unwind_err = str(e)
        logger.error("HEDGE UNWIND RAISED: %s", e)

    remaining = _signed_position(short_venue, short_symbol)
    # Re-confirm the long stayed flat too: a fill could have landed after the
    # re-check but before the cancel took effect. Either leftover means NOT flat.
    long_leftover = _signed_position(long_venue, long_symbol)
    if remaining or long_leftover:
        # Worst case. Say so loudly; the position watchdog is the backstop.
        logger.error("NAKED LEG after unwind: %s short=%s, %s long=%s",
                     short_venue, remaining, long_venue, long_leftover)
        return jsonify(opened=False, status="NAKED_LEG_UNWIND_FAILED",
                       detail=(f"open failed and the account could NOT be returned "
                               f"to flat — {short_venue} {remaining}, {long_venue} "
                               f"{long_leftover} still open. The position watchdog "
                               "should flatten it; verify now."),
                       legs={"short": short_res, "long": long_res},
                       cancel_long=cancel_long,
                       unwind={"result": unwind_res, "error": unwind_err},
                       positions={short_venue: remaining,
                                  long_venue: long_leftover}), 500

    logger.info("HEDGE UNWOUND: account flat again")
    return jsonify(opened=False, status="unwound",
                   detail="long leg did not fill; resting order cancelled, short "
                          "leg unwound, account flat",
                   legs={"short": short_res, "long": long_res},
                   cancel_long=cancel_long,
                   unwind={"result": unwind_res},
                   positions={short_venue: 0.0, long_venue: 0.0})


def _fill_price(res):
    """Average fill price out of a close result, or None. Best-effort by design.

    Each venue reports fills in its own shape and neither is guaranteed to be present
    (an IOC that filled in pieces, a dYdX tx that confirms without an echo), so every
    lookup here is allowed to come back empty. A close notification with a missing
    price is still worth sending; one that raises while extracting a price is not.
    """
    if not isinstance(res, dict):
        return None
    try:
        statuses = (res.get("response", {}).get("response", {})
                    .get("data", {}).get("statuses") or [])
        for s in statuses:
            px = (s.get("filled") or {}).get("avgPx")
            if px:
                return float(px)
    except Exception:
        pass
    for key in ("price", "avg_px", "avgPx"):
        try:
            if res.get(key):
                return float(res[key])
        except (TypeError, ValueError):
            pass
    return None


def _notify_closed(legs, pre, results):
    """Push a round-trip-complete alert. Best-effort, and never in the close path.

    Closes are the event worth an unprompted push: a completed round trip with a
    realized number attached, and the one that can happen while you are asleep — the
    exit crons run hourly. Opens are usually something you initiated yourself.

    Deliberately here in the daemon rather than in the calling skill, so it fires for
    EVERY close route: a Conductor plan, an Ainara request, or a hand-rolled curl. The
    watchdog's own protective closes notify separately, from the watchdog.

    Wrapped whole: the position is already flat by the time this runs, and no
    notification failure may turn a successful close into an error response.
    """
    try:
        notifier = _notifier()
        if not notifier.push_enabled:
            return
        coin = next((str(s).split("-")[0].upper() for s in legs.values() if s), "?")
        lines = []
        for venue, symbol in legs.items():
            size = pre.get(venue)
            if not size:
                continue
            px = _fill_price(results.get(venue))
            side = "short" if size < 0 else "long"
            lines.append(f"{venue}: closed {side} {abs(size)}"
                         + (f" @ {px}" if px else ""))
        notifier.send(
            f"[CLOSED] {coin} hedge flat",
            "\n".join(lines) + "\n\nBoth legs confirmed flat. Ask for the portfolio"
            " review to see realized funding and fees for the round trip.",
            severity="info",
            data={"coin": coin, "closed_from": pre})
    except Exception as e:
        logger.warning("close notification failed (position IS closed): %s", e)


def _await_flat(venue_name, symbol, timeout_s, poll_s=1.0):
    """Poll until `symbol` is flat on `venue_name`. Returns the leftover size."""
    deadline = time.monotonic() + float(timeout_s)
    while True:
        sz = _signed_position(venue_name, symbol)
        if not sz:
            return 0.0
        if time.monotonic() >= deadline:
            return sz
        time.sleep(poll_s)


@app.post("/hedge/close")
def hedge_close():
    """Close every leg of an open hedge and confirm the account is flat.

    The mirror of /hedge/open, and the half the live system never had: `decide` can
    only ever open, so without this a position is entered and never left.

    Simpler than opening in one important way — closing only ever REDUCES risk, so
    it is never capped and never refused. It still confirms by reading positions
    back, and shouts if anything survives.

    Body: {"legs": {"hyperliquid": "BTC", "dydx": "BTC-USD"}, "dry_run": false}
    """
    body = request.get_json(force=True, silent=True) or {}
    dry_run = body.get("dry_run", True) is not False
    legs = body.get("legs") or {}

    if not isinstance(legs, dict) or not legs:
        return jsonify(error="legs must be a non-empty {venue: symbol} object"), 400
    for name in legs:
        if name not in VENUES:
            return jsonify(error=f"unknown venue '{name}'"), 404
    timeout = float(body.get("flat_timeout_s",
                             config.get("trading.executor.fill_timeout_s", 15)))

    try:
        pre = {v: _signed_position(v, s) for v, s in legs.items()}
    except Exception as e:
        logger.error("hedge close state read failed: %s", e)
        return jsonify(closed=False, status="refused",
                       detail=f"could not read account state: {e}"), 503

    if not any(pre.values()):
        return jsonify(closed=True, status="flat_already",
                       detail="nothing open on either venue", positions=pre)

    if dry_run:
        return jsonify(closed=False, dry_run=True, status="planned",
                       detail="dry run — nothing closed; resend with dry_run=false",
                       positions=pre)

    logger.info("HEDGE CLOSE %s", pre)
    results = {}
    for venue_name, symbol in legs.items():
        if not pre.get(venue_name):
            continue
        try:
            results[venue_name] = _close_leg(venue_name, symbol)
        except Exception as e:
            logger.error("HEDGE CLOSE %s raised: %s", venue_name, e)
            results[venue_name] = {"error": str(e)}

    post = {v: _await_flat(v, s, timeout) for v, s in legs.items()}
    if any(post.values()):
        still = {v: sz for v, sz in post.items() if sz}
        logger.error("HEDGE CLOSE INCOMPLETE: still open %s", still)
        return jsonify(closed=False, status="PARTIAL_CLOSE_FAILED",
                       detail=(f"could not flatten {', '.join(still)} — {still} still "
                               "open. The position watchdog should finish this; "
                               "verify now."),
                       legs=results, positions=post), 500

    logger.info("HEDGE CLOSED: account flat")
    _notify_closed(legs, pre, results)
    return jsonify(closed=True, status="closed", detail="all legs closed; flat",
                   legs=results, positions=post, was=pre)


def main():
    port = int(config.get("executor.port", 8130))
    logger.info("executor daemon on http://127.0.0.1:%s", port)
    app.run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
