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

"""Shared executor exceptions. Stdlib-only, so watchdog.py can import it."""


class VenueStateUnavailable(RuntimeError):
    """The venue's position state could not be READ.

    Emphatically NOT the same as "the venue holds nothing", and the whole reason
    this type exists is that the two used to be indistinguishable.

    dydx.state() called `r.json().get("subaccounts")` with no status check, and
    returned a dict with no "positions" key for anything unexpected — a 429
    rate-limit body, a 5xx, a degraded response. Callers read
    `state.get("positions") or []` and concluded the account was FLAT.

    On 2026-07-27 that turned three fully-hedged coins into three "broken hedges":
    the watchdog flattened every Hyperliquid leg at 18:34 UTC, and because the
    dYdX read stayed broken it could not see the three long legs it had just
    stranded. They ran unhedged for eight hours until the reads recovered, which
    cost ~$4.64 against a hedge that had been flat to +$0.08 while intact.

    Anything that consumes venue state MUST treat this as "unknown" and refuse to
    take destructive action on it. Never as "flat".
    """
