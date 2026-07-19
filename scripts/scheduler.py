#!/usr/bin/env python3
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

"""
Ainara Sentinel Scheduler — starts Bureau + Orakle, monitors health, and triggers
orchestration plans on cron schedules defined in scheduler.yaml.

Sample config for `<ainara_config>/scheduler.yaml`:

# Daemon settings
#bureau_url: "http://127.0.0.1:8010"
#orakle_health_url: "http://127.0.0.1:8100/health"
#health_check_interval: 10
#restart_grace_period: 30
#max_restart_attempts: 3

# Plan schedules
plans:
  trading_routine:
    cron: "0 9 * * 1-5"
    enabled: true
  news_digest:
    cron: "0 8 * * *"
    enabled: false


"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Self-re-exec under virtual environment (before any third-party imports)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_VENV_PATHS = [
    os.path.expanduser("~/ainara-env"),
    os.path.expanduser("~/.venv"),
    os.path.expanduser("~/venv"),
    os.path.join(str(PROJECT_ROOT), "venv"),
]


def _running_in_venv():
    """Return True if the current interpreter is inside a virtual environment."""
    return (
        hasattr(sys, "real_prefix")  # old-style virtualenv
        or (sys.prefix != sys.base_prefix)  # stdlib venv / modern virtualenv
    )


def _find_venv_python():
    """Find a venv python binary from known locations (stdlib only)."""
    for venv_path in _VENV_PATHS:
        venv_dir = Path(venv_path)
        if os.name == "nt":
            candidate = venv_dir / "Scripts" / "python.exe"
        else:
            candidate = venv_dir / "bin" / "python"
        if candidate.exists():
            return str(candidate)
    return None


if not _running_in_venv():
    _venv_python = _find_venv_python()
    if _venv_python:
        # Re-exec the same script under the venv interpreter
        os.execv(_venv_python, [_venv_python] + sys.argv)
    elif not getattr(sys, "frozen", False) and not hasattr(sys, "_MEIPASS"):
        print(
            "WARNING: No virtual environment found and not running inside one. "
            "Third-party dependencies may be missing.",
            file=sys.stderr,
        )

# ---------------------------------------------------------------------------
# Now safe to import third-party packages
# ---------------------------------------------------------------------------
import argparse  # noqa: E402
import json  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import psutil  # noqa: E402
import requests  # noqa: E402
import yaml  # noqa: E402
from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

# ---------------------------------------------------------------------------
# Add project root to sys.path so we can import ainara.framework
# ---------------------------------------------------------------------------
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ainara.framework.config import ConfigManager  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_DIR = "/tmp"
PID_FILE = os.path.join(LOG_DIR, "ainara-scheduler.pid")
ORAKLE_LOG = os.path.join(LOG_DIR, "orakle.log")
BUREAU_LOG = os.path.join(LOG_DIR, "bureau.log")

ORAKLE_CMD = "python -m ainara.orakle.server"
BUREAU_CMD = "python -m ainara.bureau.server"

# Default scheduler settings (overridden by ainara.yaml scheduler: section)
DEFAULT_BUREAU_URL = "http://127.0.0.1:8010"
DEFAULT_ORAKLE_HEALTH_URL = "http://127.0.0.1:8100/health"
DEFAULT_HEALTH_CHECK_INTERVAL = 10
DEFAULT_RESTART_GRACE_PERIOD = 30
DEFAULT_RESTART_GRACE_POLL_INTERVAL = 5
DEFAULT_MAX_RESTART_ATTEMPTS = 3
HEARTBEAT_LOG_INTERVAL = 60
HEALTH_CHECK_TIMEOUT = 3


# ---------------------------------------------------------------------------
# Logging helpers (simple stdout, no dependency on framework logger)
# ---------------------------------------------------------------------------
def log_info(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")


def log_error(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] ERROR: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_SCHEDULER_YAML = """\
# Ainara Sentinel Scheduler configuration
# Place this file in your ainara config directory (e.g. ~/.config/ainara/)

# Daemon settings (uncomment to override defaults)
#bureau_url: "http://127.0.0.1:8010"
#orakle_health_url: "http://127.0.0.1:8100/health"
#health_check_interval: 10
#restart_grace_period: 30
#restart_grace_poll_interval: 5
#max_restart_attempts: 3

