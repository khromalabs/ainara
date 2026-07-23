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

import asyncio
import json
import logging
import multiprocessing
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional  # List,

from ainara.bureau.plan import Plan, PlanValidationError, StepNode
from ainara.bureau.scratchpad import Scratchpad
from ainara.framework.orakle_client import call_skill

logger = logging.getLogger(__name__)


def _run_skill_in_process(
    orakle_servers: list,
    skill_id: str,
    params: dict,
    timeout: int,
    result_queue: multiprocessing.Queue,
) -> None:
    """
    Worker function executed in a separate process for skill steps.
    Calls the Orakle skill directly and puts the result on the queue.
    """
    try:
        result_str = call_skill(
            orakle_servers, skill_id, params, timeout=timeout
        )

        # Check if the result indicates an application-level error
        # (the skill completed the round trip but returned an error key)
        failure_reason = None
        try:
            parsed = json.loads(result_str)
            # Look for an explicit error key at top level or under "result"
            error = parsed.get("error") or (isinstance(parsed.get("result"), dict) and parsed.get("result", {}).get("error"))
            if error:
                failure_reason = f"Skill error: {error}"
                result_response = str(error)
            else:
                result_response = result_str  # keep the pretty-printed JSON as is
        except json.JSONDecodeError:
            result_response = result_str
            # fallback to transport-level check
            if result_str.startswith("Error:"):
                failure_reason = result_str

        result = {
            "response": result_response if not failure_reason else result_response,
            "turns_used": 0,
            "skills_executed": [skill_id],
            "failure_reason": failure_reason,
        }

        result_queue.put(result, timeout=5)
    except Exception as e:
        logger.error(f"Skill step '{skill_id}' failed: {e}")
        result_queue.put(
            {
                "response": "",
                "turns_used": 0,
                "skills_executed": [skill_id],
                "failure_reason": f"Skill execution error: {e}",
            },
            timeout=5,
        )


