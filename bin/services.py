#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil
import requests

# Log file paths
LOG_DIR = "/tmp"
ORAKLE_LOG = os.path.join(LOG_DIR, "orakle.log")
PYBRIDGE_LOG = os.path.join(LOG_DIR, "pybridge.log")
OLLAMA_LOG = os.path.join(LOG_DIR, "ollama.log")

# Service commands
ORAKLE_CMD = "python -m ainara.orakle.server"
PYBRIDGE_CMD = "python -m ainara.framework.pybridge"
OLLAMA_CMD = "ollama"
TEMPORARILY_DISABLE_OLLAMA = True  # Set to False to re-enable Ollama

# Service health endpoints
ORAKLE_HEALTH_URL = "http://localhost:5000/health"
PYBRIDGE_HEALTH_URL = "http://localhost:5001/health"

# Virtual environment paths to check (in order of preference)
VENV_PATHS = [
    os.path.expanduser("~/ainara-env"),
    os.path.expanduser("~/.venv"),
    os.path.expanduser("~/venv"),
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "venv"
    ),
]


def check_service_health(url, service_name, timeout=2):
    """Check if a service is healthy by calling its health endpoint"""
    try:
        response = requests.get(url, timeout=timeout)
        response_json = json.loads(response.text)
        if (
            response.status_code == 200
            and response_json["status"].strip().lower() == "ok"
        ):
            return True
        else:
            return False
    except requests.RequestException:
        return False


def watch_services_health(services_to_watch, check_interval=3):
    """
    Watch the health of services and report any issues

    Args:
        services_to_watch: Dict of service names to their health URLs
        check_interval: How often to check health in seconds
    """
    try:
        print("Monitoring...")
        fails = 0
        fails_limit = 4
        was_unhealthy = False

        while True:
            health_status = {}
            unhealthy_services = []
            time.sleep(check_interval)

            for service, url in services_to_watch.items():
                is_healthy = check_service_health(url, service)
                health_status[service] = (
                    "healthy" if is_healthy else "unhealthy"
                )

                if not is_healthy:
                    unhealthy_services.append(service)

            # Alert about unhealthy services
            if unhealthy_services:
                was_unhealthy = True
                print(
                    "ERROR: The following service(s) are unhealthy:"
                    f" {', '.join(unhealthy_services)}"
                )
                fails += 1
                if fails == fails_limit:
                    print("Max fail limits reached, exiting...")
                    stop_services()
                    sys.exit(1)
                else:
                    print("Retrying...")
            else:
                if was_unhealthy:
                    print("Services are healthy now")
                    was_unhealthy = False

    except KeyboardInterrupt:
        print("Exiting...")
        stop_services()
        sys.exit(0)


def find_and_activate_venv():
    """Find and activate a virtual environment"""
    for venv_path in VENV_PATHS:
        # Check for Linux/macOS style virtual environment
        if os.path.exists(os.path.join(venv_path, "bin", "activate")):
            return True, venv_path
        # Check for Windows style virtual environment
        elif os.path.exists(
            os.path.join(venv_path, "Scripts", "activate.bat")
        ):
            return True, venv_path
    return False, None


def check_command(command):
    """Check if a command is available in the system"""
    return shutil.which(command) is not None


def is_service_running(command):
    """Check if a service is running using psutil"""
    # For Python services, look for the module name in the command line
    if command.startswith("python"):
        module_name = command.split(" -m ")[-1] if " -m " in command else ""
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info["cmdline"]
                if cmdline and len(cmdline) > 1:
                    # Check if this is a Python process running our module
                    if "python" in cmdline[
                        0
                    ].lower() and module_name in " ".join(cmdline):
                        return True
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                pass
    else:
        # For non-Python services, just look for the command name
        cmd_name = command.split()[0]
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if cmd_name in proc.info["name"] or (
                    proc.info["cmdline"]
                    and cmd_name in " ".join(proc.info["cmdline"])
                ):
                    return True
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                pass
    return False


def get_services_status():
    """Get status of all services"""
    status = {
        "orakle": "running" if is_service_running(ORAKLE_CMD) else "stopped",
        "pybridge": "running" if is_service_running(PYBRIDGE_CMD) else "stopped",
    }
    if not TEMPORARILY_DISABLE_OLLAMA:
        status["ollama"] = "running" if is_service_running(OLLAMA_CMD + " serve") else "stopped"
    else:
        status["ollama"] = "temporarily disabled"
    return status


