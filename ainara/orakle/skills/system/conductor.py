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

"""Run Ainara Conductor plans on request — the same plans the scheduler crons.

Why this exists: plans were reachable only from the CLI
(`scheduler.py --run-plan`), so asking Ainara to "open the BTC carry" meant she
called the individual skills herself instead. That bypasses the whole plan
machinery — the deterministic step order, the `avoid_step_if` gates, the `avoid_if`
interlocks that stop an exit racing a mid-open entry, and the ledger write. The
skills are the parts; the plan is the assembly.

WHAT THIS DOES AND DOES NOT HAND THE LLM
----------------------------------------
It triggers a plan. It cannot compose one, reorder its steps, or place an order.
Every gate inside the plan still applies, and for the trading plans that means the
carry engine's own `sit_out` verdict, the executor daemon's dry_run / network /
jurisdiction gate, the per-order notional cap, and the refuse-unless-flat check —
none of which this skill can reach past. So the model chooses WHICH plan and WHICH
coin; the plan itself remains deterministic code. That is a deliberately narrower
authority than "let the LLM place trades", and it is the reason this is acceptable
on a path that moves money.

It is still a real escalation, so it is OFF by default: a plan must be named in
`bureau.plan_runner.allowed_plans` before it can be triggered. An unset allowlist
refuses everything and says so.
"""

import logging
from typing import Annotated, Any, Dict, List, Literal, Optional

import requests

from ainara.framework.config import config
from ainara.framework.skill import Skill


