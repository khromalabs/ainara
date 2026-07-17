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
import tempfile
import time

from flask import Flask, jsonify, request

from executor.config import ExecutorConfig
from executor.venues.dydx import DydxExecutor
from executor.venues.hyperliquid import HyperliquidExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("executor.server")

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


def plan_hedge_legs(short_symbol, long_symbol, size, ref_price, cross_pct,
                    cap_notional=None):
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

    Prices are rounded to whole dollars, matching the tick assumption the rest of
    the executor already makes for BTC (see watchdog._act).
    """
    size = float(size)
    ref_price = float(ref_price)
    cross = float(cross_pct) / 100.0
    if size <= 0:
        raise ValueError("size must be > 0")
    if ref_price <= 0:
        raise ValueError("ref_price must be > 0")

    sell_px = round(ref_price * (1 - cross))
    buy_px = round(ref_price * (1 + cross))

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

    return {
        "short": {"symbol": short_symbol, "is_buy": False,
                  "price": sell_px, "size": size},
        "long": {"symbol": long_symbol, "is_buy": True,
                 "price": buy_px, "size": size},
        "shaved": shaved,
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
        legs = plan_hedge_legs(short_symbol, long_symbol, size, ref_price,
                               cross_pct, cap_notional=cap)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if legs["shaved"]:
        logger.info("HEDGE size shaved to fit cap: %s", legs["shaved"])

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
    short_pos = _await_position(short_venue, short_symbol, False, fill_timeout)
    if not short_pos:
        logger.info("HEDGE ABORTED: short leg did not fill; account still flat")
        return jsonify(opened=False, status="aborted_flat",
                       detail="short leg did not fill; nothing opened, account flat",
                       legs={"short": short_res, "long": None},
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

    # 4. Long leg failed -> unwind the short so we never hold a naked leg.
    logger.error("HEDGE BROKEN: long leg not filled — unwinding %s short",
                 short_venue)
    unwind_res, unwind_err = None, None
    try:
        unwind_res = _close_leg(short_venue, short_symbol)
    except Exception as e:
        unwind_err = str(e)
        logger.error("HEDGE UNWIND RAISED: %s", e)

    remaining = _signed_position(short_venue, short_symbol)
    if remaining:
        # Worst case. Say so loudly; the position watchdog is the backstop.
        logger.error("NAKED LEG: %s still holds %s after unwind attempt",
                     short_venue, remaining)
        return jsonify(opened=False, status="NAKED_LEG_UNWIND_FAILED",
                       detail=(f"long leg failed and the {short_venue} short could "
                               f"NOT be unwound — {remaining} still open. The "
                               f"position watchdog should flatten it; verify now."),
                       legs={"short": short_res, "long": long_res},
                       unwind={"result": unwind_res, "error": unwind_err},
                       positions={short_venue: remaining, long_venue: 0.0}), 500

    logger.info("HEDGE UNWOUND: account flat again")
    return jsonify(opened=False, status="unwound",
                   detail="long leg did not fill; short leg unwound, account flat",
                   legs={"short": short_res, "long": long_res},
                   unwind={"result": unwind_res},
                   positions={short_venue: 0.0, long_venue: 0.0})


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
    return jsonify(closed=True, status="closed", detail="all legs closed; flat",
                   legs=results, positions=post, was=pre)


def main():
    port = int(config.get("executor.port", 8130))
    logger.info("executor daemon on http://127.0.0.1:%s", port)
    app.run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