def stop_services():
    """Stop all running services using psutil"""
    try:
        # Define service identifiers
        service_identifiers = {
            "orakle": "ainara.orakle.server",
            "pybridge": "ainara.framework.pybridge",
        }
        if not TEMPORARILY_DISABLE_OLLAMA:
            service_identifiers["ollama"] = OLLAMA_CMD

        # Find and terminate processes
        for service, identifier in service_identifiers.items():
            print(f"Stopping {service}...")
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = proc.info["cmdline"]
                    if not cmdline:
                        continue

                    cmdline_str = " ".join(cmdline)

                    if identifier in cmdline_str:
                        print(f"  Found {service} process (PID: {proc.pid})")
                        try:
                            # Try graceful termination first
                            p = psutil.Process(proc.pid)
                            p.terminate()

                            # Wait for up to 3 seconds
                            gone, alive = psutil.wait_procs([p], timeout=3)

                            # If still alive, force kill
                            if alive:
                                print(
                                    f"  Force killing {service} (PID:"
                                    f" {proc.pid})"
                                )
                                p.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    pass

        # Clean logs
        for log_file in [ORAKLE_LOG, PYBRIDGE_LOG, OLLAMA_LOG]:
            if os.path.exists(log_file):
                os.remove(log_file)

        return True
    except Exception as e:
        print(f"Error stopping services: {e}", file=sys.stderr)
        return False


def start_service(service, skip=False, venv_active=False, venv_path=None):
    """Start a specific service if it's not already running"""
    if service == "orakle":
        cmd = ORAKLE_CMD
        log_file = ORAKLE_LOG
        args = []
    elif service == "pybridge":
        cmd = PYBRIDGE_CMD
        log_file = PYBRIDGE_LOG
        args = []
    elif service == "ollama":
        if TEMPORARILY_DISABLE_OLLAMA:
            return {
                "status": "info",
                "message": "Ollama is temporarily disabled (change TEMPORARILY_DISABLE_OLLAMA to False to enable)"
            }
        cmd = OLLAMA_CMD
        log_file = OLLAMA_LOG
        args = ["serve"]

        # Check if Ollama is installed
        if not check_command(cmd):
            return {
                "status": "error",
                "message": "Ollama not found. Please install Ollama first.",
            }

        # Check if the model is already pulled
        model_name = os.environ.get("LOCAL_LLM_MODEL", "llama3")
        try:
            # Check if model exists
            result = subprocess.run(
                [cmd, "list"], capture_output=True, text=True
            )
            if model_name not in result.stdout:
                print(f"Model {model_name} not found. Pulling it now...")
                subprocess.run([cmd, "pull", model_name], check=True)
        except Exception as e:
            print(f"Error checking/pulling model: {e}")
    else:
        return {"status": "error", "message": f"Unknown service: {service}"}

    # Check if service is already running
    if is_service_running(cmd):
        return {"status": "info", "message": f"{service} is already running"}

    # Check if we should skip this service
    if skip:
        return {
            "status": "info",
            "message": f"Skipping {service} as requested",
        }

    # Start the service
    try:
        with open(log_file, "w") as log:
            # If we're using a venv and this is a Python service, use the venv python
            # move one directory up
            cwd = os.getcwd()
            if venv_active and service in ["orakle", "pybridge"]:
                # Get the module part from the command
                module = cmd.split(" -m ")[1]

                # Create a platform-specific activation command
                if sys.platform == "win32":
                    # Windows
                    activate_script = os.path.join(
                        venv_path, "Scripts", "activate.bat"
                    )

                    # For Windows, we'll create a temporary batch file that activates the venv and runs the command
                    temp_batch = os.path.join(
                        tempfile.gettempdir(), f"run_{service}.bat"
                    )
                    with open(temp_batch, "w") as batch:
                        batch.write("@echo off\n")
                        batch.write(f'call "{activate_script}"\n')
                        batch.write(f'python -m {module} {" ".join(args)}\n')

                    # print("CURRENT DIR: " + os.getcwd())
                    # print(f"WILL LAUNCH: {temp_batch}")
                    os.chdir(os.path.dirname(cwd))
                    subprocess.Popen(
                        temp_batch, stdout=log, stderr=log, shell=True
                    )
                    os.chdir(cwd)
                else:
                    # Linux/macOS
                    activate_script = os.path.join(
                        venv_path, "bin", "activate"
                    )

                    # For Linux/macOS, we can use source directly
                    shell = "/bin/bash"
                    if sys.platform == "darwin" and os.path.exists("/bin/zsh"):
                        shell = "/bin/zsh"  # Use zsh on newer macOS

                    full_cmd = (
                        f"source {activate_script} && python -m"
                        f" {module} {' '.join(args)}"
                    )
                    # print("CURRENT DIR: " + os.getcwd())
                    # print(f"WILL LAUNCH: {full_cmd}")
                    os.chdir(os.path.dirname(cwd))
                    subprocess.Popen(
                        full_cmd,
                        stdout=log,
                        stderr=log,
                        shell=True,
                        executable=shell,
                    )
                    os.chdir(cwd)
            else:
                if not check_command(cmd.split()[0]):
                    return {
                        "status": "error",
                        "message": f"Command not found: {cmd.split()[0]}",
                    }
                os.chdir(os.path.dirname(cwd))
                subprocess.Popen([cmd] + args, stdout=log, stderr=log)
                os.chdir(cwd)

        # Give it a moment to start
        time.sleep(1)

        # Check if it started successfully
        if is_service_running(cmd):
            return {
                "status": "success",
                "message": f"{service} started successfully",
            }
        else:
            return {"status": "error", "message": f"Failed to start {service}"}
    except Exception as e:
        return {"status": "error", "message": f"Error starting {service}: {e}"}


