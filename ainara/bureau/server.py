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

import argparse
# import pprint
import logging
import multiprocessing
import os
import queue
import signal
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from ainara.bureau.conductor import Conductor
from ainara.framework.config import ConfigManager
from ainara.framework.connectors.manager import ConnectorManager
from ainara.framework.connectors.router import ConnectorRouter
from ainara.framework.llm import create_llm_backend
from ainara.framework.logging_setup import logging_manager
from ainara.framework.orakle_middleware import OrakleCapabilityFetcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d] - %(message)s",
)

# Grace period (seconds) after a gentle termination before a hard kill
GRACE_PERIOD = 20
logger = logging.getLogger("bureau")

app = Flask(__name__)


def _terminate_step(step_id: str, task: Dict[str, Any], reason: str) -> None:
    """
    Perform the two‑step termination (graceful → hard) for a running step.

    Args:
        step_id: The UUID of the step.
        task: The internal ``step_registry[step_id]`` dict.
        reason: Human‑readable description used for ``failure_reason``.
    """
    proc = task.get("process")
    if not proc or not proc.is_alive():
        # Nothing to kill – maybe already finished or never started
        return

    logger.warning(
        f"Step {step_id} termination requested ({reason}). "
        "Attempting graceful shutdown."
    )

    # 1️⃣  Gentle termination (SIGINT / CTRL_BREAK_EVENT)
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()  # SIGTERM on POSIX
    except Exception as e:  # pragma: no cover – defensive
        logger.error(f"Error sending graceful signal to step {step_id}: {e}")

    # 2️⃣  Record the request time so the timeout monitor can apply the grace period
    task["termination_requested"] = time.time()
    task["termination_reason"] = reason

    # The actual hard‑kill (proc.kill()) will be handled by the timeout monitor
    # once the grace period (GRACE_PERIOD) expires.


# Process pool for running agents in the background
# We limit the number of concurrent agents to prevent resource exhaustion
# Using processes instead of threads to allow true termination on timeout
# Executor removed; agents are launched via multiprocessing.Process

# In-memory storage for step tasks
# Structure: { step_id: { "status": str, "result": str, "error": str, "goal": str } }
# In a production environment, this should be replaced by a database (Redis/SQLite)
step_registry: Dict[str, Dict[str, Any]] = {}

# Global components
config_manager: Optional[ConfigManager] = None
llm_backend = None
global_capabilities: list = []
conductor: Optional[Conductor] = None


def parse_args():
    parser = argparse.ArgumentParser(description="Bureau Server")
    parser.add_argument(
        "--port",
        type=int,
        default=8010,
        help="Port to run the server on (default: 8010)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable profiling for the server",
    )
    return parser.parse_args()


def timeout_monitor():
    """
    Background thread that monitors running agents and enforces timeouts.
    Runs continuously checking for agents that have exceeded their execution timeout
    and harvests results from completed processes.
    """
    logger.info("Timeout monitor thread started")

    while True:
        try:
            current_time = time.time()

            # Check all running tasks
            for step_id, task in list(step_registry.items()):
                if task.get("status") != "RUNNING":
                    continue

                proc = task.get("process")
                if not proc:
                    continue

                # Check if process has finished
                if not proc.is_alive():
                    result_queue = task.get("result_queue")
                    result = None
                    got_result = False

                    if result_queue:
                        try:
                            result = result_queue.get_nowait()
                            got_result = True
                        except queue.Empty:
                            pass
                        except Exception as e:
                            logger.error(
                                f"Error reading queue for step {step_id}: {e}"
                            )

                    if got_result:
                        task["status"] = "COMPLETED"
                        task["response"] = result
                    else:
                        # Only mark as failed if it wasn't already marked by timeout/abort
                        if task.get("status") == "RUNNING":
                            task["status"] = "FAILED"
                            task["failure_reason"] = (
                                "Process terminated without returning a"
                                " result."
                            )
                            task["error"] = "ProcessCrash"

                    # Cleanup
                    proc.join(timeout=1)
                    task["process"] = None
                    task["result_queue"] = None
                    continue

                # Get timeout settings
                execution_timeout = task.get("execution_timeout", 600)
                start_time = task.get("start_time")

                # Skip if infinite timeout
                if execution_timeout == -1:
                    continue

                # Check if timeout exceeded
                if (
                    start_time
                    and (current_time - start_time) > execution_timeout
                ):
                    _terminate_step(
                        step_id,
                        task,
                        reason="execution timeout",
                    )

                # If we have already asked for termination, enforce hard kill after grace period
                if task.get("termination_requested"):
                    if (
                        current_time - task["termination_requested"]
                    ) > GRACE_PERIOD:
                        if proc.is_alive():
                            logger.warning(
                                f"Step {step_id} did not exit after grace"
                                " period; force‑killing"
                            )
                            try:
                                proc.kill()
                            except Exception as e:
                                logger.error(
                                    f"Error force‑killing step {step_id}: {e}"
                                )

                        # Finalize task as failed due to timeout
                        task["status"] = "FAILED"
                        task["failure_reason"] = (
                            f"Execution timeout: exceeded {execution_timeout}s"
                            " and did not terminate within grace period"
                        )
                        task["error"] = "TimeoutError"
                        task["process"] = None

            # Sleep for 1 second before next check
            time.sleep(1)

        except Exception as e:
            logger.error(f"Error in timeout monitor: {e}", exc_info=True)
            time.sleep(1)


