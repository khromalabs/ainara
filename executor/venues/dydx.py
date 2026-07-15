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

"""dYdX v4 execution adapter (runs in the isolated executor venv).

dYdX has NO delegated-agent concept — the wallet mnemonic is both the trading key
and the withdrawal key. So the config must point at a DEDICATED wallet holding
only bot capital. validate() proves the mnemonic by deriving its address and
checking it matches the configured/funded wallet.
"""

import hashlib
import logging

import bech32
import requests
from dydx_v4_client.key_pair import KeyPair

from executor.compliance import check_submission

logger = logging.getLogger(__name__)

INDEXER = {
    "testnet": "https://indexer.v4testnet.dydx.exchange",
    "mainnet": "https://indexer.dydx.trade",
}


def _address_from_mnemonic(mnemonic):
    """Derive the dydx1... bech32 address from a mnemonic (standard Cosmos)."""
    pub = KeyPair.from_mnemonic(mnemonic).public_key_bytes
    if len(pub) == 65:  # uncompressed -> compress for the address hash
        pub = (b"\x02" if pub[64] % 2 == 0 else b"\x03") + pub[1:33]
    ripe = hashlib.new("ripemd160", hashlib.sha256(pub).digest()).digest()
    return bech32.bech32_encode("dydx", bech32.convertbits(ripe, 8, 5))


class DydxExecutor:
    def __init__(self, config):
        self.config = config
        self.network, creds = config.venue("dydx")
        self.indexer = INDEXER[self.network]
        self._mnemonic = creds.get("mnemonic")
        # Optional: an explicitly configured address to cross-check the mnemonic.
        self.expected_address = creds.get("address")

    def validate(self):
        if not self._mnemonic:
            return {"venue": "dydx", "ok": False, "error": "missing mnemonic"}
        derived = _address_from_mnemonic(self._mnemonic)
        result = {
            "venue": "dydx",
            "network": self.network,
            "derived_address": derived,
            "ok": True,
        }
        if self.expected_address:
            result["expected_address"] = self.expected_address
            result["ok"] = derived == self.expected_address
        return result

    def state(self, subaccount=0):
        """Subaccount equity / free collateral from the public indexer."""
        addr = _address_from_mnemonic(self._mnemonic)
        r = requests.get(f"{self.indexer}/v4/addresses/{addr}", timeout=20)
        data = r.json()
        subs = data.get("subaccounts")
        if not subs:
            return {"venue": "dydx", "network": self.network, "address": addr,
                    "subaccount_exists": False,
                    "note": "no subaccount yet (fund it before trading)"}
        s = next((x for x in subs if x.get("subaccountNumber") == subaccount), subs[0])
        return {
            "venue": "dydx", "network": self.network, "address": addr,
            "subaccount": s.get("subaccountNumber"),
            "equity": float(s.get("equity", 0)),
            "free_collateral": float(s.get("freeCollateral", 0)),
            "open_positions": list((s.get("openPerpetualPositions") or {}).keys()),
        }

    def place_order(self, market, is_buy, size, price, reduce_only=False,
                    dry_run=True):
        """Construct (and, if permitted, submit) a limit order.

        NOT YET WIRED TO LIVE SUBMIT — returns the constructed order and gate
        decision only. Live signing/submit via NodeClient lands next increment.
        """
        order = {
            "venue": "dydx", "network": self.network, "market": market,
            "side": "buy" if is_buy else "sell", "size": size,
            "price": price, "reduce_only": reduce_only,
        }
        gate = check_submission(self.config, self.network, dry_run)
        if gate is not None:
            return {"submitted": False, "order": order, "gate": gate}
        return {"submitted": False, "order": order,
                "gate": {"refused": "live_submit_not_implemented"}}
