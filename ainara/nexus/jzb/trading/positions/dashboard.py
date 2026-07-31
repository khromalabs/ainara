# Nexus bundle: jzb/trading
#
# Live view of the delta-neutral carry book. This skill is the DATA half; the
# rendering half is _components/PositionsDashboard/index.html, which the
# com-ring loads in a sandboxed iframe served from Orakle's own origin.
#
# Discovery contract (see ainara/framework/capabilities/nexus.py:69 and
# ainara/framework/capabilities/skills.py:282):
#   - file must be at <bundle>/<subdir>/<file>.py
#   - class name must be Vendor.capitalize() + Bundle.capitalize()
#     + Pascal(subdir) + Pascal(file)  ->  JzbTradingPositionsDashboard
#   - capability id is the snake_case of that -> jzb_trading_positions_dashboard
#   - component name is the id minus the "jzb_trading_" prefix, PascalCased
#     -> PositionsDashboard, which must exist as
#        <bundle>/_components/PositionsDashboard/
#
# Only when that directory exists does the provider set "ui_path" on the
# capability, and only then will GET /nexus/jzb/trading/<file> serve anything.
#
# Discovery happens at Orakle startup: restart Orakle after editing this file.

import json
import logging
from typing import Annotated, Literal

from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)


class JzbTradingPositionsDashboard(Skill):
    """Live dashboard of the delta-neutral hedge book. Read-only."""

    # Selectable by the LLM. It was hidden while it was only a probe, but the
    # whole point of the dashboard is that "show me my positions" opens it —
    # keeping it hidden made that request unroutable (the matcher never sees a
    # hidden capability), which is exactly the failure it was meant to prevent.
    # It only RENDERS read-only data, so exposing it moves no money. Its
    # matcher_info leans on visual verbs so plain status questions still fall to
    # `trading_portfolio` (text), while "show/open/pull up/display" reach here.
    hiddenCapability = False

    matcher_info = (
        "OPEN THE VISUAL POSITIONS DASHBOARD — render the delta-neutral positions"
        " as an on-screen graphical PANEL/UI: both legs, sizes, liquidation bars,"
        " PnL and funding side by side. This is the SEE-IT-ON-SCREEN skill. Route"
        " here for ANY request to SHOW, SEE, VIEW, DISPLAY, PULL UP, OPEN, RENDER,"
        " WATCH or LOOK AT the positions, delta-neutral positions, hedges, book,"
        " dashboard or panel — e.g. 'show me the dashboard', 'show me my"
        " positions', 'show me my delta-neutral positions', 'let me see the"
        " positions', 'can I see my positions', 'pull up the positions', 'view my"
        " hedges', 'display the book'. The VISUAL VERB is the trigger even when"
        " the user names the positions or the delta-neutral strategy. It draws a"
        " graphical view and does NOT speak or summarize numbers; if the user"
        " wants to be TOLD status, funding, PnL or hedge health in words ('how are"
        " my positions doing', 'am I hedged', 'what funding am I earning'), that"
        " is the text portfolio skill, not this. Read-only; renders data, never"
        " trades."
    )

    def run(
        self,
        coin: Annotated[
            str,
            "Which asset(s) to display. Default 'ALL' — the whole book side by"
            " side. Pass a single symbol (BTC, ETH, SOL) to narrow it.",
        ] = "ALL",
        action: Annotated[
            Literal["status"],
            "Only 'status' (live open positions) is rendered by this component.",
        ] = "status",
    ) -> str:
        """Return the live portfolio status as a JSON *string*.

        Nexus skills must return a string: the middleware does json.loads() on
        it (orakle_middleware.py:1117). The component then receives the decoded
        object via postMessage, already unwrapped by document-view.js:488.
        """
        # Imported here rather than at module scope: a failure to import the
        # trading stack should surface as a rendered error, not silently drop
        # the whole nexus bundle out of discovery at startup.
        try:
            from ainara.orakle.skills.trading.portfolio import TradingPortfolio
        except Exception as e:
            logger.exception("PositionsDashboard: cannot import TradingPortfolio")
            return json.dumps(
                {"error": f"trading_portfolio unavailable: {e}", "positions": []}
            )

        try:
            data = TradingPortfolio().run(action="status", coin=coin)
        except Exception as e:
            logger.exception("PositionsDashboard: portfolio status failed")
            return json.dumps(
                {"error": f"portfolio status failed: {e}", "positions": []}
            )

        # A single-coin status has no "positions" list; normalize so the
        # component only ever has to handle one shape.
        if isinstance(data, dict) and "positions" not in data:
            data = {
                "as_of": data.get("as_of"),
                "health": data.get("health"),
                "open_coins": [data.get("coin")] if data.get("coin") else [],
                "positions": [data],
                "scope": "single_coin",
                "verdict": data.get("verdict"),
            }

        return json.dumps(data, default=str)