def initialize_components():
    """Initialize configuration, LLM, and Middleware."""
    global config_manager, llm_backend, global_capabilities

    logger.info("Initializing Bureau components...")

    # 1. Load Configuration
    config_manager = ConfigManager()
    config_manager.load_config()
    config = config_manager.config

    # logger.info(f"LLM config: {config.get('llm', {})}")

    # 2. Initialize LLM Backend
    logger.info("Initializing LLM Backend")
    llm_backend = create_llm_backend(config.get("llm", {}))

    # 3. Fetch Orakle Capabilities
    logger.info("Fetching global Orakle capabilities")
    orakle_servers = config.get("orakle.servers", ["http://127.0.0.1:8100"])
    fetcher = OrakleCapabilityFetcher(orakle_servers)
    global_capabilities = fetcher.fetch_capabilities()

    # 4. Start timeout monitor thread
    monitor_thread = threading.Thread(target=timeout_monitor, daemon=True)
    monitor_thread.start()
    logger.info("Timeout monitor thread initialized")

    # 5. Initialize Connector Router for notifications
    resource_base_dir = Path(__file__).parent.parent.parent
    router = ConnectorRouter(resource_base_dir / "resources" / "contracts")
    try:
        connector_manager = ConnectorManager(config_manager, router)  # NOQA
        logger.info("Initialized ConnectorManager for Bureau.")
    except Exception as e:
        logger.error(
            f"Failed to initialize ConnectorManager: {e}", exc_info=True
        )
        router = None

    # 6. Initialize the Conductor
    global conductor
    # Derive the plans dir from the config file that was actually loaded, so
    # that an AINARA_CONFIG override points the Conductor at the same config
    # directory every other component uses.
    plans_dir = (
        Path(config_manager.config_file_path).parent / "bureau"
        if config_manager.config_file_path
        else None
    )

    if plans_dir:
        conductor = Conductor(
            plans_dir=plans_dir,
            llm_config=config.get("llm", {}),
            orakle_servers=config.get(
                "orakle.servers", ["http://127.0.0.1:8100"]
            ),
            global_capabilities=global_capabilities,
            step_registry=step_registry,
            router=router,
            config_manager=config_manager,
        )
        conductor.start()
        logger.info(
            "Conductor initialized%s."
        )
    else:
        logger.warning(
            "Could not determine config path for Conductor plans"
            " directory."
        )


