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
        "OPEN THE ON-SCREEN DASHBOARD — a rendered visual PANEL / UI page shown"
        " in the interface. Use ONLY when the user asks to SEE, VIEW, DISPLAY,"
        " PULL UP, OPEN, RENDER or WATCH something on screen / visually / as a"
        " dashboard or panel. Trigger phrases: show me the dashboard, open the"
        " dashboard, pull up the dashboard, display it visually, show it on"
        " screen, open the panel, visual aid, positions panel, dashboard view."
        " This skill draws a graphical view; it does NOT describe or summarize"
        " numbers in words — if the user just wants to be TOLD their status,"
        " funding, PnL or hedge health in text/speech, this is the WRONG skill"
        " and the text portfolio skill should be used instead. Read-only;"
        " renders data, never trades."
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
