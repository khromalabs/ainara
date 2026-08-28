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

"""dYdX v4 permissioned-key (authenticator) support.

Lets the bot trade with a DEDICATED key that can ONLY place/cancel orders, ONLY on
chosen subaccounts, ONLY on chosen markets — and cannot withdraw or transfer. The
main wallet's mnemonic is needed once (to register the authenticator) and never by
the running bot.

Flow:
  1. build_trading_authenticator(bot_pubkey, subaccounts, clob_pair_ids)
  2. await register(node, main_wallet, authenticator)      # signed by MAIN wallet
  3. await find_authenticator_ids(node, main_address)       # discover assigned id
  4. bot signs orders with TxOptions(authenticators=[id], ...)  (see dydx.py)
"""

import logging

from dydx_v4_client.node.authenticators import Authenticator, AuthenticatorType

logger = logging.getLogger(__name__)

# dYdX Cosmos message type URLs the bot is allowed to send.
MSG_PLACE_ORDER = "/dydxprotocol.clob.MsgPlaceOrder"
MSG_CANCEL_ORDER = "/dydxprotocol.clob.MsgCancelOrder"


def build_trading_authenticator(bot_pubkey: bytes, subaccounts, clob_pair_ids):
    """Compose a trade-only authenticator scoped to given subaccounts/markets.

    Semantics (AllOf): the tx must be signed by *bot_pubkey* AND be a place- or
    cancel-order message AND target one of *subaccounts* AND one of *clob_pair_ids*.
    No other message type (withdraw/transfer/send) can pass.
    """
    return Authenticator.compose(
        AuthenticatorType.AllOf,
        [
            Authenticator.signature_verification(bot_pubkey),
            Authenticator.compose(
                AuthenticatorType.AnyOf,
                [
                    Authenticator.message_filter(MSG_PLACE_ORDER),
                    Authenticator.message_filter(MSG_CANCEL_ORDER),
                ],
            ),
            Authenticator.subaccount_filter(list(subaccounts)),
            Authenticator.clob_pair_id_filter(list(clob_pair_ids)),
        ],
    )


async def register(node, main_wallet, authenticator):
    """Register *authenticator* on the main account (signed by the main wallet)."""
    return await node.add_authenticator(main_wallet, authenticator)


async def find_authenticator_ids(node, address):
    """Return the list of authenticator ids currently registered for *address*."""
    resp = await node.get_authenticators(address)
    return [a.id for a in resp.account_authenticators]