def run_agent_in_process(
    llm_config: dict,
    orakle_servers: list,
    blueprint: dict,
    user_context: dict,
    goal: str,
    max_turns: int,
    result_queue: multiprocessing.Queue,
    blacklisted_providers: Any = None,
    global_capabilities: list = None,
    conductor_agent: list = False,
) -> None:
    """
    Worker function executed inside a separate OS process.
    It builds its own LLM backend and Orakle middleware, runs the agent,
    and puts the resulting dict onto ``result_queue``.
    """
    # Import here to avoid issues with process serialization
    from ainara.framework.agent.core import Agent
    from ainara.framework.llm import create_llm_backend
    from ainara.framework.orakle_middleware import OrakleMiddleware

    # ═══════════════════════════════════════════════════════════════════════════
    # TODO: Logging from this child process is NOT captured in bureau.log.
    # The parent process only receives whatever is put onto result_queue.
    # For better forensics, consider implementing a multiprocessing logging
    # pattern (e.g., logging.handlers.QueueHandler + QueueListener in the
    # parent) to route all child logs to the same file.
    # ═══════════════════════════════════════════════════════════════════════════

    providers_to_try = blueprint.get("llm_providers")
    if not providers_to_try:
        default_provider = llm_config.get(
            "selected_provider", "system default"
        )
        logger.warning(
            "No 'llm_providers' defined in blueprint. Falling back to default"
            f" provider: '{default_provider}'"
        )
        providers_to_try = [None]

    if blacklisted_providers is None:
        blacklisted_providers = []

    last_error = None

    # Filter capabilities based on blueprint
    allowed_skills = blueprint.get("allowed_skills", ["*"])
    if "*" in allowed_skills:
        agent_capabilities = global_capabilities or []
    else:
        agent_capabilities = [
            s for s in global_capabilities or [] if s["name"] in allowed_skills
        ]

    # Build the Agent-specific system message
    skills_hint_text = ", ".join(
        [s["description"] for s in agent_capabilities]
    )
    from ainara.framework.template_manager import TemplateManager

    base_system_message = TemplateManager().render(
        "framework.agent.system_prompt", {"skills_hint_text": skills_hint_text}
    )
    final_system_message = base_system_message + blueprint.get(
        "system_message", ""
    )

    for provider in providers_to_try:
        if provider in blacklisted_providers:
            logger.info(
                f"Skipping provider '{provider}' as it was blacklisted by a"
                " previous step."
            )
            continue

        try:
            # Initialize LLM backend for this process with the specific provider
            llm = create_llm_backend(llm_config, selected_provider=provider)

            # Initialize Orakle middleware for this process
            orakle = OrakleMiddleware(
                llm=llm,
                orakle_servers=orakle_servers,
                capabilities=agent_capabilities,
            )
            orakle.system_message = final_system_message

            # Create and run the agent
            agent = Agent(
                llm=llm,
                orakle_middleware=orakle,
                blueprint=blueprint,
                user_context=user_context,
                system_message=final_system_message,
                conductor_agent=conductor_agent,
            )

            # Execute the agent and push the result onto the queue
            result = agent.run(goal, max_turns=max_turns)

            failure_reason = result.get("failure_reason")
            if failure_reason or not result.get("response", ""):
                if provider not in blacklisted_providers:
                    blacklisted_providers.append(provider)

                reason_msg = failure_reason if failure_reason else "Empty response from agent"
                # Record it: this is a real failure, and without it the caller
                # only ever sees "Last error: None" once every provider is tried.
                last_error = f"[{provider}] {reason_msg}"
                logger.warning(f"Agent execution failed with provider '{provider}': {reason_msg}. Retrying next...")
                last_error = f"[{provider}] {reason_msg}"
                # Do not return, let the loop continue to the next provider
            else:
                result_queue.put(result, timeout=5)
                return  # Success! Exit the process.

        except Exception as e:
            last_error = e
            logger.warning(
                f"Agent execution failed with provider '{provider}': {e}."
                " Retrying next..."
            )

            # TODO: Refine blacklist logic. Currently we blacklist on ANY exception.
            # In the future, we should distinguish between global API outages (502, timeouts)
            # and prompt-specific errors (e.g., token limits) so we don't unnecessarily blacklist.
            if provider not in blacklisted_providers:
                blacklisted_providers.append(provider)

    # If we exhaust the loop without returning, all providers failed
    logger.error(
        f"All LLM providers failed for goal. Last error: {last_error}"
    )
    try:
        result_queue.put(
            {
                "error": "AllProvidersFailed",
                "failure_reason": (
                    "All configured LLM providers failed. Last error:"
                    f" {last_error}"
                ),
            },
            timeout=5,
        )
    except Exception as e:
        logger.error(f"Failed to put error result on queue: {e}")


