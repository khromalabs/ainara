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

from executor.compliance import check_submission

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
        self._exchange = None  # lazily built only when a live order is needed

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
        positions = [
            {
                "coin": p["position"]["coin"],
                "szi": float(p["position"]["szi"]),
                "entry_px": p["position"].get("entryPx"),
                "unrealized_pnl": p["position"].get("unrealizedPnl"),
            }
            for p in st.get("assetPositions", [])
        ]
        spot = self._info({"type": "spotClearinghouseState", "user": self.master})
        usdc_spot = next(
            (float(b["total"]) for b in spot.get("balances", [])
             if b.get("coin") == "USDC"),
            0.0,
        )
        return {
            "venue": "hyperliquid",
            "network": self.network,
            "perp_account_value": float(ms.get("accountValue", 0)),
            "usdc_spot": usdc_spot,
            "positions": positions,
        }

    # ---- writes (signing SDK; gated) ----

    def place_order(self, coin, is_buy, size, limit_px, reduce_only=False,
                    dry_run=True):
        """Construct (and, if permitted, submit) a limit order.

        NOT YET WIRED TO LIVE SUBMIT — this increment returns the constructed
        order and the gate decision only. The live SDK submit path lands in the
        next increment, behind exactly the gate returned here.
        """
        order = {
            "venue": "hyperliquid", "network": self.network, "coin": coin,
            "side": "buy" if is_buy else "sell", "size": size,
            "limit_px": limit_px, "reduce_only": reduce_only,
        }
        gate = check_submission(self.config, self.network, dry_run)
        if gate is not None:
            return {"submitted": False, "order": order, "gate": gate}
        # TODO(next increment): build Exchange(agent_wallet, base, account_address
        # =master) and call .order(...); return the exchange response.
        return {"submitted": False, "order": order,
                "gate": {"refused": "live_submit_not_implemented"}}
