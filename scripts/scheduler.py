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
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
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

# Trading executor managed services — OPT-IN via scheduler.yaml `services.executor`.
# These run from the SEPARATE executor virtualenv (the venue signing SDKs conflict
# with Ainara's main deps), so they launch with a different interpreter than the
# scheduler's own. Supervising them is process-lifecycle ONLY: it keeps the daemon
# and the position watchdog alive and healthy. It NEVER opens or closes a position
# and NEVER arms any trading cron — "the engine is up" and "the strategy is armed"
# are deliberately separate switches.
EXECUTOR_CMD = "python -m executor.server"
WATCHDOG_CMD = "python -m executor.watchdog"
EXECUTOR_LOG_NAME = "executor.log"
WATCHDOG_LOG_NAME = "executor_watchdog.log"
DEFAULT_EXECUTOR_HEALTH_URL = "http://127.0.0.1:8130/health"
# The position watchdog has no HTTP surface; it freshens a heartbeat file each
# loop. Must match executor/watchdog.py's default (trading.watchdog.heartbeat_file).
DEFAULT_WATCHDOG_HEARTBEAT = os.path.join(
    tempfile.gettempdir(), "ainara_executor_watchdog_heartbeat.txt"
)
DEFAULT_WATCHDOG_HEARTBEAT_MAX_AGE = 30  # seconds (~6× the 5s watchdog poll)


def default_executor_python():
    """Path to the executor virtualenv's interpreter, mirroring _find_venv_python."""
    sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return str(PROJECT_ROOT / "executor" / ".venv" / sub[0] / sub[1])

# Default scheduler settings (overridden by ainara.yaml scheduler: section)
DEFAULT_BUREAU_URL = "http://127.0.0.1:8010"
DEFAULT_ORAKLE_HEALTH_URL = "http://127.0.0.1:8100/health"
DEFAULT_HEALTH_CHECK_INTERVAL = 10
DEFAULT_RESTART_GRACE_PERIOD = 30
DEFAULT_RESTART_GRACE_POLL_INTERVAL = 5
DEFAULT_MAX_RESTART_ATTEMPTS = 3
HEARTBEAT_LOG_INTERVAL = 60
HEALTH_CHECK_TIMEOUT = 3

# Log rotation for the scheduler's OWN captured logs (ORAKLE_LOG/BUREAU_LOG and,
# when managed, executor.log/executor_watchdog.log) — see rotate_log_if_large.
DEFAULT_LOG_ROTATE_MAX_MB = 10
DEFAULT_LOG_ROTATE_BACKUP_COUNT = 5
LOG_ROTATE_CHECK_INTERVAL = 60  # seconds; mirrors HEARTBEAT_LOG_INTERVAL


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

# Managed services (optional). Supervise the trading executor daemon + position
# watchdog alongside Bureau/Orakle, so they don't have to be started by hand. This
# is process-lifecycle only — it keeps them alive/healthy and NEVER opens a
# position or arms any trading cron. Off by default; the daemon/watchdog run from
# the executor's own virtualenv (auto-detected at executor/.venv).
#services:
#  executor:
#    enabled: false
#    #venv_python: "C:/path/to/executor/.venv/Scripts/python.exe"  # override auto-detect
#    #health_url: "http://127.0.0.1:8130/health"
#    #heartbeat_file: "..."       # must match trading.watchdog.heartbeat_file
#    #heartbeat_max_age: 30       # seconds; watchdog considered dead past this
#    #log_dir: "..."              # defaults to ainara.yaml logging.directory, so the
#                                 # executor + watchdog logs sit with every other
#                                 # Ainara log rather than in /tmp

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
    config_paths = config_manager._get_config_paths()
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
    config_paths = config_manager._get_config_paths()
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
        **_load_executor_config(raw),
    }