class SystemConductor(Skill):
    """Trigger and inspect Ainara Conductor plans via the Bureau API."""

    matcher_info = (
        "Use this skill to RUN a named Ainara automation plan (Conductor plan) on"
        " demand, or to list which plans exist and which are runnable. This is how"
        " a multi-step routine is executed as a whole rather than by calling its"
        " individual skills one at a time — it preserves the plan's step order and"
        " its safety gates. For the delta-neutral funding carry that means"
        " 'delta_neutral_farm' to evaluate-and-open a hedge and"
        " 'delta_neutral_exit' to evaluate-and-close one, per coin. Keywords: run"
        " plan, run the routine, trigger automation, open the carry, farm the"
        " funding, run the exit check, conductor plan, list plans."
    )

    def __init__(self):
        super().__init__()
        self.name = "conductor"
        self.logger = logging.getLogger(__name__)
        self.base_url = config.get(
            "apis.bureau.url", "http://127.0.0.1:8010"
        ).rstrip("/")
        self.timeout = float(config.get("apis.bureau.timeout", 30))

    # ------------------------------------------------------------------
    def _allowed(self) -> List[str]:
        """Plans this skill may trigger. Empty = refuse everything.

        Deny-by-default on purpose. Some plans place live orders, so the operator
        opts each one in by name rather than the model being able to reach anything
        the Conductor happens to have loaded.
        """
        raw = config.get("bureau.plan_runner.allowed_plans", []) or []
        return [str(p) for p in raw]

    def _refusal(self, plan: str) -> Dict[str, Any]:
        allowed = self._allowed()
        if not allowed:
            return {
                "ran": False,
                "refused": "plan_runner_not_configured",
                "detail": (
                    "No plans are allowed to be triggered this way. Add them to"
                    " bureau.plan_runner.allowed_plans in ainara.yaml, e.g."
                    " [delta_neutral_farm, delta_neutral_exit]. Until then this"
                    " skill can only 'list'."
                ),
            }
        return {
            "ran": False,
            "refused": "plan_not_allowed",
            "detail": (
                f"'{plan}' is not in bureau.plan_runner.allowed_plans."
                f" Allowed: {', '.join(allowed)}."
            ),
        }

    def _get(self, path: str):
        try:
            r = requests.get(f"{self.base_url}{path}", timeout=self.timeout)
        except requests.ConnectionError:
            return {
                "error": f"Bureau not reachable at {self.base_url}. It hosts the"
                " Conductor; start the scheduler (scripts/scheduler.py) which"
                " brings Bureau up.",
                "reachable": False,
            }
        except requests.Timeout:
            return {"error": f"Bureau timed out after {self.timeout}s"}
        try:
            return r.json()
        except ValueError:
            return {"error": f"Bureau returned non-JSON (HTTP {r.status_code})"}

    # ------------------------------------------------------------------
    async def run(
        self,
        action: Annotated[
            Literal["run", "list"],
            "'list' the Conductor's plans and which are allowed to be triggered"
            " (read-only, always available); 'run' triggers one by name.",
        ] = "list",
        plan: Annotated[
            Optional[str],
            "Plan name to run, e.g. 'delta_neutral_farm' (evaluate and open a"
            " funding-carry hedge) or 'delta_neutral_exit' (evaluate and close"
            " one). Must be listed in bureau.plan_runner.allowed_plans.",
        ] = None,
        coin: Annotated[
            Optional[str],
            "Asset for a coin-parameterized plan: BTC, ETH or SOL. One plan run"
            " handles ONE coin — run it once per coin. Omit to use the plan's own"
            " default (BTC for the delta-neutral plans).",
        ] = None,
        avoid_if: Annotated[
            Optional[List[str]],
            "Plan names that block this run if they are already executing. The"
            " delta-neutral entry and exit must never overlap, so pass the other"
            " one here.",
        ] = None,
    ) -> Dict[str, Any]:
        """Trigger or inspect a Conductor plan."""
        if action == "list":
            plans = self._get("/v1/conductor/plans")
            if isinstance(plans, dict) and plans.get("error"):
                return plans
            return {
                "plans": plans,
                "allowed_to_run": self._allowed(),
                "note": (
                    "Only plans in 'allowed_to_run' can be triggered from a"
                    " conversation; the rest are CLI/cron only. A plan run handles"
                    " one coin — pass `coin` per run."
                ),
            }

        if not plan:
            return {"ran": False, "error": "action='run' needs a plan name."
                                           " Use action='list' to see them."}
        if plan not in self._allowed():
            return self._refusal(plan)

        body: Dict[str, Any] = {}
        if coin:
            body["vars"] = {"coin": str(coin).upper()}
        if avoid_if:
            body["avoid_if"] = list(avoid_if)

        url = f"{self.base_url}/v1/conductor/plans/{plan}/run"
        try:
            r = requests.post(url, json=body or None, timeout=self.timeout)
        except requests.ConnectionError:
            return {"ran": False, "error": f"Bureau not reachable at"
                                           f" {self.base_url}", "reachable": False}
        except requests.Timeout:
            # The Conductor accepts and runs asynchronously, so a timeout here says
            # nothing about whether the run started. Never imply it did not.
            return {
                "ran": None,
                "error": f"Bureau timed out after {self.timeout}s. The run may have"
                         " STARTED — check the plan's status before retrying, or a"
                         " retry could double-open.",
            }

        try:
            payload = r.json()
        except ValueError:
            payload = {"detail": r.text[:300]}

        if r.status_code in (200, 202):
            return {"ran": True, "plan": plan, "coin": coin,
                    "status_code": r.status_code, "result": payload,
                    "note": "Triggered. The plan runs asynchronously — ask for the"
                            " portfolio status to see the outcome."}
        if r.status_code == 409:
            # Conflict is the interlock doing its job, not a failure.
            return {"ran": False, "plan": plan, "skipped": "conflict",
                    "detail": payload,
                    "note": "Already running, or blocked by avoid_if. This is the"
                            " overlap guard working — do not retry immediately."}
        if r.status_code == 404:
            return {"ran": False, "plan": plan,
                    "error": f"Bureau does not know a plan called '{plan}'. It"
                             " must be in the config's bureau/ plans directory."}
        return {"ran": False, "plan": plan, "status_code": r.status_code,
                "error": payload}