# Plan schedules
plans:
  # Example plan (disabled by default):
  # trading_routine:
  #   cron: "0 9 * * 1-5"
  #   enabled: true
  #   avoid_if:
  #     - other_plan_name
  # news_digest:
  #   cron: "0 8 * * *"
  #   enabled: false
"""


def find_scheduler_yaml(config_manager):
    """Find scheduler.yaml in the platform-specific ainara config directory.

    Searches the same config paths that ConfigManager uses (e.g.
    ~/.config/ainara/ on Linux, %APPDATA%/ainara/ on Windows).

    Returns the Path to scheduler.yaml if found, None otherwise.
    """
    config_paths = config_manager.get_default_config_paths()
    for config_path in config_paths:
        # config_path points to ainara.yaml; parent is the config directory
        scheduler_yaml = config_path.parent / "scheduler.yaml"
        if scheduler_yaml.exists():
            return scheduler_yaml
    return None


def load_scheduler_yaml(config_manager):
    """Load and parse the scheduler.yaml file.

    If no scheduler.yaml exists, creates a default template in the first
    available config directory.

    Returns the full parsed dict, or an empty dict if not found/created.
    """
    path = find_scheduler_yaml(config_manager)
    if path:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        log_info(f"Loaded scheduler config from: {path}")
        return data

    # No file found — create a default template
    config_paths = config_manager.get_default_config_paths()
    if config_paths:
        config_dir = config_paths[0].parent
        config_dir.mkdir(parents=True, exist_ok=True)
        new_path = config_dir / "scheduler.yaml"
        try:
            new_path.write_text(DEFAULT_SCHEDULER_YAML)
            log_info(f"Created default scheduler.yaml at: {new_path}")
        except OSError as e:
            log_error(f"Failed to create default scheduler.yaml: {e}")
    else:
        log_info(
            "No scheduler.yaml found and no config directory available"
        )

    return {}


def load_scheduler_config(raw):
    """Extract daemon settings from the parsed scheduler.yaml data."""
    return {
        "bureau_url": raw.get("bureau_url", DEFAULT_BUREAU_URL),
        "orakle_health_url": raw.get(
            "orakle_health_url", DEFAULT_ORAKLE_HEALTH_URL
        ),
        "health_check_interval": raw.get(
            "health_check_interval", DEFAULT_HEALTH_CHECK_INTERVAL
        ),
        "restart_grace_period": raw.get(
            "restart_grace_period", DEFAULT_RESTART_GRACE_PERIOD
        ),
        "restart_grace_poll_interval": raw.get(
            "restart_grace_poll_interval",
            DEFAULT_RESTART_GRACE_POLL_INTERVAL,
        ),
        "max_restart_attempts": raw.get(
            "max_restart_attempts", DEFAULT_MAX_RESTART_ATTEMPTS
        ),
    }


def load_schedules(raw):
    """Extract plan schedules from the parsed scheduler.yaml data.

    Returns a dict of plan_name -> {"cron": str, "enabled": bool}
    """
    return raw.get("plans") or {}


# ---------------------------------------------------------------------------
# PID file lock (single-instance guard)
# ---------------------------------------------------------------------------
def acquire_pid_lock():
    """Ensure only one scheduler instance runs at a time.

    If a PID file exists and the process is still alive, abort.
    If the PID file is stale, overwrite it.
    """
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                # Extra check: verify it's actually our scheduler process
                try:
                    proc = psutil.Process(old_pid)
                    cmdline = " ".join(proc.cmdline())
                    if "scheduler" in cmdline:
                        log_error(
                            f"Another scheduler instance is already running "
                            f"(PID {old_pid}). Use --stop first or --logs to "
                            f"view output."
                        )
                        sys.exit(1)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass  # Process gone or inaccessible — stale lock
        except (ValueError, OSError):
            pass  # Corrupt PID file — overwrite it

    # Write our PID
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError as e:
        log_error(f"Failed to write PID file: {e}")


def release_pid_lock():
    """Remove the PID file on exit."""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(PID_FILE)
    except (ValueError, OSError):
        pass


# ---------------------------------------------------------------------------
# Health checking
# ---------------------------------------------------------------------------


def check_service_health(url, timeout=None):
    """Check if a service is healthy by calling its health endpoint."""
    if timeout is None:
        timeout = HEALTH_CHECK_TIMEOUT
    try:
        response = requests.get(url, timeout=timeout)
        response_json = json.loads(response.text)
        status = response_json.get("status", "").strip().lower()
        return response.status_code == 200 and status in ("ok", "healthy")
    except requests.RequestException:
        return False


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------
def is_service_running(command):
    """Check if a service is running using psutil."""
    module_name = ""
    if " -m " in command:
        module_name = command.split(" -m ")[-1]

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if not cmdline or len(cmdline) < 2:
                continue
            cmdline_str = " ".join(cmdline)
            if module_name and module_name in cmdline_str:
                return True
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            pass
    return False


def stop_process(identifier):
    """Stop processes matching the given identifier string."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"]
            if not cmdline:
                continue
            if identifier in " ".join(cmdline):
                p = psutil.Process(proc.pid)
                p.send_signal(
                    signal.SIGINT if os.name != "nt" else signal.SIGTERM
                )
                gone, alive = psutil.wait_procs([p], timeout=3)
                if alive:
                    p.kill()
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            pass