class Conductor:
    """
    The Conductor loads plan YAML files,
    and orchestrates DAG-based agent execution with a per-run scratchpad.

    Future improvement ideas:
    - Reflection loops: a reviewer step that can send results back
      for refinement before proceeding
    - Human-in-the-loop: a 'type: approval' step that pauses the DAG
      and waits for user confirmation via API
    - Dynamic step generation: an early step's output spawns parallel
      workers (e.g. one analyst agent per coin the screener flags)
    - Cross-run memory: persistent store per plan so steps can reference
      results from previous executions (positions, history, trends)
    - Streaming: emit scratchpad events as steps complete for real-time
      observation of plan progress
    - Transform steps: lightweight 'type: transform' for reshaping data
      between steps without invoking an LLM
    - Dynamic plan composition: let the LLM generate plans on the fly
      from conversational intent, so the user never touches YAML —
      the conversation remains the only interface
    - Plan caching: store dynamically generated plans for reuse when
      the same intent pattern is detected again
    """

    def __init__(
        self,
        plans_dir: Path,
        llm_config: dict,
        orakle_servers: list,
        global_capabilities: list,
        step_registry: dict,
        router=None,
        config_manager=None,
    ):
        self.plans_dir = Path(plans_dir)
        self.llm_config = llm_config
        self.orakle_servers = orakle_servers
        self.global_capabilities = global_capabilities
        self.step_registry = step_registry  # shared with server.py
        self.router = router
        self.config_manager = config_manager

        self.plans: Dict[str, Plan] = {}
        self.plan_status: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, threading.Lock] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Load plans."""
        self._load_plans()
        logger.info("Conductor started with %d plan(s)", len(self.plans))

    def shutdown(self) -> None:
        """Gracefully shut down"""
        logger.info("Conductor shutting down...")

    # ------------------------------------------------------------------
    # Plan loading
    # ------------------------------------------------------------------

    def _load_plans(self) -> None:
        """Scan the plans directory and load valid YAML plans."""
        if not self.plans_dir.exists():
            logger.info(
                "Plans directory '%s' does not exist. No plans loaded.",
                self.plans_dir,
            )
            return

        for filepath in sorted(self.plans_dir.glob("*.yaml")):
            try:
                plan = Plan(filepath)
                self.plans[plan.name] = plan
                self._locks[plan.name] = threading.Lock()
                self.plan_status[plan.name] = {
                    "state": "idle",
                    "last_run": None,
                    "last_result": None,
                    "last_failure": None,
                }
                logger.info("Loaded conductor plan: %s", plan.name)
            except PlanValidationError as e:
                logger.error(
                    "Skipping invalid plan '%s': %s", filepath.name, e
                )
            except Exception as e:
                logger.error(
                    "Unexpected error loading plan '%s': %s",
                    filepath.name,
                    e,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Plan triggering
    # ------------------------------------------------------------------

    def trigger_plan(
        self, plan_name: str, avoid_if: Optional[Any] = None
    ) -> tuple:
        """
        Attempt to start a plan run.  Returns ``(run_id, error_str)``
        where *error_str* is ``None`` on success or one of:

        * ``"plan_not_found"``   – no plan with that name is loaded
        * ``"already_running"``  – the plan's lock is held; run in progress
        * ``"avoid_condition_met:<blocking_plan>"`` – a plan specified in avoid_if is running
        """
        if plan_name not in self.plans:
            return None, "plan_not_found"

        lock = self._locks.get(plan_name)
        if lock is None:
            return None, "plan_not_found"

        if avoid_if:
            if isinstance(avoid_if, str):
                avoid_if = [avoid_if]
            for avoid_plan in avoid_if:
                avoid_lock = self._locks.get(avoid_plan)
                if avoid_lock is None:
                    logger.debug(
                        "Plan '%s' in avoid_if not found, ignoring.",
                        avoid_plan,
                    )
                    continue
                if avoid_lock.locked():
                    return None, f"avoid_condition_met:{avoid_plan}"

        if not lock.acquire(blocking=False):
            return None, "already_running"

        run_id = str(uuid.uuid4())[:8]
        thread = threading.Thread(
            target=self._execute_plan,
            args=(plan_name, run_id, lock),
            name=f"conductor-{plan_name}-{run_id}",
            daemon=True,
        )
        thread.start()
        return run_id, None

    # ------------------------------------------------------------------
    # DAG execution
    # ------------------------------------------------------------------

    def _execute_plan(
        self, plan_name: str, run_id: str, lock: threading.Lock
    ) -> None:
        """
        Orchestrate the full DAG execution for a single plan run.
        Runs in its own thread.
        """
        log_prefix = f"[conductor:{plan_name}:{run_id}]"
        plan = self.plans[plan_name]
        scratchpad = Scratchpad(max_chars=plan.scratchpad_max_chars)

        # Create a shared list for blacklisted providers in this specific plan run
        manager = multiprocessing.Manager()
        blacklisted_providers = manager.list()

        start_time = datetime.now(timezone.utc)

        self.plan_status[plan_name]["state"] = "running"
        self.plan_status[plan_name]["last_run"] = datetime.now(
            timezone.utc
        ).isoformat()
        self.plan_status[plan_name]["current_run_id"] = run_id

        logger.info("%s Plan execution started", log_prefix)

        completed: set = set()
        failed = False
        failed_step: Optional[str] = None
        failure_reason: Optional[str] = None
        # Track step_ids spawned in this run for abort purposes
        running_step_ids: Dict[str, str] = {}  # step_name -> step_id
        # Track skipped steps for reporting
        skipped_steps: Dict[str, str] = {}  # step_name -> skip_reason
        # Track avoid_if evaluation errors for reporting
        avoid_if_errors: Dict[str, Optional[str]] = {}

        try:
            while len(completed) < len(plan.steps):
                ready = plan.get_ready_steps(completed)
                # Filter out steps already running
                ready = [s for s in ready if s not in running_step_ids]

                if not ready and not running_step_ids:
                    logger.error(
                        "%s Deadlock: no ready steps and none running",
                        log_prefix,
                    )
                    failed = True
                    failure_reason = "Deadlock in DAG execution"
                    break

                # Launch ready steps up to max_parallel
                available_slots = plan.max_parallel - len(running_step_ids)
                to_launch = ready[:available_slots]

                for step_name in to_launch:
                    step_node = plan.steps[step_name]

                    logger.debug("==== WILL EXECUTE STEP ===")
                    logger.debug(f"{step_node}")

                    # Check avoid_step_if conditions before spawning (OR logic)
                    if step_node.avoid_step_if:
                        skip_step = False
                        for avoid_path in step_node.avoid_step_if:
                            should_skip, skip_reason, eval_error = self._should_skip_step(
                                step_name,
                                step_node,
                                scratchpad,
                                log_prefix,
                                avoid_path,
                            )
                            avoid_if_errors[step_name] = eval_error
                            if should_skip:
                                # Mark step as completed but skipped
                                skipped_result = {
                                    "response": "",
                                    "turns_used": 0,
                                    "skills_executed": [],
                                    "failure_reason": None,
                                    "skipped": True,
                                    "avoid_if_error": eval_error,
                                }
                                scratchpad.store(step_name, skipped_result)
                                completed.add(step_name)
                                skipped_steps[step_name] = skip_reason
                                logger.info(
                                    "%s Step '%s' skipped: %s",
                                    log_prefix,
                                    step_name,
                                    skip_reason,
                                )
                                skip_step = True
                                break  # Skip immediately if any condition is met

                        if skip_step:
                            continue

                    if step_node.type == "agent":
                        resolved_goal = scratchpad.resolve_template(
                            step_node.goal_template
                        )
                        step_id = self._spawn_agent(
                            plan_name=plan_name,
                            run_id=run_id,
                            step_name=step_name,
                            step_node=step_node,
                            goal=resolved_goal,
                            blacklisted_providers=blacklisted_providers,
                        )
                    elif step_node.type == "skill":
                        step_id = self._spawn_skill(
                            plan_name=plan_name,
                            run_id=run_id,
                            step_name=step_name,
                            step_node=step_node,
                            scratchpad=scratchpad,
                        )
                    else:
                        logger.error(
                            "%s Unknown step type '%s' for step '%s'",
                            log_prefix,
                            step_node.type,
                            step_name,
                        )
                        failed = True
                        failed_step = step_name
                        failure_reason = (
                            f"Unknown step type '{step_node.type}'"
                        )
                        break

                    running_step_ids[step_name] = step_id
                    logger.info(
                        "%s Launched %s step '%s' (id=%s)",
                        log_prefix,
                        step_node.type,
                        step_name,
                        step_id,
                    )

                if failed:
                    self._abort_running_steps(running_step_ids, log_prefix)
                    break

                # Poll running steps for completion
                newly_completed = self._poll_running_steps(
                    running_step_ids, log_prefix
                )

                # halted = False
                # halt_step = None
                # halt_condition = None

                for step_name, result in newly_completed.items():
                    del running_step_ids[step_name]

                    if result.get("failure_reason") or result.get("error"):
                        failed = True
                        failed_step = step_name
                        failure_reason = result.get(
                            "failure_reason",
                            result.get("error", "Unknown error"),
                        )
                        logger.error(
                            "%s Step '%s' failed: %s",
                            log_prefix,
                            step_name,
                            failure_reason,
                        )
                        break

                    # Inject avoid_if_evaluation error, if any
                    eval_err = avoid_if_errors.get(step_name)
                    if eval_err:
                        result["avoid_if_error"] = eval_err

                    scratchpad.store(step_name, result)
                    completed.add(step_name)
                    logger.info(
                        "%s Step '%s' completed (%d/%d)",
                        log_prefix,
                        step_name,
                        len(completed),
                        len(plan.steps),
                    )

                if failed:
                    self._abort_running_steps(running_step_ids, log_prefix)
                    break

                # Small sleep to avoid busy-waiting
                if running_step_ids:
                    time.sleep(2)

        except Exception as e:
            failed = True
            failure_reason = f"Unexpected error: {e}"
            logger.error(
                "%s Unexpected error during execution: %s",
                log_prefix,
                e,
                exc_info=True,
            )
            self._abort_running_steps(running_step_ids, log_prefix)

        # Finalize
        if failed:
            self.plan_status[plan_name]["state"] = "failed"
            self.plan_status[plan_name]["last_result"] = "failed"
            self.plan_status[plan_name]["last_failure"] = {
                "run_id": run_id,
                "step": failed_step,
                "reason": failure_reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            logger.error(
                "%s Plan FAILED at step '%s'", log_prefix, failed_step
            )

            if plan.on_failure == "notify":
                self._send_failure_notification(
                    plan_name, run_id, failed_step, failure_reason
                )
        else:
            self.plan_status[plan_name]["state"] = "idle"
            self.plan_status[plan_name]["last_result"] = "success"
            self.plan_status[plan_name]["last_failure"] = None
            logger.info("%s Plan completed successfully", log_prefix)

        # --- avoid_report_if ---
        # Only evaluated on success; if truthy (possibly negated) the
        # forensic report is suppressed to reduce noise.
        if not failed and plan.avoid_report_if:
            condition = plan.avoid_report_if
            invert = False
            if condition.startswith('!'):
                invert = True
                condition = condition[1:]

            value, error = scratchpad.resolve_dotted_path(condition)
            if error is not None:
                logger.warning(
                    "%s avoid_report_if eval error: %s – generating report anyway",
                    log_prefix, error
                )
            else:
                is_truthy = self._is_truthy(value)
                should_avoid = is_truthy if not invert else not is_truthy
                if should_avoid:
                    logger.info(
                        "%s Forensic report avoided by condition '%s' (evaluated to %s)",
                        log_prefix,
                        plan.avoid_report_if,
                        "truthy" if is_truthy else "falsy (negated)",
                    )
                    # Clean up state and release lock without writing a report
                    self.plan_status[plan_name].pop("current_run_id", None)
                    lock.release()
                    return

        self._generate_forensic_report(
            plan_name=plan_name,
            run_id=run_id,
            start_time=start_time,
            plan=plan,
            scratchpad=scratchpad,
            completed=completed,
            failed=failed,
            failed_step=failed_step,
            failure_reason=failure_reason,
            skipped_steps=skipped_steps,
            log_prefix=log_prefix,
        )

        self.plan_status[plan_name].pop("current_run_id", None)
        lock.release()

    @staticmethod
    def _format_response(response: str) -> str:
        """Pretty-print JSON if possible, else return as-is."""
        try:
            parsed = json.loads(response)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
        return str(response)

    @staticmethod
    def _is_truthy(value: Any) -> bool:
        """JS-style truthy evaluation: returns True if value is not falsy."""
        if value is None or value is False or value == 0 or value == '':
            return False
        if isinstance(value, (list, dict)) and len(value) == 0:
            return False
        return True

    # ------------------------------------------------------------------
    # Forensic report
    # ------------------------------------------------------------------

    def _generate_forensic_report(
        self, plan_name: str, run_id: str, start_time: datetime, **kwargs
    ) -> None:
        """
        Generate a markdown forensic report for a plan execution.

        Expected kwargs:
        - plan (Plan): The executed plan object
        - scratchpad (Scratchpad): The run's scratchpad with results
        - completed (set): Set of completed step names
        - failed (bool): Whether the plan failed
        - failed_step (str): Name of the failed step (if any)
        - failure_reason (str): Reason for failure (if any)
        - skipped_steps (dict): Dict of skipped step names to skip reasons
        - log_prefix (str): Prefix for logger output
        """
        plan = kwargs.get("plan")
        scratchpad = kwargs.get("scratchpad")
        completed = kwargs.get("completed", set())
        failed = kwargs.get("failed", False)
        failed_step = kwargs.get("failed_step")
        failure_reason = kwargs.get("failure_reason")
        skipped_steps = kwargs.get("skipped_steps", {})
        log_prefix = kwargs.get("log_prefix", "")

        try:
            end_time = datetime.now(timezone.utc)
            duration = end_time - start_time

            reports_dir = Path(self.config_manager.get_default_log_dir()) / "bureau" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            timestamp_str = start_time.astimezone().strftime("%Y%m%d_%H%M")
            report_name = f"plan_{plan_name}-{timestamp_str}-{run_id}.md"
            report_path = reports_dir / report_name

            if failed:
                status_label = "❌ FAILED"
            else:
                status_label = "✅ SUCCESS"

            lines = [
                f"# Forensic Report: Plan `{plan_name}`",
                f"**Run ID:** `{run_id}`",
                f"**Status:** {status_label}",
                f"**Start Time:** {start_time.isoformat()}",
                f"**End Time:** {end_time.isoformat()}",
                f"**Duration:** {duration}\n",
            ]

            if failed:
                lines.append(f"**Failed Step:** `{failed_step}`")
                lines.append(f"**Failure Reason:** {failure_reason}\n")

            lines.append("## Execution Summary\n")
            lines.append("| Step | Type | Status | Turns | Skills Executed |")
            lines.append("|---|---|---|---|---|")

            attempted_steps = list(completed)
            if failed and failed_step and failed_step not in attempted_steps:
                attempted_steps.append(failed_step)

            for step_name in attempted_steps:
                step_node = plan.steps[step_name]
                result = scratchpad.get(step_name) or {}
                avoid_error = result.get("avoid_if_error")

                if step_name in skipped_steps:
                    status = "⏭️ Skipped"
                elif step_name in completed:
                    if avoid_error:
                        status = "⚠️ Completed (gate eval error)"
                    else:
                        status = "✅ Completed"
                else:
                    status = "❌ Failed"

                turns = result.get("turns_used", 0)
                skills = ", ".join(result.get("skills_executed", [])) or "None"
                lines.append(
                    f"| `{step_name}` | {step_node.type} | {status} | {turns}"
                    f" | {skills} |"
                )

            lines.append("\n## Step Details\n")
            for step_name in attempted_steps:
                lines.append(f"### Step: `{step_name}`")
                result = scratchpad.get(step_name) or {}
                if result.get("avoid_if_error"):
                    lines.append(
                        f"\n> ⚠️ **Warning:** The `avoid_step_if` condition could not be "
                        f"evaluated: {result['avoid_if_error']}\n"
                    )
                if step_name in skipped_steps:
                    skip_reason = skipped_steps[step_name]
                    lines.append(f"**Skipped:** {skip_reason}\n")
                elif step_name in completed:
                    response = result.get("response", "No response recorded.")
                    lines.append(
                        "**Response / Final Answer:**\n```text\n"
                        + self._format_response(response)
                        + "\n```\n"
                    )
                else:
                    lines.append(
                        f"**Error / Failure Reason:** {failure_reason}\n"
                    )

            with open(report_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            logger.info(
                "%s Forensic report saved to %s", log_prefix, report_path
            )
        except Exception as e:
            logger.error(
                "%s Failed to generate forensic report: %s",
                log_prefix,
                e,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Avoid condition evaluation
    # ------------------------------------------------------------------

    def _should_skip_step(
        self,
        step_name: str,
        step_node: StepNode,
        scratchpad: Scratchpad,
        log_prefix: str,
        avoid_path: str = "",
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Evaluate an ``avoid_step_if`` condition before executing a step.

        Returns a tuple of (should_skip: bool, skip_reason: Optional[str],
        evaluation_error: Optional[str]).
        - If the condition is truthy, returns (True, reason_string, None)
        - If the condition is falsy, returns (False, None, None)
        - On error (missing step, invalid JSON, missing path), returns (False, None, error_string);
          the step will **run**, but the error string is surfaced prominently in the forensic report.
        """
        if not avoid_path:
            return False, None, None

        # Detect negation operator
        invert = False
        cleaned_path = avoid_path
        if avoid_path.startswith('!'):
            invert = True
            cleaned_path = avoid_path[1:]

        current, error = scratchpad.resolve_dotted_path(cleaned_path)
        if error is not None:
            error_reason = f"Condition '{avoid_path}': {error}"
            logger.error(
                "%s Step '%s': %s Executing step anyway.",
                log_prefix,
                step_name,
                error_reason,
            )
            return False, None, error_reason

        # JS-style truthy evaluation
        is_truthy = self._is_truthy(current)
        should_trigger = is_truthy if not invert else not is_truthy

        if should_trigger:
            reason_prefix = "Truthy" if is_truthy else "Falsy (negated)"
            skip_reason = f"{reason_prefix} condition: {avoid_path} = {current!r}"
            logger.info(
                "%s Step '%s' avoid_step_if='%s' evaluated to %s "
                "(value=%r). Skipping step.",
                log_prefix,
                step_name,
                avoid_path,
                reason_prefix.lower(),
                current,
            )
            return True, skip_reason, None

        logger.info(
            "%s Step '%s' avoid_step_if='%s' evaluated to %s "
            "(value=%r). Executing step.",
            log_prefix,
            step_name,
            avoid_path,
            "falsy" if is_truthy else "truthy (negated)",
            current,
        )
        return False, None, None

    # ------------------------------------------------------------------
    # Agent spawning & polling
    # ------------------------------------------------------------------

    def _spawn_agent(
        self,
        plan_name: str,
        run_id: str,
        step_name: str,
        step_node: StepNode,
        goal: str,
        blacklisted_providers: Any = None,
    ) -> str:
        """Spawn an agent process, reusing the Bureau infrastructure."""
        from ainara.bureau.server import run_agent_in_process

        step_id = f"conductor-{plan_name}-{run_id}-{step_name}"
        result_queue = multiprocessing.Queue()

        plan = self.plans[plan_name]
        user_context = {"language": plan.raw.get("language", "en")}

        process = multiprocessing.Process(
            target=run_agent_in_process,
            args=(
                self.llm_config,
                self.orakle_servers,
                step_node.blueprint,
                user_context,
                goal,
                step_node.max_turns,
                result_queue,
                blacklisted_providers,
                self.global_capabilities,
                True,  # conductor_agent
            ),
        )
        process.start()

        # Register in the shared step_registry so timeout_monitor can track it
        self.step_registry[step_id] = {
            "id": step_id,
            "status": "RUNNING",
            "goal": goal,
            "response": None,
            "turns_used": 0,
            "skills_executed": [],
            "failure_reason": None,
            "error": None,
            "execution_timeout": step_node.execution_timeout,
            "start_time": time.time(),
            "process": process,
            "result_queue": result_queue,
            "pid": process.pid,
        }

        return step_id

    def _spawn_skill(
        self,
        plan_name: str,
        run_id: str,
        step_name: str,
        step_node: StepNode,
        scratchpad: Scratchpad,
    ) -> str:
        """Spawn a skill execution in a separate process."""
        step_id = f"conductor-{plan_name}-{run_id}-{step_name}"
        result_queue = multiprocessing.Queue()

        # Resolve any scratchpad templates in params
        resolved_params = {}
        for key, value in (step_node.params or {}).items():
            if isinstance(value, str):
                resolved_params[key] = scratchpad.resolve_template(value)
            else:
                resolved_params[key] = value

        process = multiprocessing.Process(
            target=_run_skill_in_process,
            args=(
                self.orakle_servers,
                step_node.skill,
                resolved_params,
                step_node.execution_timeout,
                result_queue,
            ),
        )
        process.start()

        self.step_registry[step_id] = {
            "id": step_id,
            "status": "RUNNING",
            "goal": f"skill:{step_node.skill}",
            "response": None,
            "turns_used": 0,
            "skills_executed": [step_node.skill],
            "failure_reason": None,
            "error": None,
            "execution_timeout": step_node.execution_timeout,
            "start_time": time.time(),
            "process": process,
            "result_queue": result_queue,
            "pid": process.pid,
        }

        return step_id

    def _poll_running_steps(
        self,
        running: Dict[str, str],
        log_prefix: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Check running steps for completion.  Returns a dict of
        ``{step_name: result_dict}`` for steps that have finished.
        """
        completed = {}

        for step_name, step_id in list(running.items()):
            task = self.step_registry.get(step_id)
            if task is None:
                completed[step_name] = {
                    "error": "Task record missing",
                    "failure_reason": (
                        "Internal error: task record disappeared"
                    ),
                }
                continue

            status = task.get("status")
            if status == "COMPLETED":
                response = task.get("response", {})
                if isinstance(response, dict):
                    completed[step_name] = {
                        "response": response.get("response", ""),
                        "turns_used": response.get("turns_used", 0),
                        "skills_executed": response.get("skills_executed", []),
                        "failure_reason": response.get("failure_reason"),
                    }
                else:
                    # Skill steps put the full result dict directly
                    completed[step_name] = {
                        "response": str(response),
                        "turns_used": 0,
                        "skills_executed": [],
                        "failure_reason": None,
                    }
                # If the step itself reported a failure_reason in its result
                if completed[step_name]["failure_reason"]:
                    completed[step_name]["error"] = "StepGoalNotAchieved"
            elif status == "FAILED":
                completed[step_name] = {
                    "error": task.get("error", "Unknown"),
                    "failure_reason": task.get(
                        "failure_reason", "Step process failed"
                    ),
                }

        return completed

    def _abort_running_steps(
        self, running: Dict[str, str], log_prefix: str
    ) -> None:
        """Terminate all currently running steps for this plan."""
        from ainara.bureau.server import _terminate_step

        for step_name, step_id in list(running.items()):
            task = self.step_registry.get(step_id)
            if task and task.get("status") == "RUNNING":
                logger.warning(
                    "%s Aborting step '%s' (id=%s)",
                    log_prefix,
                    step_name,
                    step_id,
                )
                _terminate_step(step_id, task, reason="plan failure abort")
                task["status"] = "FAILED"
                task["failure_reason"] = "Aborted due to plan failure"
                task["error"] = "PlanAbort"

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _send_failure_notification(
        self,
        plan_name: str,
        run_id: str,
        failed_step: Optional[str],
        failure_reason: Optional[str],
    ) -> None:
        """Send a failure notification via the connector router."""
        if not self.router:
            logger.warning(
                "No router available — cannot send failure notification "
                "for plan '%s'",
                plan_name,
            )
            return

        message = (
            f"[Conductor] Plan '{plan_name}' failed.\n"
            f"Run ID: {run_id}\n"
            f"Failed step: {failed_step or 'N/A'}\n"
            f"Reason: {failure_reason or 'Unknown'}\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}"
        )

        try:
            # Use asyncio to call the async router
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    self.router.route_request(
                        contract="messages",
                        path="/messages",
                        method="POST",
                        params={
                            "target_id": "conductor_notifications",
                            "content": message,
                        },
                    )
                )
            finally:
                loop.close()
            logger.info("Failure notification sent for plan '%s'", plan_name)
        except Exception as e:
            logger.error(
                "Failed to send notification for plan '%s': %s",
                plan_name,
                e,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_plans(self) -> Dict[str, Any]:
        """Return metadata for all loaded plans (name, steps)."""
        result = {}
        for plan_name, plan in self.plans.items():
            steps = {}
            for step_name, node in plan.steps.items():
                steps[step_name] = {
                    "type": node.type,
                    "depends_on": node.depends_on,
                    "execution_timeout": node.execution_timeout,
                }
                if node.type == "agent":
                    steps[step_name]["max_turns"] = node.max_turns
                elif node.type == "skill":
                    steps[step_name]["skill"] = node.skill
            result[plan_name] = {
                "name": plan_name,
                "on_failure": plan.on_failure,
                "max_parallel": plan.max_parallel,
                "steps": steps,
            }
        return result

    def get_status(self) -> Dict[str, Any]:
        """Return status information for all loaded plans."""
        result = {}
        for plan_name, plan in self.plans.items():
            status = self.plan_status.get(plan_name, {})
            result[plan_name] = {
                "state": status.get("state", "unknown"),
                "steps": list(plan.steps.keys()),
                "last_run": status.get("last_run"),
                "last_result": status.get("last_result"),
                "last_failure": status.get("last_failure"),
            }
        return result
