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

"""One-time setup: register a scoped, trade-only permissioned key on the dYdX
account, so the running bot never holds the main wallet's mnemonic.

    DRY (default): generate the bot key, compose the authenticator, verify node
        connectivity and main-wallet construction. Broadcasts NOTHING.
    --broadcast:   additionally register the authenticator on-chain (signed by
        the MAIN wallet; needs gas) and print the config values to save.

    AINARA_CONFIG=<path> python -m executor.setup_dydx_permission [--broadcast]
"""

import asyncio
import os
import sys

from dydx_v4_client.key_pair import KeyPair
from dydx_v4_client.node.client import NodeClient
from dydx_v4_client.wallet import Wallet

from executor.config import ExecutorConfig
from executor.venues.dydx import _address_from_mnemonic, dydx_network
from executor.venues.dydx_permissioned import (
    build_trading_authenticator,
    find_authenticator_ids,
    register,
)

# dYdX clobPairId per market: BTC-USD=0, ETH-USD=1, SOL-USD=5, HYPE-USD=319.
# NOTE: hardcoded for now — the "add any token" work will derive these from the
# configured coin map via the indexer so a new market needs no code edit.
MAJORS_CLOB_IDS = [0, 1, 5, 319]


# How many subaccounts to authorize by default. An authenticator is IMMUTABLE — the
# protocol has add/remove and no edit — so every change of scope means registering a
# new one, signed by the account owner, which means handling the main mnemonic again.
# Authorizing a small range up front makes that a one-time event: adding a fourth coin
# later becomes a config edit instead of another on-chain grant with your seed out.
#
# The wider grant costs approximately nothing. The scope still only permits
# place/cancel, still only in subaccounts of an account you own, and still cannot
# transfer or withdraw — so the worst a leaked bot key gains from the extra range is
# the ability to place orders in an empty subaccount it could already place in one.
DEFAULT_AUTHORIZED_SUBACCOUNTS = 6  # 0..5


def authorized_subaccounts(cfg):
    """Subaccounts the bot key may trade in.

    The authenticator is composed AllOf, so `subaccount_filter` is a HARD on-chain
    allowlist — an order aimed at a subaccount outside it is REJECTED by the chain,
    not merely discouraged. Position isolation routes ETH to subaccount 1 and SOL to
    2 (trading.dydx.subaccounts), so a key scoped to [0] silently makes every
    isolated coin unopenable, and finds that out mid-hedge with the short leg on.

    Resolution order:
      1. `trading.dydx.authorized_subaccounts` — an explicit list, if you want to
         pin the grant exactly.
      2. `trading.dydx.authorize_count` (default 6) — authorize 0..n-1, covering
         today's coins and headroom for the next few.

    Always a superset of the isolation map, so the on-chain scope and the routing
    cannot drift apart, and always includes 0 (the default for unmapped coins and
    where collateral arrives).
    """
    mapped = {int(v) for v in
              (cfg.get("trading.dydx.subaccounts", {}) or {}).values()}
    explicit = cfg.get("trading.dydx.authorized_subaccounts")
    if explicit:
        return sorted({0, *mapped, *(int(v) for v in explicit)})
    count = int(cfg.get("trading.dydx.authorize_count",
                        DEFAULT_AUTHORIZED_SUBACCOUNTS))
    return sorted({0, *mapped, *range(max(count, 1))})


def _compress(pub):
    if len(pub) == 65:
        return (b"\x02" if pub[64] % 2 == 0 else b"\x03") + pub[1:33]
    return pub


def _bot_pubkey_bytes(bot_mnemonic):
    return _compress(KeyPair.from_mnemonic(bot_mnemonic).public_key_bytes)


def existing_bot_pubkey(creds):
    """Public key of the bot credential already in config, or (None, None).

    Re-registration should widen the SCOPE, not rotate the key. This script used to
    mint a fresh mnemonic on every run, so adding subaccounts 1 and 2 to the
    on-chain allowlist would also swap agent_private_key and bot_mnemonic — three
    config fields to update instead of one, and a stretch where it is unclear which
    credential the running bot is actually presenting.

    Derives from agent_private_key, because that is the key that actually signs
    orders; bot_mnemonic is the backup form of the same key.
    """
    k = creds.get("agent_private_key")
    if k:
        k = k[2:] if k.startswith("0x") else k
        return _compress(KeyPair.from_hex(k).public_key_bytes), "agent_private_key"
    m = creds.get("bot_mnemonic")
    if m:
        return _bot_pubkey_bytes(m), "bot_mnemonic"
    return None, None