def default_executor_log_dir():
    """Where the executor services' logs go: the same Logs/ directory as every other
    Ainara log, falling back to LOG_DIR if that cannot be resolved.

    LOG_DIR is "/tmp", which on Windows resolves to C:\\tmp — not the real temp dir,
    and not anywhere anyone thinks to look. These two files are the forensic record
    of the component that moves money: after the 2026-07-27 incident had to be
    reconstructed from venue fill history, "somewhere nobody looks" is not good
    enough. `logging.directory` in ainara.yaml is where the rest already live.

    Deliberately NOT applied to ORAKLE_LOG / BUREAU_LOG: those are the scheduler's
    captured stdout, while the framework writes its OWN rotating orakle.log and
    bureau.log into that same directory. Pointing both at one path would give one
    file two writers.
    """
    try:
        d = ConfigManager().get("logging.directory")
        if d:
            os.makedirs(d, exist_ok=True)
            return d
    except Exception as e:
        log_error(f"could not resolve logging.directory ({e}); "
                  f"executor logs fall back to {LOG_DIR}")
    return LOG_DIR


def _load_log_rotation_config():
    """(max_bytes, backup_count) for rotating the scheduler's OWN captured
    logs — read fresh on every check (see LOG_ROTATE_CHECK_INTERVAL) so a
    config change takes effect without a scheduler restart, same as every
    other trading risk-control knob.

    Deliberately SEPARATE keys from the framework's own logging.max_size_mb /
    logging.backup_count (ainara/framework/logging_setup.py, which already
    rotates orakle.log/bureau.log/pybridge.log via RotatingFileHandler): that
    key's default is a raw BYTE count despite its "_mb" name, so a value
    someone actually sets there meaning megabytes would be read as bytes and
    rotate on almost every line. New code gets its own, correctly-named keys
    rather than inheriting that ambiguity.
    """
    try:
        mgr = ConfigManager()
        max_mb = float(mgr.get("logging.rotation.max_size_mb",
                               DEFAULT_LOG_ROTATE_MAX_MB))
        backups = int(mgr.get("logging.rotation.backup_count",
                             DEFAULT_LOG_ROTATE_BACKUP_COUNT))
        return max_mb * 1024 * 1024, backups
    except Exception as e:
        log_error(f"could not read log-rotation config, using defaults: {e}")
        return (DEFAULT_LOG_ROTATE_MAX_MB * 1024 * 1024,
                DEFAULT_LOG_ROTATE_BACKUP_COUNT)


def rotate_log_if_large(log_file, max_bytes, backup_count):
    """Copytruncate rotation for a log a subprocess holds open as its stdout/
    stderr for its entire lifetime (every log start_service() manages).

    Renaming the live file would leave that subprocess writing into the now-
    invisible, renamed-away inode forever — nothing here can tell a plain
    subprocess to reopen stdout the way SIGHUP tells nginx or syslog to.
    Copying the content out to a numbered backup and then truncating the
    ORIGINAL file IN PLACE keeps the subprocess's existing file descriptor
    valid; it simply starts writing into an empty file again. This is
    logrotate's own 'copytruncate' strategy, built for exactly this situation.

    backup_count <= 0 truncates without keeping history (matches stdlib
    RotatingFileHandler's own backupCount=0 semantics).
    """
    try:
        if not os.path.exists(log_file) or os.path.getsize(log_file) < max_bytes:
            return
        oldest = f"{log_file}.{backup_count}"
        if backup_count > 0 and os.path.exists(oldest):
            os.remove(oldest)
        for i in range(backup_count - 1, 0, -1):
            src, dst = f"{log_file}.{i}", f"{log_file}.{i + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        if backup_count > 0:
            shutil.copy2(log_file, f"{log_file}.1")
        with open(log_file, "r+") as f:
            f.truncate(0)
        log_info(f"rotated {log_file} (reached {max_bytes} bytes)")
    except Exception as e:
        # Never let log-hygiene housekeeping take down the supervisor loop.
        log_error(f"log rotation failed for {log_file}: {e}")


