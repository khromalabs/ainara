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
import copy
import json
import logging
import multiprocessing
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional  # List,

from ainara.bureau.plan import (
    Plan,
    PlanValidationError,
    StepNode,
    iter_static_refs,
)
from ainara.bureau.scratchpad import (
    Scratchpad,
    StaticBindings,
    resolve_property_aware,
)
from ainara.framework.orakle_client import call_skill

logger = logging.getLogger(__name__)


def _format_binding_value(value: Any, limit: int = 160) -> str:
    """Compact, markdown-table-safe repr of a resolved binding value."""
    text = repr(value)
    if len(text) > limit:
        text = text[:limit] + f"...[repr len={len(text)}]"
    return text.replace("|", "\\|")


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
        property_registry: Optional[Dict[str, Any]] = None,
    ):
        self.plans_dir = Path(plans_dir)
        self.llm_config = llm_config
        self.orakle_servers = orakle_servers
        self.global_capabilities = global_capabilities
        self.step_registry = step_registry  # shared with server.py
        self.router = router
        self.config_manager = config_manager
        # Flat full_key -> property descriptor map fetched from the Orakle
        # server (view=properties). Lets config_aliases and $skills.* refs
        # resolve against declared skill property defaults.
        # TODO: Skill properties are assumed static for the process lifetime.
        # If hot-swapping of skill properties is ever supported, refresh this
        # snapshot (e.g. at the start of each plan run) instead of capturing
        # it once at Bureau startup.
        self.property_registry = property_registry or {}

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
        """
        Gracefully shut down: terminate any running steps registered by
        this conductor, mark their plans as stopped, and release plan
        locks. Idempotent; safe to call multiple times.
        """
        logger.info("Conductor shutting down...")

        # Local import to avoid a circular import at module load time,
        # matching the pattern used in _abort_running_steps.
        from ainara.bureau.server import _terminate_step

        for step_id, task in list(self.step_registry.items()):
            if not step_id.startswith("conductor-"):
                continue
            if task.get("status") != "RUNNING":
                continue
            proc = task.get("process")
            if proc and proc.is_alive():
                logger.warning(
                    "Terminating step '%s' during shutdown", step_id
                )
                _terminate_step(step_id, task, reason="server shutdown")
            task["status"] = "FAILED"
            task["failure_reason"] = "Aborted due to server shutdown"
            task["error"] = "Shutdown"

        for plan_name, lock in self._locks.items():
            if not lock.locked():
                continue
            self.plan_status[plan_name]["state"] = "stopped"
            logger.info("Releasing lock for plan '%s'", plan_name)
            try:
                lock.release()
            except RuntimeError:
                # Executor thread released it first; harmless during exit.
                pass

        logger.info("Conductor shutdown complete")

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
                    # logger.info(
                    #     "Plan '%s' in avoid_if not found, ignoring.",
                    #     avoid_plan,
                    # )
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

        # --- Static bindings snapshot (variables + config aliases) ---
        # Resolved once per run; mid-run config reloads do not affect it.
        bindings, bindings_error = self._build_static_bindings(plan, log_prefix)
        scratchpad = Scratchpad(
            max_chars=plan.scratchpad_max_chars, static_bindings=bindings
        )

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
        # Track steps aborted mid-run (plan failure) for reporting
        aborted_steps: Dict[str, str] = {}  # step_name -> abort reason
        # Track avoid_if evaluation errors for reporting
        avoid_if_errors: Dict[str, Optional[str]] = {}

        # --- Preflight: resolve every static ref before launching steps ---
        resolved_refs: Dict[str, Any] = {}
        binding_failures: list = []
        if bindings_error is None:
            resolved_refs, binding_failures = self._preflight_static_refs(
                plan, scratchpad, log_prefix
            )
        else:
            binding_failures = [bindings_error]

        if binding_failures:
            failed = True
            failure_reason = (
                "Static binding resolution failed: "
                + "; ".join(binding_failures)
            )

        try:
            while not failed and len(completed) < len(plan.steps):
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

                    # logger.info("==== WILL EXECUTE STEP ===")
                    # logger.info(f"{step_node}")

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
                        if not isinstance(resolved_goal, str):
                            resolved_goal = str(resolved_goal)
                        step_id = self._spawn_agent(
                            plan_name=plan_name,
                            run_id=run_id,
                            step_name=step_name,
                            step_node=step_node,
                            goal=resolved_goal,
                            blacklisted_providers=blacklisted_providers,
                            scratchpad=scratchpad,
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
                    aborted_steps.update(
                        self._abort_running_steps(
                            running_step_ids, log_prefix
                        )
                    )
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
                    aborted_steps.update(
                        self._abort_running_steps(
                            running_step_ids, log_prefix
                        )
                    )
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
            aborted_steps.update(
                self._abort_running_steps(running_step_ids, log_prefix)
            )

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
            if condition.startswith('not '):
                invert = True
                condition = condition[4:].strip()

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
            aborted_steps=aborted_steps,
            log_prefix=log_prefix,
            bindings=bindings,
            resolved_refs=resolved_refs,
            binding_failures=binding_failures,
        )

        self.plan_status[plan_name].pop("current_run_id", None)
        lock.release()

    def _build_static_bindings(
        self, plan: Plan, log_prefix: str
    ) -> tuple:
        """
        Snapshot plan variables and resolve config aliases once per run.

        Returns ``(StaticBindings, error_or_None)``. Aliases are resolved
        immediately so a broken alias aborts the run before any step runs.
        """
        config_root: dict = {}
        if self.config_manager is not None:
            try:
                if self.config_manager.needs_load():
                    self.config_manager.load_config()
                config_root = copy.deepcopy(self.config_manager.config) or {}
            except Exception as e:
                logger.error(
                    "%s Failed to snapshot configuration for bindings: %s",
                    log_prefix,
                    e,
                    exc_info=True,
                )
                return None, f"Failed to snapshot configuration: {e}"

        aliases: Dict[str, Any] = {}
        for name, target in plan.config_aliases.items():
            value, error = resolve_property_aware(
                config_root, target, target, self.property_registry
            )
            if error is not None or value is None:
                message = (
                    f"Config alias '{name}' -> '{target}' could not be"
                    f" resolved: {error or 'null value'}"
                )
                logger.error("%s %s", log_prefix, message)
                return None, message
            aliases[name] = value

        bindings = StaticBindings(
            variables=dict(plan.variables),
            aliases=aliases,
            alias_targets=dict(plan.config_aliases),
            config_root=config_root,
            property_registry=self.property_registry,
        )
        logger.info(
            "%s Static bindings ready: %d variable(s), %d config alias(es)",
            log_prefix,
            len(bindings.variables),
            len(bindings.aliases),
        )
        return bindings, None

    def _preflight_static_refs(
        self, plan: Plan, scratchpad: Scratchpad, log_prefix: str
    ) -> tuple:
        """
        Resolve every static ``{{$...}}`` reference used across agent goals,
        agent system messages and skill params. Returns
        ``(resolved_refs, failures)``: *resolved_refs* maps each distinct ref
        body to its resolved value (for the forensic report); *failures* is a
        list of error strings (empty when everything resolves).
        """
        resolved: Dict[str, Any] = {}
        failed_bodies: set = set()
        failures: list = []
        for _, body in iter_static_refs(plan.steps):
            if body in resolved or body in failed_bodies:
                continue
            value, error = scratchpad.resolve_dotted_path(f"${body}")
            if error is not None or value is None:
                failed_bodies.add(body)
                failures.append(f"${body}: {error or 'resolved to null'}")
            else:
                resolved[body] = value
        if failures:
            logger.error(
                "%s Static binding preflight failed: %s",
                log_prefix,
                "; ".join(failures),
            )
        return resolved, failures

    @staticmethod
    def _format_response(response: str) -> str:
        """Pretty-print JSON and abbreviate long escaped string fields.

        Keeps the JSON compact and human-readable by replacing long escaped
        strings with a placeholder, then appends the decoded value below the
        JSON block.
        """
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            return str(response)

        if not isinstance(data, (dict, list)):
            return str(response)

        appendix = []
        threshold = 40

        def _should_abbreviate(value) -> bool:
            return (
                isinstance(value, str)
                and len(value) > threshold
                and (
                    re.search(r'[\n\t\r\b\f]', value)
                    or re.search(r'\\[ntbfru]', value)
                )
            )

        def _handle_str(value: str, path: str) -> str:
            decoded = Conductor._unescape_readable(value)
            appendix.append((path, decoded))
            return f"<see decoded appendix: {path}>"

        def _walk_shallow(obj, path: str = "") -> None:
            if isinstance(obj, dict):
                for key, value in list(obj.items()):
                    child_path = f"{path}.{key}" if path else key
                    if _should_abbreviate(value):
                        obj[key] = _handle_str(value, child_path)
                    elif isinstance(value, dict):
                        for nested_key, nested_value in list(value.items()):
                            nested_path = f"{child_path}.{nested_key}"
                            if _should_abbreviate(nested_value):
                                value[nested_key] = _handle_str(
                                    nested_value, nested_path
                                )
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    item_path = f"{path}[{idx}]"
                    if isinstance(item, dict):
                        for nested_key, nested_value in list(item.items()):
                            nested_path = f"{item_path}.{nested_key}"
                            if _should_abbreviate(nested_value):
                                item[nested_key] = _handle_str(
                                    nested_value, nested_path
                                )

        _walk_shallow(data)

        pretty_json = json.dumps(data, indent=2, ensure_ascii=False)

        if not appendix:
            return pretty_json

        parts = [pretty_json, "```\n\n**Decoded long fields:**\n"]
        for path, value in appendix:
            parts.append(f"### `{path}`\n```text\n{value}\n\n")
        return "\n".join(parts)

    @staticmethod
    def _unescape_readable(text: str) -> str:
        """Decode common JSON/string escapes for human-readable forensic reports."""
        unicode_escape = re.compile(r"\\u([0-9a-fA-F]{4})")
        simple_escapes = {
            r"\n": "\n",
            r"\t": "\t",
            r"\r": "\r",
            r"\b": "\b",
            r"\f": "\f",
            r"\"": '"',
            r"\\": "\\",
        }

        def replace_unicode(match):
            return chr(int(match.group(1), 16))

        def replace_escape(match):
            esc = match.group(0)
            return simple_escapes.get(esc, esc)

        text = unicode_escape.sub(replace_unicode, text)
        return re.sub(r"\\[ntrb\"\\]|\\f", replace_escape, text)

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
        - aborted_steps (dict): Dict of aborted step names to abort reasons
        - log_prefix (str): Prefix for logger output
        """
        plan = kwargs.get("plan")
        scratchpad = kwargs.get("scratchpad")
        completed = kwargs.get("completed", set())
        failed = kwargs.get("failed", False)
        failed_step = kwargs.get("failed_step")
        failure_reason = kwargs.get("failure_reason")
        skipped_steps = kwargs.get("skipped_steps", {})
        aborted_steps = kwargs.get("aborted_steps", {})
        log_prefix = kwargs.get("log_prefix", "")

        bindings = kwargs.get("bindings")
        resolved_refs = kwargs.get("resolved_refs", {})
        binding_failures = kwargs.get("binding_failures", [])

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

            # Report steps in plan declaration (YAML) order, regardless of
            # outcome (completed / skipped / failed / aborted).
            attempted = set(completed) | set(aborted_steps)
            if failed and failed_step:
                attempted.add(failed_step)
            attempted_steps = [n for n in plan.steps if n in attempted]

            for step_name in attempted_steps:
                step_node = plan.steps[step_name]
                result = scratchpad.get(step_name) or {}
                avoid_error = result.get("avoid_if_error")

                if step_name in skipped_steps:
                    status = "⏭️ Skipped"
                elif step_name in aborted_steps:
                    status = "⛔ Aborted"
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

            # --- Resolved static bindings (audit trail) ---
            lines.append("\n## Resolved Bindings\n")
            if bindings is None:
                lines.append(
                    "_Static bindings could not be built (see failure"
                    " reason)._\n"
                )
            elif (
                not bindings.variables
                and not bindings.aliases
                and not resolved_refs
            ):
                lines.append("_No static bindings used by this plan._\n")
            else:
                lines.append("| Binding | Source | Resolved Value |")
                lines.append("|---|---|---|")
                for name, value in bindings.variables.items():
                    lines.append(
                        f"| `${name}` | plan variable |"
                        f" {_format_binding_value(value)} |"
                    )
                for name, target in bindings.alias_targets.items():
                    lines.append(
                        f"| `${name}` | config alias `{target}` |"
                        f" {_format_binding_value(bindings.aliases.get(name))}"
                        " |"
                    )
                for body, value in sorted(resolved_refs.items()):
                    lines.append(
                        f"| `${body}` | template reference |"
                        f" {_format_binding_value(value)} |"
                    )
                lines.append("")
            for failure in binding_failures:
                lines.append(f"\n> ⚠️ **Binding failure:** {failure}")

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
                elif step_name in aborted_steps:
                    lines.append(
                        f"**Aborted:** {aborted_steps[step_name]}\n"
                    )
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

        # Condition negation syntax: 'not step.field.path'
        # Example:
        #   avoid_step_if: not exposure.result.actions_taken
        #
        # TODO: Future extension
        # The condition evaluator could be grown into a full boolean expression
        # language supporting parentheses, 'and', 'or', and both prefix 'not' and
        # infix 'not()' operators, e.g.:
        #   (not path1 and path2) or not path3
        # or:
        #   not(path1 and path2)
        # This would allow arbitrarily rich gating logic while keeping the YAML
        # configuration readable and requiring no special quoting. The evaluator
        # would require a small recursive‑descent / Pratt parser but would reuse
        # the same dot‑path resolution engine we already have for the scratchpad.
        invert = False
        cleaned_path = avoid_path
        if avoid_path.startswith('not '):
            invert = True
            cleaned_path = avoid_path[4:].strip()
            if not cleaned_path:
                # 'not' without a path is invalid – treat as an error
                error = "Invalid negation: 'not' must be followed by a path"
                logger.error(
                    "%s Step '%s': %s. Executing step anyway.",
                    log_prefix, step_name, error,
                )
                return False, None, error

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
        scratchpad: Optional[Scratchpad] = None,
    ) -> str:
        """Spawn an agent process, reusing the Bureau infrastructure."""
        from ainara.bureau.server import run_agent_in_process

        step_id = f"conductor-{plan_name}-{run_id}-{step_name}"
        result_queue = multiprocessing.Queue()

        # Render placeholders in the blueprint's system message (static $refs
        # and dynamic {{step.*}} refs) before it crosses the process
        # boundary. The worker receives final text; server.py is untouched.
        blueprint = copy.deepcopy(step_node.blueprint)
        if scratchpad is not None and isinstance(
            blueprint.get("system_message"), str
        ):
            rendered = scratchpad.resolve_template(blueprint["system_message"])
            blueprint["system_message"] = (
                rendered if isinstance(rendered, str) else str(rendered)
            )

        plan = self.plans[plan_name]
        user_context = {"language": plan.raw.get("language", "en")}

        process = multiprocessing.Process(
            target=run_agent_in_process,
            args=(
                self.llm_config,
                self.orakle_servers,
                blueprint,
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
    ) -> Dict[str, str]:
        """Terminate all currently running steps for this plan.

        Returns a mapping ``{step_name: reason}`` covering every step that
        was still in flight when the plan aborted (i.e. steps that never
        produced a harvested result).
        """
        from ainara.bureau.server import _terminate_step

        aborted: Dict[str, str] = {}
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
                aborted[step_name] = "Terminated mid-run due to plan failure"
            elif task and task.get("status") == "COMPLETED":
                # Process finished but the poll loop broke before harvesting
                aborted[step_name] = (
                    "Finished, but its result was never collected "
                    "(plan failed first)"
                )
            else:
                aborted[step_name] = (
                    (task or {}).get("failure_reason")
                    or "Aborted due to plan failure"
                )
        return aborted

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
