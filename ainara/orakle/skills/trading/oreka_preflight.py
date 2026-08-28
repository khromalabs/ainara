"""Orakle skill — the Oreka desk's preflight.

Drops into `ainara/orakle/skills/trading/`. Every check is read-only; nothing
here can place, cancel or modify an order.

Worth knowing when reading the result: preflight prefers what the RUNNING daemon
reports over what the YAML says, because services read their config once at
startup. "I set it to mainnet" and "it is on mainnet" are different claims, and
the gap between them is what this catches.
"""

import logging
from typing import Annotated, Any, Dict

from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)


class TradingOrekaPreflight(Skill):
    """Is the desk configured, credentialled and guarded the way you think?"""

    matcher_info = (
        "Use this skill to check whether the Oreka delta-neutral desk is healthy"
        " and safe to run: config resolution, venue credentials verified at the"
        " venue, which network each venue is really on, the dry-run and"
        " jurisdiction gates, size caps, the daemon, and whether the watchdog is"
        " alive and raising anything. Read-only. Keywords: is my desk ok, desk"
        " health, preflight, doctor, is the watchdog running, am I safe to trade,"
        " check my trading setup."
    )

    def __init__(self):
        super().__init__()
        self.name = "oreka_preflight"
        self.logger = logging.getLogger(__name__)

    def run(
        self,
        verbose: Annotated[
            bool,
            "True returns every check. False (default) returns only failures and"
            " warnings plus the counts, which is what someone asking 'is it ok?'"
            " actually wants.",
        ] = False,
    ) -> Dict[str, Any]:
        """Run the preflight and summarise it. Touches no order path."""
        try:
            from oreka import doctor
        except ImportError as e:
            return _not_installed(e)

        try:
            checks = doctor.run_checks()
        except Exception as e:
            self.logger.warning("oreka_preflight failed: %s", e)
            return {"error": f"preflight could not run: {type(e).__name__}: {e}",
                    "healthy": None}

        rows = [{"check": c.name, "status": c.status, "detail": c.detail}
                for c in checks]
        failed = [r for r in rows if r["status"] == doctor.FAIL]
        warned = [r for r in rows if r["status"] == doctor.WARN]

        # `healthy` is False on any failure, never None-as-false: an unknown and a
        # known-bad must not read alike to whatever renders this.
        return {
            "healthy": not failed,
            "failures": len(failed),
            "warnings": len(warned),
            "summary": (
                f"{len(failed)} failed, {len(warned)} warning(s)" if failed
                else f"no failures, {len(warned)} warning(s)" if warned
                else "all checks passed"),
            "needs_attention": failed + warned,
            "checks": rows if verbose else None,
            "note": ("Warnings are often states you intended - mainnet, a gate you"
                     " opened on purpose. Read them rather than counting them."),
        }


def _not_installed(exc):
    return {
        "error": "Oreka is not installed in this environment, so the preflight"
                 " cannot run. Install it into the environment Orakle runs in"
                 f" (pip install -e <oreka>). Import failed with: {exc}",
        "installed": False,
        "healthy": None,
    }