# The previous Future‑based completion callback is no longer needed.
# (All termination now goes through ``_terminate_agent``.)


@app.route("/v1/agents", methods=["POST"])
def create_agent():
    """
    Spawn a new autonomous agent.

    Payload:
        goal (str): The objective.
        blueprint (dict, optional): Agent persona and skills.
        user_context (dict, optional): User profile info.
        max_turns (int, optional): Safety limit.
        execution_timeout (int, optional): Timeout in seconds (-1 for infinite).
    """
    data = request.json
    if not data or "goal" not in data:
        return jsonify({"error": "Missing 'goal' in request body"}), 400

    goal = data["goal"]
    blueprint = data.get("blueprint", {})
    user_context = data.get("user_context", {})
    max_turns = data.get("max_turns", 20)

    # Get timeout from request or config (default 600 seconds)
    execution_timeout = data.get(
        "execution_timeout", config_manager.get("bureau.agent_timeout", 600)
    )

    # Generate a unique ID for this run
    agent_id = str(uuid.uuid4())

    try:
        # Get configuration needed for the process
        llm_config = config_manager.config.get("llm", {})
        orakle_servers = config_manager.config.get(
            "orakle.servers", ["http://127.0.0.1:8100"]
        )

        # Initialize task record
        step_registry[agent_id] = {
            "id": agent_id,
            "status": "PENDING",
            "goal": goal,
            "response": None,
            "turns_used": 0,
            "skills_executed": [],
            "failure_reason": None,
            "error": None,
            "execution_timeout": execution_timeout,
            "future": None,
        }

        # Create a Queue for the agent result
        result_queue = multiprocessing.Queue()

        # Launch a separate process for the agent
        process = multiprocessing.Process(
            target=run_agent_in_process,
            args=(
                llm_config,
                orakle_servers,
                blueprint,
                user_context,
                goal,
                max_turns,
                result_queue,
                None,  # blacklisted_providers
                global_capabilities,
            ),
        )
        process.start()

        # Store process information for monitoring and result retrieval
        step_registry[agent_id]["process"] = process
        step_registry[agent_id]["result_queue"] = result_queue
        step_registry[agent_id]["pid"] = process.pid
        step_registry[agent_id]["status"] = "RUNNING"
        step_registry[agent_id]["start_time"] = time.time()

        return (
            jsonify(
                {
                    "agent_id": agent_id,
                    "status": "RUNNING",
                    "message": "Agent started successfully",
                    "execution_timeout": execution_timeout,
                }
            ),
            202,
        )

    except Exception as e:
        logger.error(f"Failed to create agent: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/v1/agents/<agent_id>", methods=["GET"])
def get_agent_status(agent_id):
    """Get the status and result of an agent run."""
    task = step_registry.get(agent_id)
    if not task:
        return jsonify({"error": "Agent ID not found"}), 404

    # Note: The done callback (_process_agent_completion) handles status updates
    # automatically when the future completes, so we don't need to check future.done()
    # here anymore. We just return the current task state.

    # Determine HTTP status code based on agent status
    status = task.get("status")

    # Remove future from response (not JSON serializable)
    # Remove internal objects that are not JSON‑serialisable
    response_task = {
        k: v
        for k, v in task.items()
        if k not in ("process", "result_queue", "pid", "termination_requested")
    }

    if status == "PENDING" or status == "RUNNING":
        # Still processing
        return jsonify(response_task), 200
    elif status == "COMPLETED":
        # Goal achieved successfully
        return jsonify(response_task), 200
    elif status == "FAILED":
        # Goal not achieved or execution error
        # Use 424 Failed Dependency for goal failures, 500 for execution errors
        if task.get("error"):
            # Execution error (exception)
            return jsonify(response_task), 500
        else:
            # Goal not achieved (logical failure)
            return jsonify(response_task), 424
    else:
        # Unknown status
        return jsonify(response_task), 200