def _load_executor_config(raw):
    """Executor managed-services settings from scheduler.yaml `services.executor`.

    Default OFF: users who don't run the trading strategy never spawn its daemon.

    `enabled` also honours `trading.executor.autostart` in ainara.yaml (OR'd with
    scheduler.yaml's own key), because that file — not this one — is what Polaris's
    setup wizard already reads and writes via the pybridge /config API. Routing the
    toggle through ainara.yaml means the GUI never has to locate or parse
    scheduler.yaml itself: doing that in Node would mean re-deriving the
    AINARA_CONFIG-aware config-directory resolution ConfigManager already owns, which
    is exactly the split-brain that made Bureau load zero plans (see docs/
    progress_report.md 1.1) — one bug from duplicating this logic is enough.
    """
    svc = ((raw.get("services") or {}).get("executor") or {})
    log_dir = svc.get("log_dir") or default_executor_log_dir()
    autostart_flag = bool(ConfigManager().get("trading.executor.autostart", False))
    return {
        "executor_enabled": bool(svc.get("enabled", False)) or autostart_flag,
        "executor_python": svc.get("venv_python") or default_executor_python(),
        "executor_log": os.path.join(log_dir, EXECUTOR_LOG_NAME),
        "watchdog_log": os.path.join(log_dir, WATCHDOG_LOG_NAME),
        "executor_health_url": svc.get(
            "health_url", DEFAULT_EXECUTOR_HEALTH_URL),
        "watchdog_heartbeat_file": svc.get(
            "heartbeat_file", DEFAULT_WATCHDOG_HEARTBEAT),
        "watchdog_heartbeat_max_age": svc.get(
            "heartbeat_max_age", DEFAULT_WATCHDOG_HEARTBEAT_MAX_AGE),
    }


def executor_services(sched_config):
    """The executor daemon + position watchdog as managed-service descriptors,
    or an empty list when management is disabled. The daemon probes via HTTP; the
    watchdog (no HTTP surface) via its heartbeat file."""
    if not sched_config.get("executor_enabled"):
        return []
    py = sched_config["executor_python"]
    cwd = str(PROJECT_ROOT)
    return [
        {"name": "executor", "cmd": EXECUTOR_CMD,
         "log": sched_config["executor_log"],
         "python_exe": py, "cwd": cwd,
         "health": {"type": "http", "url": sched_config["executor_health_url"]}},
        {"name": "watchdog", "cmd": WATCHDOG_CMD,
         "log": sched_config["watchdog_log"],
         "python_exe": py, "cwd": cwd,
         "health": {"type": "heartbeat",
                    "path": sched_config["watchdog_heartbeat_file"],
                    "max_age": sched_config["watchdog_heartbeat_max_age"]}},
    ]


def restart_managed_service(svc, sched_config):
    """Stop and restart a managed service (cross-venv aware), waiting for its own
    health probe. The executor-service analogue of restart_service."""
    identifier = svc["cmd"].split(" -m ")[1]
    log_info(f"Restarting {svc['name']}...")
    stop_process(identifier)
    time.sleep(2)
    success, msg = start_service(
        svc["name"], svc["cmd"], svc["log"], python_exe=svc["python_exe"],
        cwd=svc["cwd"])
    if not success:
        log_error(msg)
        return False
    grace = sched_config["restart_grace_period"]
    poll = sched_config["restart_grace_poll_interval"]
    elapsed = 0
    while elapsed < grace:
        time.sleep(poll)
        elapsed += poll
        if check_health(svc):
            log_info(f"{svc['name']} is healthy after restart")
            return True
    log_error(f"{svc['name']} did not become healthy within {grace}s")
    return False


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


def check_heartbeat(path, max_age_s):
    """Liveness by file freshness — for a service with no HTTP surface (the
    position watchdog). True if the file exists and its timestamp is recent."""
    try:
        if not os.path.exists(path):
            return False
        with open(path, encoding="utf-8") as fh:
            ts = float(fh.read().strip())
        return (time.time() - ts) <= max_age_s
    except (OSError, ValueError):
        return False


def check_health(svc):
    """Health of a managed service, dispatching on its declared probe type."""
    h = svc["health"]
    if h["type"] == "heartbeat":
        return check_heartbeat(h["path"], h["max_age"])
    return check_service_health(h["url"])


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


