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

import logging
from typing import Annotated, Any, Dict, Literal, Optional

import requests

from ainara.framework.config import config
from ainara.framework.skill import Skill


class TradingExecutorClient(Skill):
    """Thin client to the standalone trading executor daemon.

    The daemon runs as a separate process (its own venv) that owns the venue
    signing SDKs and places the actual orders. This skill just proxies over
    localhost HTTP, so Orakle stays dependency-light. All safety enforcement —
    the dry_run / testnet / mainnet-jurisdiction gate — lives in the daemon, which
    is network-aware and closest to the venue. This client's own safety measure is
    that order placement defaults to dry_run (never submits unless asked).
    """

    matcher_info = (
        "Use this skill to drive the delta-neutral trading executor: check venue"
        " account state, list or place or cancel perpetual orders on Hyperliquid"
        " or dYdX through the local executor daemon. Order placement defaults to a"
        " safe dry run. Keywords: execute trade, place order, cancel order, open"
        " position, close position, account state, executor."
    )

    def __init__(self):
        super().__init__()
        self.name = "executor"
        self.logger = logging.getLogger(__name__)
        self.base_url = config.get(
            "apis.executor.url", "http://127.0.0.1:8130"
        ).rstrip("/")
        self.timeout = float(config.get("apis.executor.timeout", 30))

    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, body: Optional[dict] = None):
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(method, url, json=body, timeout=self.timeout)
        except requests.ConnectionError:
            return {
                "error": f"executor daemon not reachable at {self.base_url}. "
                "Start it: python -m executor.server (in the executor venv).",
                "reachable": False,
            }
        except requests.Timeout:
            return {"error": f"executor daemon timed out after {self.timeout}s"}
        try:
            data = resp.json()
        except ValueError:
            return {"error": f"non-JSON response ({resp.status_code})",
                    "body": resp.text[:200]}
        if resp.status_code >= 400 and "error" not in data:
            data = {"error": data, "status": resp.status_code}
        return data

    # ------------------------------------------------------------------
    async def run(
        self,
        action: Annotated[
            Literal["validate", "state", "orders", "place", "cancel", "health"],
            "What to do: check daemon 'health'; 'validate' credentials; read"
            " account 'state'; list open 'orders'; 'place' or 'cancel' an order",
        ] = "state",
        venue: Annotated[
            Literal["hyperliquid", "dydx"], "Which venue"
        ] = "hyperliquid",
        symbol: Annotated[
            Optional[str], "Market symbol: 'BTC' on hyperliquid, 'BTC-USD' on dydx"
        ] = None,
        is_buy: Annotated[bool, "True to buy/long, False to sell/short"] = True,
        size: Annotated[Optional[float], "Order size in base units"] = None,
        price: Annotated[Optional[float], "Limit price"] = None,
        oid: Annotated[Optional[int], "Order id to cancel"] = None,
        reduce_only: Annotated[bool, "Order may only reduce an existing position"] = False,
        dry_run: Annotated[
            bool,
            "If True (default) the order is validated but NOT submitted. Must be"
            " explicitly False to actually place a live order.",
        ] = True,
    ) -> Dict[str, Any]:
        """Drive the trading executor daemon over local HTTP."""
        if action == "health":
            return self._request("GET", "/health")
        if action == "validate":
            return self._request("GET", f"/venues/{venue}/validate")
        if action == "state":
            return self._request("GET", f"/venues/{venue}/state")
        if action == "orders":
            return self._request("GET", f"/venues/{venue}/orders")
        if action == "place":
            if not symbol or size is None or price is None:
                return {"error": "place requires symbol, size and price"}
            return self._request("POST", f"/venues/{venue}/order", {
                "symbol": symbol, "is_buy": is_buy, "size": size, "price": price,
                "reduce_only": reduce_only, "dry_run": dry_run,
            })
        if action == "cancel":
            if not symbol or oid is None:
                return {"error": "cancel requires symbol and oid"}
            return self._request("POST", f"/venues/{venue}/cancel",
                                 {"symbol": symbol, "oid": oid})
        return {"error": f"unknown action '{action}'"}
