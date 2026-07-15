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

Supports two signing modes, auto-detected from config:
  - "permissioned": account_address + agent_private_key (+ authenticator_id).
    A scoped trade-only API key (no withdraw). Preferred. The main wallet seed
    never enters the running bot.
  - "mnemonic": mnemonic. Full-custody signing; use only with a DEDICATED wallet.

validate() confirms the delegated key is authorized on-chain (mirrors how the HL
adapter confirms its agent is approved).
"""

import base64
import hashlib
import logging
import random
import time

import bech32
import requests
from dydx_v4_client import MAX_CLIENT_ID, OrderFlags
from dydx_v4_client.indexer.rest.constants import OrderType
from dydx_v4_client.key_pair import KeyPair
from dydx_v4_client.network import TESTNET
from dydx_v4_client.node.builder import TxOptions
from dydx_v4_client.node.client import NodeClient
from dydx_v4_client.node.market import Market
from dydx_v4_client.wallet import Wallet
from v4_proto.dydxprotocol.clob.order_pb2 import Order

from executor.compliance import check_submission

logger = logging.getLogger(__name__)

INDEXER = {
    "testnet": "https://indexer.v4testnet.dydx.exchange",
    "mainnet": "https://indexer.dydx.trade",
}


def _compress(pub: bytes) -> bytes:
    if len(pub) == 65:
        return (b"\x02" if pub[64] % 2 == 0 else b"\x03") + pub[1:33]
    return pub


def _address_from_mnemonic(mnemonic):
    pub = _compress(KeyPair.from_mnemonic(mnemonic).public_key_bytes)
    ripe = hashlib.new("ripemd160", hashlib.sha256(pub).digest()).digest()
    return bech32.bech32_encode("dydx", bech32.convertbits(ripe, 8, 5))


class DydxExecutor:
    def __init__(self, config):
        self.config = config
        self.network, creds = config.venue("dydx")
        self.indexer = INDEXER[self.network]
        self._creds = creds
        if creds.get("agent_private_key"):
            self.mode = "permissioned"
            self.account_address = creds.get("account_address")
            self._api_key = creds["agent_private_key"]
            self.authenticator_id = creds.get("authenticator_id")
        else:
            self.mode = "mnemonic"
            self._mnemonic = creds.get("mnemonic")
            self.account_address = (
                creds.get("address") or _address_from_mnemonic(self._mnemonic)
            )

    # ------------------------------------------------------------------
    def _api_pubkey(self):
        k = self._api_key[2:] if self._api_key.startswith("0x") else self._api_key
        return _compress(KeyPair.from_hex(k).public_key_bytes)

    async def _node(self):
        # Only testnet node wired here; mainnet node added when we go live there.
        return await NodeClient.connect(TESTNET.node)

    # ------------------------------------------------------------------
    async def validate(self):
        """Confirm the signing credential is authorized for the account."""
        if self.mode == "mnemonic":
            derived = _address_from_mnemonic(self._mnemonic)
            ok = derived == self.account_address
            return {"venue": "dydx", "mode": "mnemonic", "network": self.network,
                    "address": derived, "ok": ok}

        # permissioned: find the authenticator whose SignatureVerification is our key
        our_b64 = base64.b64encode(self._api_pubkey()).decode()
        node = await self._node()
        resp = await node.get_authenticators(self.account_address)
        matched = None
        for a in resp.account_authenticators:
            if our_b64 in bytes(a.config).decode("utf-8", "replace"):
                matched = a
                break
        cfg_id = str(self.authenticator_id) if self.authenticator_id is not None else None
        return {
            "venue": "dydx", "mode": "permissioned", "network": self.network,
            "account": self.account_address,
            "authorized_authenticator_id": matched.id if matched else None,
            "config_authenticator_id": cfg_id,
            "config_id_matches": bool(matched) and str(matched.id) == cfg_id,
            "ok": bool(matched) and str(matched.id) == cfg_id,
        }

    def state(self, subaccount=0):
        """Subaccount equity / free collateral from the public indexer."""
        r = requests.get(
            f"{self.indexer}/v4/addresses/{self.account_address}", timeout=20
        )
        subs = r.json().get("subaccounts")
        if not subs:
            return {"venue": "dydx", "network": self.network,
                    "address": self.account_address, "subaccount_exists": False,
                    "note": "no subaccount yet (fund it before trading)"}
        s = next((x for x in subs if x.get("subaccountNumber") == subaccount), subs[0])
        return {
            "venue": "dydx", "network": self.network,
            "address": self.account_address, "subaccount": s.get("subaccountNumber"),
            "equity": float(s.get("equity", 0)),
            "free_collateral": float(s.get("freeCollateral", 0)),
            "open_positions": list((s.get("openPerpetualPositions") or {}).keys()),
        }

    def open_orders(self, subaccount=0):
        r = requests.get(
            f"{self.indexer}/v4/orders?address={self.account_address}"
            f"&subaccountNumber={subaccount}&status=OPEN", timeout=20)
        return r.json()

    def _api_key_hex(self):
        return self._api_key[2:] if self._api_key.startswith("0x") else self._api_key

    def _market(self, ticker):
        md = requests.get(
            f"{self.indexer}/v4/perpetualMarkets?ticker={ticker}", timeout=20
        ).json()["markets"][ticker]
        return Market(md)

    async def _signer(self, node):
        """Build the (wallet, tx_options) that sign as the permissioned key on
        behalf of the main account. tx_options carries the authenticator id and
        the account sequence/number (the sequence manager is bypassed for it)."""
        account = await node.get_account(self.account_address)
        wallet = Wallet(KeyPair.from_hex(self._api_key_hex()),
                        account.account_number, account.sequence)
        tx_options = TxOptions(authenticators=[int(self.authenticator_id)],
                               sequence=account.sequence,
                               account_number=account.account_number)
        return wallet, tx_options

    async def place_order(self, market, is_buy, size, price, reduce_only=False,
                          dry_run=True, good_til_seconds=3600):
        """Place a stateful (LONG_TERM) limit order via the permissioned key.

        Returns client_id + good_til_block_time, which cancel_order needs to
        reconstruct the order id.
        """
        order = {"venue": "dydx", "network": self.network, "market": market,
                 "side": "buy" if is_buy else "sell", "size": size,
                 "price": price, "reduce_only": reduce_only, "mode": self.mode}
        gate = check_submission(self.config, self.network, dry_run)
        if gate is not None:
            return {"submitted": False, "order": order, "gate": gate}
        if self.mode != "permissioned":
            return {"submitted": False, "order": order,
                    "gate": {"refused": "mnemonic order path not wired; "
                             "use a permissioned api key"}}
        node = await self._node()
        mkt = self._market(market)
        wallet, tx_options = await self._signer(node)
        client_id = random.randint(0, MAX_CLIENT_ID)
        gtbt = int(time.time()) + int(good_til_seconds)
        order_id = mkt.order_id(self.account_address, 0, client_id,
                                OrderFlags.LONG_TERM)
        side = Order.Side.SIDE_BUY if is_buy else Order.Side.SIDE_SELL
        proto = mkt.order(order_id, OrderType.LIMIT, side, float(size), float(price),
                          Order.TimeInForce.TIME_IN_FORCE_UNSPECIFIED,
                          reduce_only=reduce_only, good_til_block_time=gtbt)
        resp = await node.place_order(wallet, proto, tx_options=tx_options)
        code = getattr(getattr(resp, "tx_response", resp), "code", None)
        return {"submitted": code == 0, "order": order, "tx_code": code,
                "client_id": client_id, "good_til_block_time": gtbt}

    async def cancel_order(self, market, client_id, good_til_block_time):
        """Cancel a stateful order by the client_id + gtbt returned from place."""
        node = await self._node()
        mkt = self._market(market)
        wallet, tx_options = await self._signer(node)
        order_id = mkt.order_id(self.account_address, 0, int(client_id),
                                OrderFlags.LONG_TERM)
        resp = await node.cancel_order(
            wallet, order_id, good_til_block_time=int(good_til_block_time),
            tx_options=tx_options)
        code = getattr(getattr(resp, "tx_response", resp), "code", None)
        return {"cancelled": code == 0, "tx_code": code, "client_id": client_id}