async def verify():
    """Read-only: does the CONFIGURED authenticator actually cover the coin map?

    No mnemonic, no gas, no signature. This is the check that closes the loop after
    a --broadcast: the routing lives in ainara.yaml while the permission lives
    on-chain, and nothing else compares the two. Get it wrong and the failure
    arrives mid-hedge, as an on-chain rejection with the other leg already open.
    """
    import base64
    import re

    def subaccount_scope(blob):
        """Subaccounts a composed authenticator permits, or None if unreadable.

        MUST key on the field TYPE. A composed authenticator carries both a
        SubaccountFilter and a ClobPairIdFilter, and both encode as a
        comma-separated digit list — so "take the last digit list" silently reports
        the MARKET filter (0,1,5 for BTC/ETH/SOL) as if it were the subaccount
        scope, and the two happen to look equally plausible.
        """
        m = re.search(
            r'"type"\s*:\s*"[^"]*SubaccountFilter[^"]*"\s*,\s*'
            r'"config"\s*:\s*"([A-Za-z0-9+/=]*)"', blob)
        if not m:
            return None
        try:
            decoded = base64.b64decode(m.group(1)).decode("utf-8", "replace")
        except Exception:
            return None
        if not re.fullmatch(r"[0-9]+(,[0-9]+)*", decoded or ""):
            return None
        return sorted(int(x) for x in decoded.split(","))

    cfg = ExecutorConfig()
    network, creds = cfg.venue("dydx")
    address = creds.get("account_address")
    configured_id = creds.get("authenticator_id")
    want = authorized_subaccounts(cfg)
    mapped = cfg.get("trading.dydx.subaccounts", {}) or {}

    node = await NodeClient.connect(
        dydx_network(network, creds.get("node_url")).node)
    resp = await node.get_authenticators(address)

    print(f"account          : {address}")
    print(f"config id        : {configured_id}")
    print(f"coin map         : {mapped or '(unset — everything uses subaccount 0)'}")
    print(f"needs subaccounts: {want}\n")

    found, covers = None, []
    for a in resp.account_authenticators:
        subs = subaccount_scope(bytes(a.config).decode("utf-8", "replace"))
        marker = " <- config points here" if str(a.id) == str(configured_id) else ""
        ok = subs is not None and all(s in subs for s in want)
        if ok and str(a.id) != str(configured_id):
            covers.append(a.id)
        print(f"  id {a.id}: subaccounts {subs if subs is not None else '?'}"
              f"{'  (covers the map)' if ok else ''}{marker}")
        if str(a.id) == str(configured_id):
            found = subs

    print()
    if found is None:
        print("RESULT: could not read the configured authenticator's scope."
              " Is authenticator_id correct?")
        return
    missing = [s for s in want if s not in found]
    if missing:
        print(f"RESULT: NOT READY — subaccounts {missing} are routed to but NOT"
              f" authorized by authenticator {configured_id}. Orders for those coins"
              f" would be REJECTED on-chain.")
        if covers:
            print(f"        But authenticator {covers[0]} DOES cover them. Set"
                  f" apis.dydx.{network}.authenticator_id: {covers[0]} and restart"
                  f" the executor daemon + watchdog. No broadcast needed.")
        else:
            print("        Re-run with --broadcast, then set authenticator_id to"
                  " the new id.")
    else:
        print("RESULT: OK — every subaccount the config routes to is authorized."
              " Restart the executor daemon and watchdog if you just changed the id.")


