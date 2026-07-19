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

# Majors on dYdX: clobPairId BTC-USD=0, ETH-USD=1, SOL-USD=5 (testnet-verified).
MAJORS_CLOB_IDS = [0, 1, 5]
SUBACCOUNTS = [0]


def _bot_pubkey_bytes(bot_mnemonic):
    pub = KeyPair.from_mnemonic(bot_mnemonic).public_key_bytes
    if len(pub) == 65:
        pub = (b"\x02" if pub[64] % 2 == 0 else b"\x03") + pub[1:33]
    return pub


async def main(broadcast: bool):
    cfg = ExecutorConfig()
    network, creds = cfg.venue("dydx")
    if network != "testnet" and not broadcast:
        pass
    main_mnemonic = creds.get("mnemonic")
    if not main_mnemonic:
        sys.exit("No dydx mnemonic in config.")
    main_address = _address_from_mnemonic(main_mnemonic)

    # A fresh, dedicated bot key — the trade-only credential.
    from bip_utils import Bip39MnemonicGenerator, Bip39WordsNum
    bot_mnemonic = str(Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_24))
    bot_pub = _bot_pubkey_bytes(bot_mnemonic)

    auth = build_trading_authenticator(bot_pub, SUBACCOUNTS, MAJORS_CLOB_IDS)

    print(f"network        : {network}")
    print(f"main account   : {main_address}")
    print(f"scope          : place/cancel only, subaccounts {SUBACCOUNTS}, "
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
    print(f"\nSAVE THESE TO ainara.yaml under apis.dydx.{network}:")
    print("  bot_mnemonic:     <the 24 words below — trade-only key>")
    print(f"  authenticator_id: {new_ids[0] if new_ids else '<see ids above>'}")
    print(f"\n  {bot_mnemonic}\n")
    print("After saving, the MAIN mnemonic can be removed from config — the running"
          " bot only needs bot_mnemonic + authenticator_id + the main address.")


if __name__ == "__main__":
    asyncio.run(main("--broadcast" in sys.argv))