def tail_logs():
    """Tail all log files with color coding using Python's built-in file operations"""
    try:
        # Define color codes
        colors = {
            "orakle": "\033[31m",  # Red
            "pybridge": "\033[33m",  # Yellow
            # "whisper": "\033[32m",  # Green
            "ollama": "\033[36m",  # Cyan
        }
        reset = "\033[0m"

        # Windows doesn't support ANSI colors in cmd.exe by default
        if sys.platform == "win32" and not os.environ.get("ANSICON"):
            # Try to enable VT100 emulation on Windows 10+
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except (ImportError, AttributeError):
                # If we can't enable colors, disable them
                for service in colors:
                    colors[service] = ""
                reset = ""

        # Open log files for reading
        log_files = {}
        log_positions = {}

        if not argsg.skip_orakle:
            log_files["orakle"] = open(ORAKLE_LOG, "r")
            log_positions["orakle"] = 0

        if not argsg.skip_pybridge:
            log_files["pybridge"] = open(PYBRIDGE_LOG, "r")
            log_positions["pybridge"] = 0

        if not argsg.skip_ollama:
            log_files["ollama"] = open(OLLAMA_LOG, "r")
            log_positions["ollama"] = 0

        print("Tailing logs (press Ctrl+C to stop)...")

        # Tail the logs
        try:
            while True:
                for service, f in log_files.items():
                    f.seek(log_positions[service])
                    new_lines = f.readlines()
                    if new_lines:
                        for line in new_lines:
                            print(
                                f"{colors[service]}{service}:"
                                f" {line.strip()}{reset}"
                            )
                        log_positions[service] = f.tell()
                time.sleep(0.5)
        finally:
            # Close all files
            for f in log_files.values():
                f.close()

    except KeyboardInterrupt:
        print("\nStopped tailing logs")


def run_setup(install=False):
    """Run the setup script"""
    setup_script = Path(__file__).parent / "setup.py"

    if not setup_script.exists():
        return {"status": "error", "message": "Setup script not found"}

    try:
        cmd = [sys.executable, str(setup_script)]
        if install:
            cmd.append("--install")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return {
                "status": "success",
                "message": "Setup completed successfully",
            }
        else:
            return {
                "status": "error",
                "message": f"Setup failed: {result.stderr}",
            }
    except Exception as e:
        return {"status": "error", "message": f"Error running setup: {e}"}


def handle_service_failure(service_failed, results):
    """Handle a service failure by stopping all services and exiting"""
    if service_failed:
        print("A service failed to start. Stopping all services...")
        stop_services()
        return True
    return False