async def main(broadcast: bool, rotate: bool = False):
    cfg = ExecutorConfig()
    network, creds = cfg.venue("dydx")

    # Prefer the env var: this is the MAIN wallet key — it can withdraw, which is
    # exactly the authority the permissioned-key setup exists to keep out of the
    # running bot. It is needed here only to SIGN the registration, once.
    #
    # Keeping it out of ainara.yaml matters concretely: ConfigManager.save()
    # copies the config to ainara.yaml.bak before writing, and Orakle exposes
    # PUT /config — so a save while the mnemonic is in the file leaves a copy in
    # .bak that survives deleting it from the original.
    main_mnemonic = os.environ.get("DYDX_MAIN_MNEMONIC") or creds.get("mnemonic")
    if not main_mnemonic:
        sys.exit(
            "No dydx main mnemonic.\n"
            "  Preferred (never touches disk), in the shell you run this from:\n"
            "    $env:DYDX_MAIN_MNEMONIC = 'word word ...'\n"
            "  It disappears when that terminal closes.\n"
            "  Fallback: apis.dydx.<network>.mnemonic in ainara.yaml — if you use\n"
            "  this, delete BOTH ainara.yaml and ainara.yaml.bak afterwards."
        )
    source = ("env DYDX_MAIN_MNEMONIC" if os.environ.get("DYDX_MAIN_MNEMONIC")
              else "ainara.yaml (consider the env var instead)")
    main_address = _address_from_mnemonic(main_mnemonic)
    print(f"main key source: {source}")

    # Refuse unless the seed derives the account we are configured to trade. Without
    # this the script authenticates whatever the seed happens to own: supplying the
    # BOT's mnemonic derived the bot's own address and got "account not found" from
    # the chain (it has never transacted — it signs on behalf of the main account),
    # and a seed that HAD transacted would have registered an authenticator on the
    # wrong account, spending gas to grant access to something the bot does not use.
    # fund_subaccounts has had this guard from the start; this script did not.
    configured = creds.get("account_address")
    if configured and main_address != configured:
        hint = ""
        if creds.get("bot_mnemonic") and \
                _address_from_mnemonic(creds["bot_mnemonic"]) == main_address:
            hint = ("\n  That is your BOT mnemonic (apis.dydx.%s.bot_mnemonic). The"
                    " bot key cannot\n  grant its own permissions — this step needs"
                    " the wallet that OWNS the account." % network)
        sys.exit(
            f"WRONG SEED — refusing before signing anything.\n"
            f"  it derives      : {main_address}\n"
            f"  config expects  : {configured}"
            f"{hint}\n"
            f"  Set DYDX_MAIN_MNEMONIC to the secret phrase for {configured}."
        )

    # Reuse the trade-only credential already in config; --rotate-key forces a new
    # one (first-time setup, or a key believed compromised). Widening the subaccount
    # scope is not a reason to change keys.
    bot_mnemonic = None
    bot_pub, key_source = (None, None) if rotate else existing_bot_pubkey(creds)
    if bot_pub is None:
        from bip_utils import Bip39MnemonicGenerator, Bip39WordsNum
        bot_mnemonic = str(
            Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_24))
        bot_pub = _bot_pubkey_bytes(bot_mnemonic)
        key_source = "NEWLY GENERATED — save the words printed at the end"
    print(f"bot key        : {key_source}")

    subaccounts = authorized_subaccounts(cfg)
    auth = build_trading_authenticator(bot_pub, subaccounts, MAJORS_CLOB_IDS)

    print(f"network        : {network}")
    print(f"main account   : {main_address}")
    print(f"scope          : place/cancel only, subaccounts {subaccounts}, "
          f"markets(clobPairId) {MAJORS_CLOB_IDS}")
    print(f"authenticator  : {auth.todict().get('type')} (trade-only, no withdraw/transfer)")

    # Was: TESTNET.node if testnet else None — i.e. mainnet registration could
    # never work. Share the adapter's network resolution so both agree.
    node = await NodeClient.connect(
        dydx_network(network, creds.get("node_url")).node
    )
    # Construct the main wallet (reads account number/sequence — no broadcast).
    main_wallet = await Wallet.from_mnemonic(node, main_mnemonic, main_address)
    print(f"node connected : yes  (main wallet account_number="
          f"{main_wallet.account_number}, sequence={main_wallet.sequence})")

    existing = await find_authenticator_ids(node, main_address)
    print(f"existing authenticator ids: {existing or 'none'}")

    if not broadcast:
        print("\nDRY RUN — nothing broadcast. Re-run with --broadcast to register.")
        return

    print("\nBROADCASTING authenticator registration (signed by main wallet)...")
    resp = await register(node, main_wallet, auth)
    print("  tx response code:", getattr(getattr(resp, 'tx_response', resp), 'code', resp))
    ids_after = await find_authenticator_ids(node, main_address)
    new_ids = [i for i in ids_after if i not in existing]
    print(f"  authenticator ids now: {ids_after}  (new: {new_ids})")
    print(f"\nSAVE THIS TO ainara.yaml under apis.dydx.{network}:")
    print(f"  authenticator_id: {new_ids[0] if new_ids else '<see ids above>'}")
    if bot_mnemonic:
        print("  bot_mnemonic:     <the 24 words below — trade-only key>")
        print(f"\n  {bot_mnemonic}\n")
        print("After saving, the MAIN mnemonic can be removed from config — the"
              " running bot only needs bot_mnemonic + authenticator_id + the main"
              " address.")
    else:
        print("  (bot key UNCHANGED — same agent_private_key. Only the scope and"
              " the authenticator id are new.)")
    print("\nThe OLD authenticator still exists and still works, so nothing breaks"
          " until you switch the id. Restart the executor daemon and watchdog after"
          " saving, so they present the new one.")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        asyncio.run(verify())
    else:
        asyncio.run(main("--broadcast" in sys.argv, "--rotate-key" in sys.argv))
