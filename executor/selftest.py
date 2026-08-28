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

"""Executor self-test: validate credentials, read state, and confirm the order
gate refuses to submit by default. Places NO orders. Run:

    AINARA_CONFIG=<path> python -m executor.selftest
"""

import asyncio
import inspect
import json

from executor.config import ExecutorConfig
from executor.venues.dydx import DydxExecutor
from executor.venues.hyperliquid import HyperliquidExecutor


async def _maybe_await(value):
    """Adapters mix sync (HL SDK) and async (dYdX node) calls; normalize both."""
    return await value if inspect.isawaitable(value) else value


async def main():
    cfg = ExecutorConfig()
    print(f"config: {cfg.path}")
    print(f"jurisdiction_acknowledged: {cfg.jurisdiction_acknowledged()}\n")

    for Adapter in (HyperliquidExecutor, DydxExecutor):
        v = Adapter(cfg)
        name = v.__class__.__name__
        print(f"=== {name} ===")
        print("validate:", json.dumps(await _maybe_await(v.validate()), indent=2))
        try:
            print("state:   ", json.dumps(await _maybe_await(v.state()), indent=2))
        except Exception as e:
            print("state:    <error>", e)
        # Prove the safety gate WITHOUT placing anything: dry_run always refuses
        # to submit (it never reaches the venue). NEVER pass dry_run=False here —
        # on testnet the gate permits it and a real order would be placed.
        probe = await _maybe_await(v.place_order(
            *(("BTC", True, 0.001, 50000) if name == "HyperliquidExecutor"
              else ("BTC-USD", True, 0.001, 50000)),
            dry_run=True,
        ))
        print("order gate (dry_run, no submit):", json.dumps(probe["gate"], indent=2))
        print()


if __name__ == "__main__":
    asyncio.run(main())