def start_service(service_name, cmd, log_file, python_exe=None, cwd=None):
    """Start a service if not already running. Returns (success, message).

    `python_exe` selects the interpreter — defaults to the scheduler's own
    (sys.executable) for Orakle/Bureau, but the executor services pass their
    separate venv's interpreter so they load the right dependency set.

    `cwd` sets the working directory. The `ainara` package is pip-installed so
    Orakle/Bureau resolve from anywhere, but the `executor` package is run in place
    via `-m` and only imports when the cwd is the project root — so the executor
    services pass it explicitly.
    """
    if is_service_running(cmd):
        return True, f"{service_name} is already running"

    try:
        # APPEND, never truncate. A supervisor that restarts a crashed service and
        # erases the log explaining why it crashed is worse than no supervisor: the
        # 2026-07-27 watchdog incident was diagnosed from venue fills precisely
        # because its own output was gone, and auto-restart would have destroyed it
        # a second time. Growth is bounded in practice — these services log only on
        # risk, not per poll.
        with open(log_file, "a") as log:
            module = cmd.split(" -m ")[1]
            full_cmd = f'"{python_exe or sys.executable}" -m {module}'

            if os.name == "nt":
                subprocess.Popen(full_cmd, stdout=log, stderr=log, shell=True,
                                 cwd=cwd)
            else:
                subprocess.Popen(
                    full_cmd,
                    stdout=log,
                    stderr=log,
                    shell=True,
                    executable="/bin/bash",
                    cwd=cwd,
                )

        time.sleep(2)

        if is_service_running(cmd):
            return True, f"{service_name} started successfully"
        else:
            return False, f"Failed to start {service_name}"
    except Exception as e:
        return False, f"Error starting {service_name}: {e}"