def check_and_start_service(
    service_name, args, results, venv_active, venv_path
):
    """Start a service and handle any failures"""
    if not getattr(args, f"skip_{service_name}"):
        results[service_name] = start_service(
            service_name,
            skip=getattr(args, f"skip_{service_name}"),
            venv_active=venv_active,
            venv_path=venv_path,
        )
        if results[service_name]["status"] == "error" and not args.force:
            print(
                f"ERROR: Failed to start {service_name}:"
                f" {results[service_name]['message']}"
            )
            return True
    return False


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Manage Ainara services")
    parser.add_argument(
        "--skip-orakle",
        action="store_true",
        help="Skip starting the Orakle server",
    )
    parser.add_argument(
        "--skip-pybridge",
        action="store_true",
        help="Skip starting the Pybridge server",
    )
    parser.add_argument(
        "--skip-ollama",
        action="store_true",
        help="Skip starting the Ollama LLM server",
    )
    parser.add_argument(
        "--stop", action="store_true", help="Stop all running servers"
    )
    parser.add_argument(
        "--tail", action="store_true", help="Just tail the log files"
    )
    parser.add_argument(
        "--status", action="store_true", help="Check status of all services"
    )
    parser.add_argument(
        "--setup", action="store_true", help="Run the environment setup script"
    )
    parser.add_argument(
        "--install", action="store_true", help="Install missing dependencies"
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="Don't try to activate a virtual environment",
    )
    parser.add_argument(
        "--ollama-model",
        help="Specify the Ollama model to use (default: llama3)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Continue even if some services fail to start",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Monitor health of services after starting",
    )
    parser.add_argument(
        "--health-interval",
        type=int,
        default=30,
        help="Interval in seconds between health checks (default: 30)",
    )
    args = parser.parse_args()
    global argsg
    argsg = args

    # Set Ollama model if specified
    if args.ollama_model:
        os.environ["LOCAL_LLM_MODEL"] = args.ollama_model

    # Just tail logs if requested
    if args.tail:
        tail_logs()
        return

    # Check status if requested
    if args.status:
        status = get_services_status()
        print("Service Status:")
        print(f"  Orakle:   {status['orakle']}")
        print(f"  Pybridge: {status['pybridge']}")
        print(f"  Ollama:   {status['ollama']}")
        if TEMPORARILY_DISABLE_OLLAMA:
            print("    Note: Ollama is temporarily disabled (change TEMPORARILY_DISABLE_OLLAMA to False to enable)")
        return

    # Stop services if requested
    if args.stop:
        success = stop_services()
        if success:
            print("All servers stopped successfully")
        else:
            print("Failed to stop some servers")
        return

    # Run setup if requested
    if args.setup or args.install:
        result = run_setup(install=args.install)
        print(result["message"])
        return

    # Try to find and activate a virtual environment unless --no-venv is specified
    venv_active = False
    venv_path = None
    if not args.no_venv:
        venv_active, venv_path = find_and_activate_venv()
        if venv_active:
            print(f"Using virtual environment: {venv_path}")
        elif not venv_active:
            print(
                "Warning: No virtual environment found. Services may not work"
                " correctly."
            )
            print("Use --no-venv to suppress this warning.")

    # Start services
    # TODO force configuration restart
#    if os.path.exists("/home/ruben/.config/ainara/ainara.yaml"):
#        os.remove("/home/ruben/.config/ainara/ainara.yaml")
#    if os.path.exists("/home/ruben/.config/ainara/polaris/polaris.json"):
#        os.remove("/home/ruben/.config/ainara/polaris/polaris.json")
    results = {}
    service_failed = False

    # Start Orakle
    service_failed = check_and_start_service(
        "orakle", args, results, venv_active, venv_path
    )

    # If a service failed and we're not forcing, stop everything and exit
    if handle_service_failure(service_failed, results):
        return 1

    # Wait a bit before starting Pybridge
    time.sleep(3)

    # Start Pybridge
    service_failed = check_and_start_service(
        "pybridge", args, results, venv_active, venv_path
    )

    # If a service failed and we're not forcing, stop everything and exit
    if handle_service_failure(service_failed, results):
        return 1

    # If a service failed and we're not forcing, stop everything and exit
    if handle_service_failure(service_failed, results):
        return 1

    # Start Ollama
    service_failed = check_and_start_service(
        "ollama", args, results, venv_active, venv_path
    )

    # If a service failed and we're not forcing, stop everything and exit
    if handle_service_failure(service_failed, results):
        return 1

    # Output results
    for service, result in results.items():
        print(f"{service}: {result['message']}")

    try:
        # If health check is enabled, monitor service health
        if args.health_check:
            services_to_watch = {}
            if not args.skip_orakle:
                services_to_watch["orakle"] = ORAKLE_HEALTH_URL
            if not args.skip_pybridge:
                services_to_watch["pybridge"] = PYBRIDGE_HEALTH_URL

            if services_to_watch:
                watch_services_health(services_to_watch)
            else:
                print("No services to monitor for health.")
                print("Running...")
        else:
            print("Running...")
        while True:
            time.sleep(1)  # Sleep for 1 second
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
