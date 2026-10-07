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

"""Bootstrap a source-run development environment for Ainara.

Idempotent: safe to re-run at any time. It will:

  1. Create the Python virtualenv (default: .venv) if it does not exist.
  2. Install Python dependencies (requirements.txt + editable ainara package).
  3. Install Node dependencies via `npm ci` (skipped if already present).
  4. Print how to start the application (the first-boot setup Wizard
     handles the rest of the configuration).

Usage:
    python3 scripts/bootstrap.py [options]

Options:
    --venv-dir DIR     Virtualenv location (default: .venv, or the
                       AINARA_VENV_DIR environment variable).
    --recreate         Delete and recreate the virtualenv from scratch.
    --skip-pip         Skip the Python dependency installation step.
    --skip-npm         Skip the Node dependency installation step.
    --reinstall-npm    Force `npm ci` even if node_modules already exists.

Requirements: Python >= 3.11 (3.12 recommended), Node.js >= 18 and npm.
"""

import argparse
import os
import shutil
import subprocess
import sys
import venv

MIN_PYTHON = (3, 11)
RECOMMENDED_PYTHON = (3, 12)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(msg: str) -> None:
    print(f"[bootstrap] {msg}")


def fatal(msg: str, hint: str = "") -> None:
    print(f"[bootstrap] ERROR: {msg}", file=sys.stderr)
    if hint:
        print(f"[bootstrap] hint: {hint}", file=sys.stderr)
    sys.exit(1)


def check_python_version() -> None:
    version = sys.version_info[:2]
    if version < MIN_PYTHON:
        fatal(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, "
            f"got {version[0]}.{version[1]}."
        )
    if version != RECOMMENDED_PYTHON:
        log(
            f"WARNING: dependencies are pinned against Python "
            f"{RECOMMENDED_PYTHON[0]}.{RECOMMENDED_PYTHON[1]}; you are "
            f"using {version[0]}.{version[1]}. Continuing, but a 3.12 "
            f"interpreter is recommended."
        )


def resolve_venv_dir(requested: str) -> str:
    venv_dir = requested or os.environ.get("AINARA_VENV_DIR") or ".venv"
    return venv_dir if os.path.isabs(venv_dir) else os.path.join(REPO_ROOT, venv_dir)


def venv_python(venv_dir: str) -> str:
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def ensure_venv(venv_dir: str, recreate: bool) -> None:
    if recreate and os.path.isdir(venv_dir):
        log(f"Removing existing virtualenv at {venv_dir} (--recreate)")
        shutil.rmtree(venv_dir)

    if os.path.isfile(venv_python(venv_dir)):
        log(f"Virtualenv found at {venv_dir} — reusing it")
        return

    log(f"Creating virtualenv at {venv_dir} ...")
    result = subprocess.run(
        [sys.executable, "-m", "venv", venv_dir],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        fatal(
            f"Failed to create the virtualenv at {venv_dir}",
            hint=(
                "on Debian/Ubuntu make sure the venv/ensurepip support is "
                "installed (e.g. apt install python3.12-venv)."
            ),
        )


def run_step(cmd, description: str) -> None:
    log(f"{description} ...")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        fatal(f"{description} failed (exit code {result.returncode})")


def install_python_deps(venv_dir: str) -> None:
    python = venv_python(venv_dir)
    run_step(
        [python, "-m", "pip", "install", "--upgrade", "pip"],
        "Upgrading pip",
    )
    run_step(
        [python, "-m", "pip", "install", "-r", "requirements.txt"],
        "Installing Python dependencies (requirements.txt)",
    )
    run_step(
        [python, "-m", "pip", "install", "-e", "."],
        "Installing the ainara package in editable mode",
    )


def install_node_deps(force: bool) -> None:
    if not shutil.which("node") or not shutil.which("npm"):
        fatal(
            "Node.js and npm are required but were not found in PATH",
            hint="install Node.js (>= 18) from https://nodejs.org or via "
                 "your package manager, then re-run the bootstrap.",
        )
    marker = os.path.join(REPO_ROOT, "node_modules", "electron", "dist")
    if os.path.isdir(marker) and not force:
        log(
            "node_modules already present — skipping npm ci "
            "(use --reinstall-npm to force a clean install)"
        )
        return
    run_step(["npm", "ci"], "Installing Node dependencies (npm ci)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap the Ainara source-run development environment."
    )
    parser.add_argument(
        "--venv-dir",
        default=None,
        help="Virtualenv location (default: .venv, or $AINARA_VENV_DIR).",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate the virtualenv from scratch.",
    )
    parser.add_argument(
        "--skip-pip", action="store_true", help="Skip Python dependency install."
    )
    parser.add_argument(
        "--skip-npm", action="store_true", help="Skip Node dependency install."
    )
    parser.add_argument(
        "--reinstall-npm",
        action="store_true",
        help="Force npm ci even if node_modules is already populated.",
    )
    args = parser.parse_args()

    check_python_version()

    venv_dir = resolve_venv_dir(args.venv_dir)
    ensure_venv(venv_dir, args.recreate)

    if args.skip_pip:
        log("Skipping Python dependencies (--skip-pip)")
    else:
        install_python_deps(venv_dir)

    if args.skip_npm:
        log("Skipping Node dependencies (--skip-npm)")
    else:
        install_node_deps(args.reinstall_npm)

    log("Source-run environment ready.")
    print(
        "\n"
        "  Start the application with:\n"
        "\n"
        "      npm start\n"
        "\n"
        "  (equivalent to `npm run start:source`; use `npm run start:bundle`\n"
        "  to boot against the packaged server executables instead).\n"
        "\n"
        "  The graphical setup Wizard will guide you through first-boot\n"
        "  configuration on launch.\n"
    )


if __name__ == "__main__":
    main()
