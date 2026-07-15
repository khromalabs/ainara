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

"""Layered gate for order SUBMISSION in the executor daemon.

This is defense-in-depth: the Orakle-side skill also gates before ever calling
the daemon, and the daemon re-checks here so it can never submit an order that
the layers below would have refused.

Gates, in order:
  1. dry_run  -> never submits; constructs/signs only. Default True.
  2. testnet  -> submission allowed (play money); jurisdiction ack NOT required.
  3. mainnet  -> submission requires trading.jurisdiction_acknowledged: true.

The jurisdiction flag is a NOTICE, not a compliance control (see the Orakle-side
_compliance.py). It confers no permission or protection.
"""


def check_submission(config, network, dry_run):
    """Return None if submission may proceed, else a refusal dict.

    Callers must treat a non-None return as a hard stop.
    """
    if dry_run:
        return {
            "refused": "dry_run",
            "detail": "dry_run is enabled; order was constructed but not submitted.",
        }
    if network == "testnet":
        return None
    if network == "mainnet":
        if config.jurisdiction_acknowledged():
            return None
        return {
            "refused": "jurisdiction_not_acknowledged",
            "detail": (
                "Mainnet submission requires trading.jurisdiction_acknowledged: true."
                " Both venues prohibit restricted-jurisdiction use and forbid VPNs"
                " and false residency statements. This flag is a notice, not a"
                " compliance control."
            ),
        }
    return {"refused": "unknown_network", "detail": f"Unknown network '{network}'."}
