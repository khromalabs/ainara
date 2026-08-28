"""Orakle skill — ask the Oreka engine what it would do, without doing it.

Drops into `ainara/orakle/skills/trading/`.

`dry_run` is NOT a parameter. A cycle run through this skill constructs and
evaluates everything and stops before submitting, and there is no value a caller
can pass to change that. Live trading is the CLI's job (`oreka run farm --live`),
where reaching an order takes a word a human typed on purpose. The README beside
this file explains why the add-on keeps a language model off the order path.
"""

import logging
from typing import Annotated, Any, Dict, Literal, Optional

from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)


class TradingOrekaSignal(Skill):
    """The carry engine's verdict, and what a cycle would do about it."""

    matcher_info = (
        "Use this skill to ask whether the Oreka delta-neutral desk should open or"
        " close a funding-carry position right now, and why. Reports the smoothed"
        " cross-venue funding spread, whether it clears the threshold, the size it"
        " would trade, and the fee and slippage check that can still refuse a"
        " profitable-looking spread. Evaluates only — it never submits an order."
        " Keywords: should I open, is there a trade, funding spread, carry edge,"
        " would the desk trade, why is it sitting out, should I close."
    )

    def __init__(self):
        super().__init__()
        self.name = "oreka_signal"
        self.logger = logging.getLogger(__name__)

    def run(
        self,
        action: Annotated[
            Literal["open", "close", "cycle_farm", "cycle_exit"],
            "'open' = should a NEW position be opened (the entry verdict)."
            " 'close' = should an OPEN position be closed (the exit verdict)."
            " 'cycle_farm' / 'cycle_exit' = run the full cycle end to end,"
            " including what the executor would do, but stopping before"
            " submission. Use the cycle forms when the user wants to know what"
            " would actually happen; use open/close for just the decision.",
        ] = "open",
        coin: Annotated[
            str, "Which asset to evaluate, e.g. BTC, ETH, SOL."] = "BTC",
        capital_usd: Annotated[
            Optional[float],
            "For 'open': capital to size against. Omit to use the desk's"
            " configured default; the margin rule and notional cap bound the"
            " result either way.",
        ] = None,
    ) -> Dict[str, Any]:
        """Evaluate. Never submits, whatever is asked of it."""
        try:
            from oreka.engine import TradingCarryEngine
        except ImportError as e:
            return _not_installed(e)

        try:
            if action in ("open", "close"):
                engine = TradingCarryEngine()
                if action == "open":
                    kwargs = {"coin": coin}
                    if capital_usd is not None:
                        kwargs["capital_usd"] = capital_usd
                    return {"verdict": engine.decide(**kwargs), "submitted": False}
                return {"verdict": engine.decide_exit(coin=coin),
                        "submitted": False}

            from oreka import runner
            fn = runner.farm if action == "cycle_farm" else runner.exit_
            kwargs = {"coin": coin, "dry_run": True}   # not a parameter, on purpose
            if action == "cycle_farm" and capital_usd is not None:
                kwargs["capital_usd"] = capital_usd
            out = fn(**kwargs)
            return {"verdict": out.get("verdict"), "result": out.get("result"),
                    "report": out.get("report"), "submitted": False}
        except Exception as e:
            self.logger.warning("oreka_signal %s failed: %s", action, e)
            return {"error": f"could not evaluate: {type(e).__name__}: {e}",
                    "action": action, "coin": coin, "submitted": False}


def _not_installed(exc):
    return {
        "error": "Oreka is not installed in this environment, so the engine"
                 " cannot be asked. Install it into the environment Orakle runs"
                 f" in (pip install -e <oreka>). Import failed with: {exc}",
        "installed": False,
        "submitted": False,
    }
