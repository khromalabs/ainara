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
from dydx_v4_client.network import TESTNET, make_mainnet
from dydx_v4_client.node.builder import TxOptions
from dydx_v4_client.node.client import NodeClient
from dydx_v4_client.node.market import Market
from dydx_v4_client.wallet import Wallet
from v4_proto.dydxprotocol.clob.order_pb2 import Order

from executor.compliance import check_order_cap, check_submission
from executor.errors import VenueStateUnavailable

logger = logging.getLogger(__name__)

INDEXER = {
    "testnet": "https://indexer.v4testnet.dydx.exchange",
    "mainnet": "https://indexer.dydx.trade",
}

WS_INDEXER = {
    "testnet": "wss://indexer.v4testnet.dydx.exchange/v4/ws",
    "mainnet": "wss://indexer.dydx.trade/v4/ws",
}

# Public mainnet validator gRPC. Verified reachable at the time of writing; these
# are third-party endpoints and can rate-limit or disappear, so it is overridable
# via `apis.dydx.mainnet.node_url`. Known-good alternatives:
#   dydx-grpc.publicnode.com:443
#   dydx-grpc.kingnodes.com:443
MAINNET_NODE_URL = "dydx-ops-grpc.kingnodes.com:443"


def dydx_network(network, node_url=None):
    """Network config for `network`, so reads and writes hit the SAME chain.

    The adapter previously connected to TESTNET.node unconditionally while
    resolving the *indexer* by network — so a mainnet config would read mainnet
    state and submit orders to testnet. Orders would fail on chain-id mismatch,
    but so would the watchdog's close: a mainnet position with its safety net
    pointed at the wrong chain.
    """
    if network == "testnet":
        return TESTNET
    return make_mainnet(
        rest_indexer=INDEXER["mainnet"],
        websocket_indexer=WS_INDEXER["mainnet"],
        node_url=node_url or MAINNET_NODE_URL,
    )