@app.route("/v1/agents/abort-all", methods=["POST"])
def abort_all_agents():
    """
    Cancel every agent that is currently in a non‑terminal state.
    Returns a simple success payload with the number of agents that were
    requested to stop.
    """
    aborted = 0
    for step_id, task in list(step_registry.items()):
        # Skip steps that have already finished (COMPLETED or FAILED)
        if task.get("status") in ("COMPLETED", "FAILED"):
            continue

        # If the step is still running, request termination
        if task.get("status") == "RUNNING":
            _terminate_step(
                step_id,
                task,
                reason="user abort",
            )
            # Mark as FAILED now – the timeout monitor will clean up the process
            task["status"] = "FAILED"
            task["failure_reason"] = "Cancelled by user"
            task["error"] = "UserAbort"
            aborted += 1
        else:
            # For any other intermediate state (e.g., PENDING) mark as aborted
            task["status"] = "FAILED"
            task["failure_reason"] = "Cancelled by user"
            task["error"] = "UserAbort"
            aborted += 1

    return (
        jsonify(
            {
                "message": "All non‑terminal steps have been aborted",
                "steps_aborted": aborted,
            }
        ),
        200,
    )


@app.route("/v1/conductor/status", methods=["GET"])
def conductor_status():
    """Get the status of all conductor plans."""
    if conductor is None:
        return jsonify({"error": "Conductor not initialized"}), 503
    return jsonify(conductor.get_status()), 200


@app.route("/v1/conductor/plans", methods=["GET"])
def list_conductor_plans():
    """List all loaded conductor plans with their metadata."""
    if conductor is None:
        return jsonify({"error": "Conductor not initialized"}), 503
    return jsonify(conductor.get_plans()), 200


@app.route("/v1/conductor/plans/<plan_name>/run", methods=["POST"])
def trigger_conductor_plan(plan_name):
    """
    Trigger a conductor plan on demand.

    Returns 202 with ``run_id`` on success.
    Returns 404 if the plan is unknown, 409 if it is already running or blocked by avoid_if.
    """
    if conductor is None:
        return jsonify({"error": "Conductor not initialized"}), 503

    data = request.get_json(silent=True) or {}
    avoid_if = data.get("avoid_if")
    # Optional per-run variable overrides (e.g. {"coin": "ETH"}) for a
    # coin-parameterized plan. Must be a flat mapping; ignore anything else.
    run_vars = data.get("vars")
    if run_vars is not None and not isinstance(run_vars, dict):
        return jsonify({"error": "'vars' must be a JSON object"}), 400

    run_id, error = conductor.trigger_plan(
        plan_name, avoid_if=avoid_if, vars=run_vars)

    if error == "plan_not_found":
        return jsonify({"error": f"Plan '{plan_name}' not found"}), 404
    if error == "already_running":
        return (
            jsonify(
                {
                    "error": f"Plan '{plan_name}' is already running",
                    "plan_name": plan_name,
                }
            ),
            409,
        )
    if error and error.startswith("avoid_condition_met:"):
        blocking_plan = error.split(":", 1)[1]
        return (
            jsonify(
                {
                    "error": f"Plan '{plan_name}' skipped because '{blocking_plan}' is currently running",
                    "plan_name": plan_name,
                    "blocking_plan": blocking_plan
                }
            ),
            409,
        )
    if error:
        return jsonify({"error": error}), 500

    logger.info("Plan '%s' triggered on demand (run_id=%s)", plan_name, run_id)
    return (
        jsonify(
            {
                "plan_name": plan_name,
                "run_id": run_id,
                "status": "started",
            }
        ),
        202,
    )


@app.route("/health", methods=["GET"])
def health_check():
    """Simple health check."""
    return jsonify({"status": "healthy", "service": "bureau"}), 200


if __name__ == "__main__":
    multiprocessing.freeze_support()

    # Initialize components before starting server
    args = parse_args()
    initialize_components()
    logging_manager.setup(log_level=args.log_level, log_name="bureau.log")

    # Get port from config or default to 8001 (distinct from Orakle's 8000)
    config = config_manager.get_safe_config()
    port = config.get("bureau", {}).get("port", 8010)
    host = config.get("bureau", {}).get("host", "0.0.0.0")

    logger.info(f"Starting Bureau Server on {host}:{port}")
    try:
        app.run(host=host, port=port, debug=False, use_reloader=False)
    finally:
        if conductor:
            conductor.shutdown()
