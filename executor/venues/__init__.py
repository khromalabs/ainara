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

"""Venue adapters, plus the price rounding both close paths must agree on."""

import math


def tick_decimals(tick):
    """Number of decimal places in a price tick (0.001 -> 3, 1.0 -> 0).

    Only used to clean the float residue left by multiplying a step count
    back out by the tick. Both venues quote decimal ticks for these markets.
    """
    text = ("%.12f" % float(tick)).rstrip("0")
    whole, _, frac = text.partition(".")
    return len(frac)


def cross_to_tick(price, is_buy, tick):
    """Snap a crossing limit price onto the venue's tick grid.

    A buy rounds up and a sell rounds down, so the order still crosses after
    rounding; rounding to nearest could leave it resting on the wrong side.

    The protective close paths used to call bare round(), which returns an
    integer. Under about $1 that is a limit of 0: a buy to close a short at 0
    never fills and the leg stays naked, and a sell to close a long at 0
    sweeps the book. Reduce-only orders skip the notional cap, so nothing
    downstream catches it.

    The input price is returned unrounded when the tick is missing or not
    positive, and also when rounding would produce a price that is not
    positive (a sell at 0.475 on a whole-dollar tick floors to 0). A venue can
    quantize an off-grid float or reject it loudly; a zero it will accept.
    """
    price = float(price)
    try:
        tick = float(tick) if tick else 0.0
    except (TypeError, ValueError):
        return price
    if tick <= 0:
        return price
    steps = price / tick
    # The 1e-9 keeps a price already on the grid from being pushed a whole
    # tick outward by division residue.
    n = math.ceil(steps - 1e-9) if is_buy else math.floor(steps + 1e-9)
    rounded = round(n * tick, tick_decimals(tick))
    return rounded if rounded > 0 else price