def stop_services(sched_config=None):
    """Stop Bureau and Orakle — and the executor services too when managed."""
    log_info("Stopping services...")
    stop_process("ainara.bureau.server")
    stop_process("ainara.orakle.server")

    logs = [ORAKLE_LOG, BUREAU_LOG]
    if sched_config and sched_config.get("executor_enabled"):
        # Stop the watchdog BEFORE the daemon: with the daemon already gone the
        # watchdog cannot act on a broken hedge anyway, and this avoids it logging
        # spurious alarms during the brief teardown window.
        stop_process("executor.watchdog")
        stop_process("executor.server")
        # The executor logs are deliberately NOT added to `logs` below: they are the
        # trading stack's forensic record and a clean stop is no reason to destroy
        # it. "Why did it stop?" is a question you ask AFTER stopping.

    for log_file in logs:
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
def trigger_plan(plan_name, bureau_url, avoid_if=None, plan_vars=None):
    """Trigger a plan execution via Bureau API.

    plan_vars (a flat dict, e.g. {"coin": "ETH"}) overrides the plan's own vars
    for this run only — how one coin-parameterized plan is pointed at different
    assets.
    """
    url = f"{bureau_url}/v1/conductor/plans/{plan_name}/run"
    body = {}
    if avoid_if:
        body["avoid_if"] = avoid_if
    if plan_vars:
        body["vars"] = plan_vars
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
            # Optional per-schedule vars override (e.g. vars: {coin: ETH}) so the
            # same coin-parameterized plan can be scheduled per asset. The job id
            # is still the schedule key, so a coin-specific schedule needs its own
            # key (e.g. a "target" plan + distinct key) — kept simple here: one
            # schedule entry, one job, its own vars.
            plan_vars = plan_config.get("vars")
            target_plan = plan_config.get("plan", plan_name)
            scheduler.add_job(
                trigger_plan,
                trigger=trigger,
                args=[target_plan, bureau_url, avoid_if, plan_vars],
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

    # Executor services (opt-in) are supervised alongside — but their failure is
    # NON-FATAL: an unhealthy trading daemon must not take down the rest of Ainara,
    # so it is retried indefinitely rather than triggering the shutdown that a core
    # service failure does.
    managed = executor_services(sched_config)
    all_counted = list(services) + [s["name"] for s in managed]
    restart_counters = {name: 0 for name in all_counted}
    last_heartbeat = time.time()
    last_log_rotation_check = time.time()
    interval = sched_config["health_check_interval"]
    max_attempts = sched_config["max_restart_attempts"]

    while True:
        time.sleep(interval)

        # Heartbeat
        now = time.time()
        if now - last_heartbeat >= HEARTBEAT_LOG_INTERVAL:
            log_info(
                f"Watchdog heartbeat — monitoring "
                f"{len(services) + len(managed)} service(s)"
            )
            last_heartbeat = now

        # Log rotation for every log this scheduler captures directly (raw
        # subprocess stdout/stderr, never rotated on its own — see
        # rotate_log_if_large). Checked far less often than health, since the
        # common case is just a cheap size stat; `managed` is empty when the
        # executor services aren't enabled, so this naturally covers exactly
        # the logs that exist.
        if now - last_log_rotation_check >= LOG_ROTATE_CHECK_INTERVAL:
            max_bytes, backup_count = _load_log_rotation_config()
            for log_file in ([s["log"] for s in services.values()]
                            + [s["log"] for s in managed]):
                rotate_log_if_large(log_file, max_bytes, backup_count)
            last_log_rotation_check = now

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
                        stop_services(sched_config)
                        sys.exit(1)
            else:
                restart_counters[name] = 0

        # Executor services: restart on failure, but NEVER shut Ainara down for them.
        for svc in managed:
            name = svc["name"]
            if not check_health(svc):
                log_info(f"{name} (executor) is unhealthy — restarting")
                if restart_managed_service(svc, sched_config):
                    restart_counters[name] = 0
                else:
                    restart_counters[name] += 1
                    log_error(
                        f"{name} restart failed "
                        f"({restart_counters[name]} in a row); will keep retrying. "
                        "The trading stack is degraded — check its log.")
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
    managed = executor_services(sched_config)
    if managed:
        for svc in managed:
            label = "Executor" if svc["name"] == "executor" else "Watchdog"
            probe = ("heartbeat" if svc["health"]["type"] == "heartbeat"
                     else "health")
            print(f"  {label}: {'running' if check_health(svc) else 'stopped'}"
                  f"  ({probe})")
    else:
        print("  Executor: not managed (services.executor.enabled: false)")
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
    parser.add_argument(
        "--coin",
        metavar="SYMBOL",
        help=(
            "Override the coin for a coin-parameterized plan, e.g. ETH or SOL "
            "(used with --run-plan; sends vars={coin: SYMBOL})"
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
        stop_services(sched_config)
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
        plan_vars = {"coin": args.coin.strip().upper()} if args.coin else None
        success = trigger_plan(
            args.run_plan, sched_config["bureau_url"], avoid_if=avoid_if,
            plan_vars=plan_vars,
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

    # Start the trading executor managed services (opt-in). Process lifecycle only
    # — this brings the daemon + position watchdog up and keeps them healthy; it
    # does NOT open any position or arm any trading cron. A failure here does NOT
    # abort the scheduler: the rest of Ainara should run even if the (optional)
    # trading stack can't start.
    for svc in executor_services(sched_config):
        log_info(f"Starting {svc['name']} (executor venv)...")
        ok, msg = start_service(svc["name"], svc["cmd"], svc["log"],
                                python_exe=svc["python_exe"], cwd=svc["cwd"])
        log_info(f"  {msg}")
    for svc in executor_services(sched_config):
        healthy, waited = False, 0
        while waited < sched_config["restart_grace_period"]:
            if check_health(svc):
                healthy = True
                break
            time.sleep(sched_config["restart_grace_poll_interval"])
            waited += sched_config["restart_grace_poll_interval"]
        log_info(f"  {svc['name']}: {'healthy' if healthy else 'NOT healthy yet'}")
        if not healthy:
            log_error(f"{svc['name']} did not come up — the trading stack may be "
                      "unavailable; check its log and the executor venv.")

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
