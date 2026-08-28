"""Orakle skill — read the Oreka desk's book.

Drops into `ainara/orakle/skills/trading/`. Read-only: it reports positions and
history and cannot place, cancel or modify an order. See the README beside this
file for why the add-on draws that line where it does.
"""

import logging
from typing import Annotated, Any, Dict, Literal, Optional

from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)


class TradingOrekaDesk(Skill):
    """Live and historical view of the Oreka delta-neutral desk."""

    matcher_info = (
        "Use this skill to report on the Oreka delta-neutral funding-carry desk:"
        " open hedged positions across Hyperliquid and dYdX, hedge health,"
        " liquidation distance, funding earned, closed round trips, and whether"
        " the strategy realized the edge it predicted. Read-only; it never places"
        " an order. Keywords: my book, my positions, delta neutral, carry desk,"
        " hedge health, funding earned, realized pnl, how is the desk doing."
    )

    def __init__(self):
        super().__init__()
        self.name = "oreka_desk"
        self.logger = logging.getLogger(__name__)

    def run(
        self,
        action: Annotated[
            Literal["status", "review", "analytics"],
            "'status' = positions open right now, with hedge health, liquidation"
            " distance and the funding each leg is paying or receiving."
            " 'review' = closed round trips reconstructed from venue history."
            " 'analytics' = each recorded trade's PREDICTED edge against what it"
            " actually realized, which is the one that answers whether the model"
            " is right rather than whether the plumbing works.",
        ] = "status",
        coin: Annotated[
            str,
            "Which asset(s). Default 'ALL' — the whole book at once; use it"
            " whenever the user does not name one specific asset. Pass a single"
            " symbol (BTC, ETH, SOL, ...) ONLY when they explicitly ask about that"
            " one. Do NOT default to BTC.",
        ] = "ALL",
        lookback_days: Annotated[
            Optional[float],
            "For 'review': how far back to reconstruct closed trades. Leave unset"
            " unless the user names a period - the default is derived from the"
            " strategy's own expected hold (at least 90 days), and a shorter"
            " window cannot see a completed trade at all.",
        ] = None,
    ) -> Dict[str, Any]:
        """Report the desk's book. Places no orders and signs nothing."""
        try:
            from oreka.portfolio import TradingPortfolio
        except ImportError as e:
            return _not_installed(e)

        try:
            return TradingPortfolio().run(
                action=action, coin=coin, lookback_days=lookback_days)
        except Exception as e:
            # A read that failed is reported as a failure. It must never come
            # back looking like an empty book, which reads as "you hold nothing".
            self.logger.warning("oreka_desk %s failed: %s", action, e)
            return {"error": f"could not read the desk: {type(e).__name__}: {e}",
                    "action": action, "coin": coin}


def _not_installed(exc):
    return {
        "error": "Oreka is not installed in this environment, so the desk cannot"
                 " be read. Install it into the environment Orakle runs in"
                 f" (pip install -e <oreka>). Import failed with: {exc}",
        "installed": False,
    }