def start_service(service_name, cmd, log_file):
    """Start a service if not already running. Returns (success, message)."""
    if is_service_running(cmd):
        return True, f"{service_name} is already running"

    try:
        with open(log_file, "w") as log:
            module = cmd.split(" -m ")[1]
            full_cmd = f"{sys.executable} -m {module}"

            if os.name == "nt":
                subprocess.Popen(full_cmd, stdout=log, stderr=log, shell=True)
            else:
                subprocess.Popen(
                    full_cmd,
                    stdout=log,
                    stderr=log,
                    shell=True,
                    executable="/bin/bash",
                )

        time.sleep(2)

        if is_service_running(cmd):
            return True, f"{service_name} started successfully"
        else:
            return False, f"Failed to start {service_name}"
    except Exception as e:
        return False, f"Error starting {service_name}: {e}"


def stop_services():
    """Stop Bureau and Orakle."""
    log_info("Stopping services...")
    stop_process("ainara.bureau.server")
    stop_process("ainara.orakle.server")

    for log_file in [ORAKLE_LOG, BUREAU_LOG]:
        if os.path.exists(log_file):
            os.remove(log_file)

    log_info("Services stopped")


def restart_service(service_name, cmd, log_file, health_url, sched_config):
    """Stop and restart a service, waiting for it to become healthy."""
    identifier = cmd.split(" -m ")[1] if " -m " in cmd else cmd
    log_info(f"Restarting {service_name}...")

    stop_process(identifier)
    time.sleep(2)

    success, msg = start_service(service_name, cmd, log_file)
    if not success:
        log_error(msg)
        return False

    grace = sched_config["restart_grace_period"]
    poll = sched_config["restart_grace_poll_interval"]
    elapsed = 0

    while elapsed < grace:
        time.sleep(poll)
        elapsed += poll
        if check_service_health(health_url):
            log_info(f"{service_name} is healthy after restart")
            return True

    log_error(f"{service_name} did not become healthy within {grace}s")
    return False


# ---------------------------------------------------------------------------
# Plan triggering
# ---------------------------------------------------------------------------
def trigger_plan(plan_name, bureau_url, avoid_if=None):
    """Trigger a plan execution via Bureau API."""
    url = f"{bureau_url}/v1/conductor/plans/{plan_name}/run"
    body = {}
    if avoid_if:
        body["avoid_if"] = avoid_if
    try:
        response = requests.post(url, json=body or None, timeout=30)
        if response.status_code == 200 or response.status_code == 202:
            log_info(f"Plan '{plan_name}' triggered successfully")
            return True
        elif response.status_code == 409:
            log_info(
                f"Plan '{plan_name}' skipped (conflict): {response.text}"
            )
            return True
        else:
            log_error(
                f"Plan '{plan_name}' trigger failed: "
                f"{response.status_code} {response.text}"
            )
            return False
    except requests.RequestException as e:
        log_error(f"Plan '{plan_name}' trigger error: {e}")
        return False


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------
def build_scheduler(schedules, bureau_url):
    """Create and configure APScheduler with jobs from scheduler.yaml."""
    scheduler = BackgroundScheduler()

    for plan_name, plan_config in schedules.items():
        if not plan_config.get("enabled", False):
            log_info(f"Plan '{plan_name}' is disabled, skipping")
            continue

        cron_expr = plan_config.get("cron")
        if not cron_expr:
            log_error(f"Plan '{plan_name}' has no cron expression, skipping")
            continue

        # Parse cron expression (minute hour day month day_of_week)
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            log_error(
                f"Plan '{plan_name}' has invalid cron expression: {cron_expr}"
            )
            continue

        try:
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
            avoid_if = plan_config.get("avoid_if")
            scheduler.add_job(
                trigger_plan,
                trigger=trigger,
                args=[plan_name, bureau_url, avoid_if],
                id=plan_name,
                name=f"Plan: {plan_name}",
                replace_existing=True,
            )
            log_info(f"Scheduled plan '{plan_name}' with cron: {cron_expr}")
        except Exception as e:
            log_error(f"Failed to schedule plan '{plan_name}': {e}")

    return scheduler