def liquidation_price(equity, size_signed, mark_px, mmf):
    """Cross-margin liquidation price for a SINGLE-position subaccount.

    Hyperliquid hands us a liquidationPx; dYdX does not, so we derive it. dYdX v4
    is cross-margined per subaccount: liquidation triggers once equity falls to
    the maintenance margin requirement. With one open position:

        equity(P) = equity_now + size * (P - mark)      (unrealized PnL moves it)
        MMR(P)    = |size| * P * mmf
        solve equity(P) == MMR(P):
            P = (equity_now - size*mark) / (|size|*mmf - size)

    Returns None when price alone can never liquidate the position — a long whose
    equity exceeds its notional runs out of downside at P=0 and simply cannot be
    liquidated. None therefore means "no reachable liquidation", NOT "unknown";
    callers that could not read the risk params must say so separately.

    Single-position only: with several positions the MMR is the sum across them,
    and each leg's liquidation couples to the others. state() therefore does NOT
    call this when a subaccount holds more than one position — it reports
    "liquidation unknown" instead, so the watchdog alerts rather than trusting an
    optimistic number. The watchdog itself now assesses every coin (not just
    positions[0]); this formula stays valid only for a single-position subaccount.
    """
    s = float(size_signed)
    mark_px = float(mark_px)
    if not s or mark_px <= 0:
        return None
    denom = abs(s) * float(mmf) - s
    if denom == 0:
        return None
    p = (float(equity) - s * mark_px) / denom
    if p <= 0:
        return None  # unreachable: price cannot fall below zero
    # A long liquidates BELOW the mark, a short ABOVE it. Anything else means the
    # inputs disagree — report nothing rather than a number that reads as safe.
    if s > 0 and p >= mark_px:
        return None
    if s < 0 and p <= mark_px:
        return None
    return p


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
        # Coin -> subaccount map for POSITION ISOLATION, e.g. {BTC: 0, ETH: 1, SOL: 2}.
        # dYdX v4 is cross-margined per SUBACCOUNT, so two positions sharing one
        # subaccount share a liquidation: the maintenance requirement is the sum over
        # both, one leg's losses eat the other's collateral, and the single-position
        # liquidation formula stops being valid — which is why state() reported
        # "liquidation unknown" and left every multi-coin dYdX leg UNMONITORED.
        #
        # One coin per subaccount restores both properties: the formula is exact
        # again (so the watchdog can see the buffer), and a liquidation is contained
        # to the coin that caused it instead of cascading across the book.
        #
        # It does NOT create margin. Splitting the same equity three ways leaves each
        # position with the same buffer it had; what changes is visibility and blast
        # radius, not headroom.
        #
        # Unset/empty = every coin uses subaccount 0, exactly as before. Each
        # subaccount must be FUNDED separately before it can hold a position.
        self.subaccount_map = {
            str(k).upper(): int(v)
            for k, v in (config.get("trading.dydx.subaccounts", {}) or {}).items()
        }

    def subaccount_for(self, symbol):
        """Subaccount number for a market ('BTC-USD' or 'BTC'). 0 when unmapped."""
        return self.subaccount_map.get((symbol or "").split("-")[0].upper(), 0)

    # ------------------------------------------------------------------
    def _api_pubkey(self):
        k = self._api_key[2:] if self._api_key.startswith("0x") else self._api_key
        return _compress(KeyPair.from_hex(k).public_key_bytes)

    async def _node(self):
        """Connect to the node for the CONFIGURED network (see dydx_network)."""
        net = dydx_network(self.network, self._creds.get("node_url"))
        return await NodeClient.connect(net.node)

    def size_increment(self, market):
        """Smallest tradable size step for `market` (dYdX `stepSize`), or None.

        dYdX truncates any order to this, so a size that is not a multiple of it
        produces a leg SMALLER than the one Hyperliquid fills — i.e. residual
        unhedged delta. See server._hedge_size_step.
        """
        try:
            md = requests.get(
                f"{self.indexer}/v4/perpetualMarkets?ticker={market}", timeout=20
            ).json()["markets"][market]
            return float(md["stepSize"])
        except Exception as e:
            logger.warning("dydx stepSize unavailable for %s: %s", market, e)
            return None

    # ------------------------------------------------------------------
    async def validate(self):
        """Confirm the signing credential is authorized for the account."""
        if self.mode == "mnemonic":
            derived = _address_from_mnemonic(self._mnemonic)
            ok = derived == self.account_address
            return {"venue": "dydx", "mode": "mnemonic", "network": self.network,
                    "address": derived, "ok": ok}

        # permissioned: is the CONFIGURED authenticator registered and bound to our
        # key? Collect EVERY match, do not stop at the first.
        #
        # One key can back several authenticators — re-registering to widen the
        # subaccount scope deliberately reuses the key, so the old narrow one and the
        # new wide one both carry this pubkey. Breaking on the first match then
        # reported whichever the chain happened to list first as "the" authorized id,
        # so a correctly-configured account came back ok=False and pointed at the
        # authenticator it had just been migrated away FROM.
        our_b64 = base64.b64encode(self._api_pubkey()).decode()
        node = await self._node()
        resp = await node.get_authenticators(self.account_address)
        matches = [a.id for a in resp.account_authenticators
                   if our_b64 in bytes(a.config).decode("utf-8", "replace")]
        cfg_id = str(self.authenticator_id) if self.authenticator_id is not None else None
        configured_is_ours = cfg_id is not None and cfg_id in [str(i) for i in matches]
        return {
            "venue": "dydx", "mode": "permissioned", "network": self.network,
            "account": self.account_address,
            "authenticator_ids_for_this_key": matches,
            "config_authenticator_id": cfg_id,
            "config_id_matches": configured_is_ours,
            "ok": configured_is_ours,
            **({} if configured_is_ours or not matches else {
                "hint": f"config points at {cfg_id}, which is not bound to this bot"
                        f" key. Registered for it: {matches}."}),
        }

    def _market_risk(self, ticker):
        """(oracle_price, maintenance_margin_fraction) for a market, or (None, None).

        MMF is a market parameter, not an account setting — dYdX BTC-USD ships
        imf=0.02 (the '50x') / mmf=0.012.
        """
        try:
            md = requests.get(
                f"{self.indexer}/v4/perpetualMarkets?ticker={ticker}", timeout=20
            ).json()["markets"][ticker]
            return float(md["oraclePrice"]), float(md["maintenanceMarginFraction"])
        except Exception as e:
            # Say it out loud: without these the leg is invisible to the
            # watchdog's liquidation check, which is the whole point of wiring it.
            logger.warning("dydx market risk params unavailable for %s: %s",
                           ticker, e)
            return None, None

    def state(self, subaccount=0):
        """Subaccount equity / free collateral from the public indexer.

        Raises VenueStateUnavailable when the state cannot be READ, rather than
        returning something a caller could mistake for an empty account. This
        method used to do neither: no raise_for_status, and `if not subs` treated a
        MISSING "subaccounts" key exactly like an empty one — so a 429 or a 5xx
        with a JSON body returned a dict with no "positions", and every caller read
        that as "flat". See executor/errors.py for what that cost on 2026-07-27.

        The two cases are now distinct:
          - read failed / unparseable / no "subaccounts" field -> RAISE
          - read succeeded and there is genuinely no subaccount -> positions: []
        """
        try:
            r = requests.get(
                f"{self.indexer}/v4/addresses/{self.account_address}", timeout=20
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            raise VenueStateUnavailable(
                f"dydx indexer read failed for {self.account_address}"
                f" ({type(e).__name__}: {e})") from e
        if not isinstance(payload, dict) or "subaccounts" not in payload:
            got = (sorted(payload)[:6] if isinstance(payload, dict)
                   else type(payload).__name__)
            raise VenueStateUnavailable(
                "dydx indexer response carried no 'subaccounts' field — the read"
                f" did not succeed (got: {got})")
        subs = payload["subaccounts"]
        if not subs:
            # Genuinely nothing there — a real, readable answer. Carries an explicit
            # empty positions list so callers can tell it apart from a failed read.
            return {"venue": "dydx", "network": self.network,
                    "address": self.account_address, "subaccount_exists": False,
                    "positions": [], "open_positions": [],
                    "note": "no subaccount yet (fund it before trading)"}
        # BOOK-WIDE across every subaccount, not just one. The indexer already
        # returns them all, and with position isolation the legs live in DIFFERENT
        # subaccounts — reading only #0 would report a funded ETH position as flat,
        # which is the "unreadable looks empty" failure all over again.
        #
        # Liquidation is computed against the position's OWN subaccount equity,
        # because that is the pool that actually backs it. A subaccount holding one
        # position makes liquidation_price() exact; one holding several still degrades
        # to "unknown" (the maintenance requirement is the sum across them and each
        # leg's liquidation couples to the others). So isolation is what earns the
        # number back — this code just stops assuming one subaccount either way.
        positions, per_sub = [], {}
        for s in subs:
            num = s.get("subaccountNumber")
            equity = float(s.get("equity", 0) or 0)
            open_perps = s.get("openPerpetualPositions") or {}
            per_sub[num] = {
                "subaccount": num,
                "equity": equity,
                "free_collateral": float(s.get("freeCollateral", 0) or 0),
                "position_count": len(open_perps),
            }
            multi = len(open_perps) > 1
            for mkt, p in open_perps.items():
                sz = abs(float(p.get("size", 0)))
                signed = sz if p.get("side") == "LONG" else -sz  # sign like HL's szi
                mark, mmf = self._market_risk(mkt)
                liq = liq_dist = None
                if mark is None:
                    note = "liquidation unknown: market risk params unavailable"
                elif multi:
                    note = (f"liquidation unknown: {len(open_perps)} positions share"
                            f" cross-margin subaccount {num} — single-position"
                            " formula is not valid, this leg is unmonitored."
                            " Isolate coins via trading.dydx.subaccounts")
                else:
                    liq = liquidation_price(equity, signed, mark, mmf)
                    if liq is None:
                        note = ("not liquidatable by price alone (equity exceeds"
                                " notional)")
                    else:
                        liq_dist = abs(mark - liq) / mark * 100
                        note = None
                positions.append({
                    "coin": mkt, "size": signed, "side": p.get("side"),
                    "entry_px": p.get("entryPrice"),
                    "mark_px": mark,
                    "liquidation_px": liq,
                    "liq_distance_pct": liq_dist,
                    "liq_note": note,
                    "maintenance_margin_fraction": mmf,
                    "subaccount": num,
                    "subaccount_equity": equity,
                })
        # `subaccount` / `equity` / `free_collateral` stay at the top level for the
        # callers that predate isolation, reporting the PRIMARY subaccount (the one
        # asked for). Book-wide totals and the per-subaccount breakdown are additive,
        # so nothing that reads the old shape changes meaning.
        primary = next((x for x in subs
                        if x.get("subaccountNumber") == subaccount), subs[0])
        return {
            "venue": "dydx", "network": self.network,
            "address": self.account_address,
            "subaccount": primary.get("subaccountNumber"),
            "equity": float(primary.get("equity", 0) or 0),
            "free_collateral": float(primary.get("freeCollateral", 0) or 0),
            "equity_total": round(sum(v["equity"] for v in per_sub.values()), 6),
            "free_collateral_total": round(
                sum(v["free_collateral"] for v in per_sub.values()), 6),
            "subaccounts": per_sub,
            "isolated": bool(self.subaccount_map),
            "positions": positions,
            "open_positions": [p["coin"] for p in positions],
        }

    def open_orders(self, subaccount=0, market=None):
        """Open orders for a subaccount. Pass `market` to resolve the subaccount
        from the isolation map instead of assuming 0."""
        if market is not None:
            subaccount = self.subaccount_for(market)
        r = requests.get(
            f"{self.indexer}/v4/orders?address={self.account_address}"
            f"&subaccountNumber={subaccount}&status=OPEN", timeout=20)
        return r.json()

    def _api_key_hex(self):
        return self._api_key[2:] if self._api_key.startswith("0x") else self._api_key

    def oracle_price(self, ticker):
        md = requests.get(
            f"{self.indexer}/v4/perpetualMarkets?ticker={ticker}", timeout=20
        ).json()["markets"][ticker]
        return float(md["oraclePrice"])

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
        cap = check_order_cap(self.config, float(size) * float(price), reduce_only)
        if cap is not None:
            return {"submitted": False, "order": order, "gate": cap}
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
        sub = self.subaccount_for(market)
        order_id = mkt.order_id(self.account_address, sub, client_id,
                                OrderFlags.LONG_TERM)
        side = Order.Side.SIDE_BUY if is_buy else Order.Side.SIDE_SELL
        proto = mkt.order(order_id, OrderType.LIMIT, side, float(size), float(price),
                          Order.TimeInForce.TIME_IN_FORCE_UNSPECIFIED,
                          reduce_only=reduce_only, good_til_block_time=gtbt)
        resp = await node.place_order(wallet, proto, tx_options=tx_options)
        code = getattr(getattr(resp, "tx_response", resp), "code", None)
        return {"submitted": code == 0, "order": order, "tx_code": code,
                "client_id": client_id, "good_til_block_time": gtbt}

    async def place_market_reduce(self, market, is_buy, size, slippage=0.1):
        """Flatten/reduce a position with a SHORT_TERM IOC reduce-only order.

        dYdX rejects reduce_only on resting (stateful) orders (code 9003) — it
        requires IOC/FOK — so a close must use this short-term, immediately
        crossing path rather than place_order().
        """
        node = await self._node()
        mkt = self._market(market)
        wallet, tx_options = await self._signer(node)
        height = await node.latest_block_height()
        oracle = self.oracle_price(market)
        px = round(oracle * (1 + slippage) if is_buy else oracle * (1 - slippage))
        client_id = random.randint(0, MAX_CLIENT_ID)
        sub = self.subaccount_for(market)
        order_id = mkt.order_id(self.account_address, sub, client_id,
                                OrderFlags.SHORT_TERM)
        side = Order.Side.SIDE_BUY if is_buy else Order.Side.SIDE_SELL
        proto = mkt.order(order_id, OrderType.LIMIT, side, float(size), float(px),
                          Order.TimeInForce.TIME_IN_FORCE_IOC, reduce_only=True,
                          good_til_block=height + 10)
        resp = await node.place_order(wallet, proto, tx_options=tx_options)
        code = getattr(getattr(resp, "tx_response", resp), "code", None)
        return {"submitted": code == 0, "tx_code": code, "price": px,
                "client_id": client_id}

    async def cancel_order(self, market, client_id, good_til_block_time):
        """Cancel a stateful order by the client_id + gtbt returned from place."""
        node = await self._node()
        mkt = self._market(market)
        wallet, tx_options = await self._signer(node)
        order_id = mkt.order_id(self.account_address,
                                self.subaccount_for(market), int(client_id),
                                OrderFlags.LONG_TERM)
        resp = await node.cancel_order(
            wallet, order_id, good_til_block_time=int(good_til_block_time),
            tx_options=tx_options)
        code = getattr(getattr(resp, "tx_response", resp), "code", None)
        return {"cancelled": code == 0, "tx_code": code, "client_id": client_id}
