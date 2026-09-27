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
  3. mainnet  -> submission requires trading.jurisdiction_acknowledged: true,
                 except for reduce-only orders (see check_submission).

The jurisdiction flag is a NOTICE, not a compliance control (see the Orakle-side
_compliance.py). It confers no permission or protection.
"""


# Code defaults for the two sizing limits, equal to what
# docs/ainara.trading.example.yaml ships. They were looser (no hard cap, and no
# margin rule at all in the daemon), so a config written by hand instead of
# from the template silently ran with far more at risk. An explicit null in
# the config still means "no limit": that is a choice, an absent key is not.
# carry_engine.py keeps its own copy because it runs in the other virtualenv.
DEFAULT_MAX_ORDER_NOTIONAL_USD = 100.0
DEFAULT_MAX_ACCOUNT_MARGIN_PCT = 20.0


def check_order_cap(config, notional_usd, reduce_only):
    """Refuse an OPENING order whose USD notional exceeds the configured cap.

    Deterministic hard ceiling, enforced in the daemon regardless of what the
    carry engine sized or an LLM agent requested. Reduce-only / closing orders are
    NEVER capped — a size limit must never be able to trap you in a naked leg.

    Cap: trading.executor.max_order_notional_usd (unset =
    DEFAULT_MAX_ORDER_NOTIONAL_USD; an explicit null = no cap).
    Returns None to proceed, or a refusal dict.
    """
    if reduce_only:
        return None
    cap = config.get("trading.executor.max_order_notional_usd",
                     DEFAULT_MAX_ORDER_NOTIONAL_USD)
    if cap is None:
        return None
    try:
        cap = float(cap)
    except (TypeError, ValueError):
        return None
    if notional_usd > cap:
        return {
            "refused": "order_exceeds_max_notional",
            "detail": (
                f"order notional ${notional_usd:,.2f} exceeds the configured cap "
                f"${cap:,.2f} (trading.executor.max_order_notional_usd)."
            ),
        }
    return None


def check_submission(config, network, dry_run, reduce_only=False):
    """Return None if submission may proceed, else a refusal dict.

    Callers must treat a non-None return as a hard stop.

    `reduce_only` orders skip the mainnet jurisdiction gate, the same way
    check_order_cap never caps them: the gate exists to stop NEW exposure, and
    refusing a close only strands whatever is already open. Before this, the
    Hyperliquid close went through the gate and the dYdX close did not call
    it at all, so a watchdog flatten without the acknowledgement closed one
    leg and was refused on the other, turning a hedge into a naked position.

    `dry_run` still refuses reduce-only orders. It means "do not touch the
    venue", not "stay under a limit".
    """
    if dry_run:
        return {
            "refused": "dry_run",
            "detail": "dry_run is enabled; order was constructed but not submitted.",
        }
    if network == "testnet":
        return None
    if network == "mainnet":
        if reduce_only or config.jurisdiction_acknowledged():
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