# ---------------------------------------------------------------------------
# Log streaming (--logview)
# ---------------------------------------------------------------------------
def stream_logs(stop_event=None):
    """Stream color-coded logs from service log files.

    If stop_event is provided, runs in a background thread and stops when the
    event is set.  If stop_event is None, runs in the foreground until
    interrupted with Ctrl+C.
    """
    colors = {
        "orakle": "\033[31m",  # Red
        "bureau": "\033[34m",  # Blue
    }
    reset = "\033[0m"

    # Enable ANSI on Windows
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except (ImportError, AttributeError):
            for key in colors:
                colors[key] = ""
            reset = ""

    log_files = {}
    positions = {}

    def _should_stop():
        if stop_event is not None:
            return stop_event.is_set()
        return False

    while not _should_stop():
        # Open files lazily once they exist
        for name, path in [("orakle", ORAKLE_LOG), ("bureau", BUREAU_LOG)]:
            if name not in log_files and os.path.exists(path):
                try:
                    log_files[name] = open(path, "r")
                    positions[name] = 0
                except OSError:
                    pass

        for name, f in log_files.items():
            try:
                f.seek(positions[name])
                new_lines = f.readlines()
                if new_lines:
                    for line in new_lines:
                        print(f"{colors[name]}{name}: {line.rstrip()}{reset}")
                    positions[name] = f.tell()
            except OSError:
                pass

        time.sleep(0.5)

    # Cleanup
    for f in log_files.values():
        try:
            f.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Watchdog loop
