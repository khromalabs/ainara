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

"""Hyperliquid execution adapter (runs in the isolated executor venv).

Uses the agent (API) wallet — a delegated key that can trade but not withdraw —
to sign, and the master account address for info reads. Reads go over the public
/info endpoint; only order actions use the signing SDK.
"""

import logging

import requests
from eth_account import Account
from hyperliquid.exchange import Exchange

from executor.compliance import check_order_cap, check_submission

logger = logging.getLogger(__name__)

BASE_URL = {
    "testnet": "https://api.hyperliquid-testnet.xyz",
    "mainnet": "https://api.hyperliquid.xyz",
}


class HyperliquidExecutor:
    def __init__(self, config):
        self.config = config
        self.network, creds = config.venue("hyperliquid")
        self.base = BASE_URL[self.network]
        self.master = creds.get("account_address")
        self._agent_key = creds.get("agent_private_key")
        self._exchange_client = None  # lazily built only when a live order is needed

    # ---- reads (public /info, no signing) ----

    def _info(self, body):
        r = requests.post(f"{self.base}/info", json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    def validate(self):
        """Confirm the agent key is a valid, approved, non-withdraw delegate."""
        if not self._agent_key or not self.master:
            return {"venue": "hyperliquid", "ok": False,
                    "error": "missing account_address or agent_private_key"}
        agent = Account.from_key(self._agent_key).address
        agents = self._info({"type": "extraAgents", "user": self.master})
        approved = (
            isinstance(agents, list)
            and any(a.get("address", "").lower() == agent.lower() for a in agents)
        )
        return {
            "venue": "hyperliquid",
            "network": self.network,
            "master": self.master,
            "agent": agent,
            "agent_approved": approved,
            "ok": approved,
        }

    def state(self):
        """Perp account value and open positions."""
        st = self._info({"type": "clearinghouseState", "user": self.master})
        ms = st.get("marginSummary", {})
        positions = []
        for p in st.get("assetPositions", []):
            pos = p["position"]
            szi = float(pos["szi"])
            liq_px = pos.get("liquidationPx")
            pos_val = float(pos.get("positionValue", 0) or 0)
            # mark implied by the position's own value (avoids an extra call)
            mark = pos_val / abs(szi) if szi else None
            liq_dist = None
            if liq_px is not None and mark:
                liq_dist = abs(mark - float(liq_px)) / mark * 100
            positions.append({
                "coin": pos["coin"],
                "szi": szi,
                "entry_px": pos.get("entryPx"),
                "mark_px": mark,
                "liquidation_px": float(liq_px) if liq_px is not None else None,
                "liq_distance_pct": liq_dist,
                "unrealized_pnl": pos.get("unrealizedPnl"),
            })
        spot = self._info({"type": "spotClearinghouseState", "user": self.master})
        usdc_spot = next(
            (float(b["total"]) for b in spot.get("balances", [])
             if b.get("coin") == "USDC"),
            0.0,
        )
        free = float(ms.get("accountValue", 0)) - float(ms.get("totalMarginUsed", 0))
        return {
            "venue": "hyperliquid",
            "network": self.network,
            "perp_account_value": float(ms.get("accountValue", 0)),
            "free_collateral": max(0.0, free),
            "usdc_spot": usdc_spot,
            "positions": positions,
        }

    # ---- writes (signing SDK; gated) ----

    def _exchange(self):
        """Lazily build the signing Exchange (agent wallet trades for master)."""
        if self._exchange_client is None:
            wallet = Account.from_key(self._agent_key)
            self._exchange_client = Exchange(
                wallet, self.base, account_address=self.master
            )
        return self._exchange_client

    def open_orders(self):
        return self._info({"type": "openOrders", "user": self.master})

    def place_order(self, coin, is_buy, size, limit_px, reduce_only=False,
                    tif="Gtc", dry_run=True):
        """Construct, then (if the gate permits) submit a limit order.

        tif: 'Gtc' resting, 'Alo' post-only/maker, 'Ioc' immediate-or-cancel.
        """
        order = {
            "venue": "hyperliquid", "network": self.network, "coin": coin,
            "side": "buy" if is_buy else "sell", "size": size,
            "limit_px": limit_px, "reduce_only": reduce_only, "tif": tif,
        }
        cap = check_order_cap(self.config, float(size) * float(limit_px),
                              reduce_only)
        if cap is not None:
            return {"submitted": False, "order": order, "gate": cap}
        gate = check_submission(self.config, self.network, dry_run)
        if gate is not None:
            return {"submitted": False, "order": order, "gate": gate}
        resp = self._exchange().order(
            coin, is_buy, size, limit_px, {"limit": {"tif": tif}},
            reduce_only=reduce_only,
        )
        return {"submitted": True, "order": order, "response": resp}

    def cancel_order(self, coin, oid):
        """Cancel a resting order by its oid. Not gated (reduces exposure)."""
        return self._exchange().cancel(coin, oid)
