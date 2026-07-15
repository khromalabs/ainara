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

"""Jurisdiction acknowledgement gate for order-placing trading skills.

WHAT THIS IS: a NOTICE. It forces an operator to read the restriction and make an
explicit, deliberate configuration change before any skill can place an order.

WHAT THIS IS NOT: a compliance control, legal advice, or any form of protection.
It does not verify anything. An operator who acknowledges falsely is in exactly the
same position they would be in without it. Do not mistake this for a licence to
trade, and do not weaken it into a default-on flag.

Read-only market-data skills (hyperliquid, dydx, carry_engine) deliberately do NOT
call this: reading public market data is a different activity from trading.

Both venues currently supported prohibit use by persons in restricted
jurisdictions, and both expressly forbid using a VPN or any other technology to
conceal location, and forbid false statements about residency or citizenship:

  - Hyperliquid: Restricted Persons include those who reside in, are located in,
    are incorporated in, or have a registered office in the United States of
    America or Ontario, Canada, plus sanctioned territories.
  - dYdX v4: restricted persons include those who reside in, are located in, are
    incorporated in, have a registered office or principal place of business in,
    OR ARE OPERATED OR CONTROLLED FROM, the United States, Canada or the United
    Kingdom. Each access to the software is an affirmative confirmation that you
    are not a Restricted Person.

Operators must consult the venues' current terms themselves; the summary above is
a convenience, not a substitute, and terms change.
"""

CONFIG_KEY = "trading.jurisdiction_acknowledged"

NOTICE = (
    "REFUSED: order placement is disabled.\n"
    "\n"
    "Hyperliquid and dYdX both prohibit use by persons in restricted"
    " jurisdictions (including, but not limited to, the United States), and both"
    " expressly forbid using a VPN or any other means to conceal your location,"
    " and forbid false statements about your residency or citizenship.\n"
    "\n"
    f"To enable order placement, set `{CONFIG_KEY}: true` in ainara.yaml. By doing"
    " so you represent that you are not a restricted person, that you are not"
    " concealing your location, and that you have read the venues' current terms.\n"
    "\n"
    "This flag is a notice, not a compliance control, and confers no permission or"
    " protection. If you are unsure whether you may lawfully trade these products,"
    " you are not ready to set it."
)


def jurisdiction_acknowledged(config) -> bool:
    """True only when the operator has explicitly opted in. Defaults to False."""
    return config.get(CONFIG_KEY, False) is True


def require_jurisdiction_ack(config):
    """Return an error dict when not acknowledged, or None when clear to proceed.

    Call this at the top of every skill action that can place, modify or cancel an
    order. Never call it for read-only market data.
    """
    if jurisdiction_acknowledged(config):
        return None
    return {"error": NOTICE, "refused": "jurisdiction_not_acknowledged"}