# ---------------------------------------------------------------------------
def watchdog_loop(sched_config):
    """Monitor service health and restart unhealthy services."""
    services = {
        "orakle": {
            "cmd": ORAKLE_CMD,
            "log": ORAKLE_LOG,
            "health_url": sched_config["orakle_health_url"],
        },
        "bureau": {
            "cmd": BUREAU_CMD,
            "log": BUREAU_LOG,
            "health_url": f"{sched_config['bureau_url']}/health",
        },
    }

    restart_counters = {name: 0 for name in services}
    last_heartbeat = time.time()
    interval = sched_config["health_check_interval"]
    max_attempts = sched_config["max_restart_attempts"]

    while True:
        time.sleep(interval)

        # Heartbeat
        now = time.time()
        if now - last_heartbeat >= HEARTBEAT_LOG_INTERVAL:
            log_info(
                f"Watchdog heartbeat — monitoring {len(services)} service(s)"
            )
            last_heartbeat = now

        for name, svc in services.items():
            if not check_service_health(svc["health_url"]):
                log_info(
                    f"{name} is unhealthy (attempt "
                    f"{restart_counters[name] + 1}/{max_attempts})"
                )
                success = restart_service(
                    name,
                    svc["cmd"],
                    svc["log"],
                    svc["health_url"],
                    sched_config,
                )
                if success:
                    restart_counters[name] = 0
                else:
                    restart_counters[name] += 1
                    if restart_counters[name] >= max_attempts:
                        log_error(
                            f"{name} failed to restart after "
                            f"{max_attempts} attempts. Shutting down."
                        )
                        stop_services()
                        sys.exit(1)
            else:
                restart_counters[name] = 0


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------
def print_status(sched_config, schedules):
    """Print service and schedule status."""
    orakle_healthy = check_service_health(sched_config["orakle_health_url"])
    bureau_healthy = check_service_health(
        f"{sched_config['bureau_url']}/health"
    )

    print("Service Status:")
    print(f"  Orakle:  {'running' if orakle_healthy else 'stopped'}")
    print(f"  Bureau:  {'running' if bureau_healthy else 'stopped'}")
    print()
    print("Scheduled Plans:")
    if not schedules:
        print("  (none)")
    else:
        for plan_name, plan_config in schedules.items():
            enabled = plan_config.get("enabled", False)
            cron = plan_config.get("cron", "N/A")
            status = "enabled" if enabled else "disabled"
            print(f'  {plan_name}: cron="{cron}" [{status}]')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Ainara Sentinel Scheduler — manage services and orchestration plans"
        )
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop Bureau and Orakle services",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show service and schedule status",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress log streaming in main mode (run as silent daemon)",
    )
    parser.add_argument(
        "--logs",
        action="store_true",
        help="Attach to a running instance and stream service logs",
    )
    parser.add_argument(
        "--run-plan",
        metavar="PLAN_NAME",
        help="Trigger a specific plan immediately and exit",
    )
    parser.add_argument(
        "--avoid-if",
        metavar="PLANS",
        help=(
            "Comma-separated list of plan names that block execution "
            "(used with --run-plan)"
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Load configuration
    config_manager = ConfigManager()
    raw_config = load_scheduler_yaml(config_manager)
    sched_config = load_scheduler_config(raw_config)
    schedules = load_schedules(raw_config)

    # Handle --stop
    if args.stop:
        stop_services()
        return

    # Handle --status
    if args.status:
        print_status(sched_config, schedules)
        return

    # Handle --logs (attach to running instance)
    if args.logs:
        if not os.path.exists(ORAKLE_LOG) and not os.path.exists(BUREAU_LOG):
            log_error(
                "No log files found. Is the scheduler running?"
            )
            sys.exit(1)
        log_info("Streaming logs (Ctrl+C to detach)...")
        try:
            stream_logs()  # Foreground, blocks until Ctrl+C
        except KeyboardInterrupt:
            pass
        return

    # Handle --run-plan (trigger one plan immediately)
    if args.run_plan:
        bureau_healthy = check_service_health(
            f"{sched_config['bureau_url']}/health"
        )
        if not bureau_healthy:
            log_error("Bureau is not running. Start the scheduler first.")
            sys.exit(1)
        avoid_if = (
            [p.strip() for p in args.avoid_if.split(",")]
            if args.avoid_if
            else None
        )
        success = trigger_plan(
            args.run_plan, sched_config["bureau_url"], avoid_if=avoid_if
        )
        sys.exit(0 if success else 1)

    # --- Main mode: start services + watchdog + scheduler ---
    acquire_pid_lock()
    log_info("Ainara Sentinel Scheduler starting...")
    log_info(f"Using Python: {sys.executable}")

    # Start Orakle
    log_info("Starting Orakle...")
    success, msg = start_service("orakle", ORAKLE_CMD, ORAKLE_LOG)
    log_info(f"  {msg}")
    if not success:
        log_error("Failed to start Orakle, aborting")
        stop_services()
        sys.exit(1)

    # Wait before starting Bureau (Orakle needs to be ready)
    time.sleep(5)

    # Start Bureau
    log_info("Starting Bureau...")
    success, msg = start_service("bureau", BUREAU_CMD, BUREAU_LOG)
    log_info(f"  {msg}")
    if not success:
        log_error("Failed to start Bureau, aborting")
        stop_services()
        sys.exit(1)

    # Wait for both services to be healthy
    log_info("Waiting for services to become healthy...")
    max_wait = sched_config["restart_grace_period"]
    elapsed = 0
    poll = sched_config["restart_grace_poll_interval"]

    while elapsed < max_wait:
        orakle_ok = check_service_health(sched_config["orakle_health_url"])
        bureau_ok = check_service_health(
            f"{sched_config['bureau_url']}/health"
        )
        if orakle_ok and bureau_ok:
            break
        time.sleep(poll)
        elapsed += poll

    if not (orakle_ok and bureau_ok):
        log_error("Services did not become healthy in time, aborting")
        stop_services()
        sys.exit(1)

    log_info("All services healthy")

    # Build and start the cron scheduler
    scheduler = build_scheduler(schedules, sched_config["bureau_url"])
    scheduler.start()
    log_info("Scheduler started")

    # Start log streaming thread (default on, suppress with --quiet)
    stop_event = threading.Event()
    log_thread = None
    if not args.quiet:
        log_thread = threading.Thread(
            target=stream_logs, args=(stop_event,), daemon=True
        )
        log_thread.start()

    # Enter watchdog loop (blocks until exit)
    try:
        watchdog_loop(sched_config)
    except KeyboardInterrupt:
        log_info("Shutting down...")
    finally:
        stop_event.set()
        scheduler.shutdown(wait=False)
        stop_services()
        release_pid_lock()
        if log_thread:
            log_thread.join(timeout=2)


if __name__ == "__main__":
    main()
