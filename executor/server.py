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
import logging

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


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        venues=list(VENUES),
        jurisdiction_acknowledged=config.jurisdiction_acknowledged(),
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


def main():
    port = int(config.get("executor.port", 8130))
    logger.info("executor daemon on http://127.0.0.1:%s", port)
    app.run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
