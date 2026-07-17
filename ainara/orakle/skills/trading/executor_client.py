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

import json
import logging
from typing import Annotated, Any, Dict, Literal, Optional, Union

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
    @staticmethod
    def _unwrap_decision(decision) -> Union[dict, str]:
        """Normalize a carry-engine verdict to a plain dict.

        Accepts the dict itself, its JSON string (how a Conductor param arrives,
        since scratchpad templates stringify), and the {"result": {...}} envelope
        skill results are wrapped in. Returns an error string if it can't.
        """
        if isinstance(decision, str):
            try:
                decision = json.loads(decision)
            except (ValueError, TypeError):
                return "decision is not valid JSON"
        if not isinstance(decision, dict):
            return f"decision must be an object, got {type(decision).__name__}"
        inner = decision.get("result")
        if isinstance(inner, dict):
            decision = inner
        return decision

    def _open_hedge(self, decision, dry_run: bool) -> Dict[str, Any]:
        """Open both legs from a decide verdict, deterministically.

        Re-checks the engine's own sit_out/action verdict before submitting. The
        Conductor's avoid_step_if guard fails OPEN on an unresolvable path, so
        this is the check that actually holds if the plan's gate is misspelled.
        """
        if decision is None:
            return {"error": "open_hedge requires the carry engine's decision"}
        d = self._unwrap_decision(decision)
        if isinstance(d, str):
            return {"error": d}

        if d.get("sit_out") is True or d.get("action") == "sit_out":
            return {"opened": False, "status": "sit_out",
                    "detail": "engine says sit out; no orders sent",
                    "reason": d.get("reason")}
        if d.get("action") != "open":
            return {"opened": False, "status": "refused",
                    "detail": f"unexpected action {d.get('action')!r}; "
                              "expected 'open'"}

        body = {k: d.get(k) for k in ("short_venue", "long_venue", "short_symbol",
                                      "long_symbol", "size", "ref_price")}
        missing = [k for k, v in body.items() if v in (None, "")]
        if missing:
            return {"error": "decision is missing required field(s): "
                             f"{', '.join(missing)}"}
        body["dry_run"] = dry_run
        return self._request("POST", "/hedge/open", body)

    def _close_hedge(self, decision, dry_run: bool) -> Dict[str, Any]:
        """Close an open hedge from a decide_exit verdict, deterministically.

        Re-checks the verdict's own action before closing, mirroring _open_hedge:
        the Conductor's avoid_step_if fails OPEN, so this is the check that holds
        if the plan's gate is ever misspelled. Refusing to close is safe (the
        position simply stays), so this errs toward doing nothing.
        """
        if decision is None:
            return {"error": "close_hedge requires the exit decision"}
        d = self._unwrap_decision(decision)
        if isinstance(d, str):
            return {"error": d}

        if d.get("action") != "close" or d.get("skip_close") is True:
            return {"closed": False, "status": "skipped",
                    "detail": f"exit verdict is {d.get('action')!r}; not closing",
                    "reason": d.get("reason")}

        coin = d.get("coin")
        if not coin:
            return {"error": "exit decision is missing 'coin'"}
        # Venue symbol conventions: bare coin on HL, USD-quoted pair on dYdX.
        return self._request("POST", "/hedge/close", {
            "legs": {"hyperliquid": coin, "dydx": f"{coin}-USD"},
            "dry_run": dry_run,
        })

    # ------------------------------------------------------------------
    async def run(
        self,
        action: Annotated[
            Literal["validate", "state", "orders", "place", "cancel", "health",
                    "open_hedge", "close_hedge"],
            "What to do: check daemon 'health'; 'validate' credentials; read"
            " account 'state'; list open 'orders'; 'place' or 'cancel' an order;"
            " 'open_hedge' to open BOTH legs of a carry-engine decision at once;"
            " 'close_hedge' to flatten both legs from a decide_exit verdict",
        ] = "state",
        decision: Annotated[
            Optional[Union[str, dict]],
            "For 'open_hedge': the carry engine's decide verdict (dict, or the"
            " JSON string of it). Supplies both venues, symbols, size and"
            " ref_price, so no field has to be retyped. For 'close_hedge': the"
            " decide_exit verdict.",
        ] = None,
        venue: Annotated[
            Literal["hyperliquid", "dydx"], "Which venue"
        ] = "hyperliquid",
        symbol: Annotated[
            Optional[str], "Market symbol: 'BTC' on hyperliquid, 'BTC-USD' on dydx"
        ] = None,
        is_buy: Annotated[bool, "True to buy/long, False to sell/short"] = True,
        size: Annotated[Optional[float], "Order size in base units"] = None,
        price: Annotated[Optional[float], "Limit price"] = None,
        oid: Annotated[Optional[int], "Hyperliquid order id to cancel"] = None,
        client_id: Annotated[
            Optional[int], "dYdX client_id to cancel (from the place response)"
        ] = None,
        good_til_block_time: Annotated[
            Optional[int], "dYdX good_til_block_time to cancel (from place response)"
        ] = None,
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
        if action == "open_hedge":
            return self._open_hedge(decision, dry_run)
        if action == "close_hedge":
            return self._close_hedge(decision, dry_run)
        if action == "cancel":
            if not symbol:
                return {"error": "cancel requires symbol"}
            if venue == "dydx":
                if client_id is None or good_til_block_time is None:
                    return {"error": "dydx cancel requires client_id and "
                            "good_til_block_time (from the place response)"}
                return self._request("POST", f"/venues/{venue}/cancel", {
                    "symbol": symbol, "client_id": client_id,
                    "good_til_block_time": good_til_block_time})
            if oid is None:
                return {"error": "hyperliquid cancel requires oid"}
            return self._request("POST", f"/venues/{venue}/cancel",
                                 {"symbol": symbol, "oid": oid})
        return {"error": f"unknown action '{action}'"}
