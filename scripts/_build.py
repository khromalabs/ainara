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

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

# Same list used by servers.spec to strip the TOC. Imported here so the
# post-COLLECT verifier below cannot drift from the filter.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pyinstaller"))
from _shadowed_libs import SHADOWED_RUNTIME_LIBS

try:
    import pkg_resources
    HAVE_PKG_RESOURCES = True
except ImportError:
    HAVE_PKG_RESOURCES = False


BUILDER_IMAGE = "ainara-servers-linux-builder"
SMOKE_IMAGE = "ubuntu:22.04"  # glibc 2.35 — exactly our jammy floor

CONTAINER_BUILD_SCRIPT = r"""
set -euo pipefail
PY=/opt/venv/bin/python
cd /work
"$PY" -m PyInstaller --clean --noconfirm --distpath dist --workpath build/pyi scripts/pyinstaller/servers.spec
"$PY" scripts/_audit_glibc.py dist 2.35
"""

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _venv_python(root):
    """Path to the project-local venv's interpreter for this platform."""
    if sys.platform == "win32":
        return os.path.join(root, "venv", "Scripts", "python.exe")
    return os.path.join(root, "venv", "bin", "python")


def _has_pyarmor(python_exe):
    """True when a `pyarmor` launcher sits next to `python_exe`.

    PyArmor installs its console script into the same bin/ as the
    interpreter it belongs to; its presence is our proxy for "this is
    the licensed environment".
    """
    name = "pyarmor.exe" if sys.platform == "win32" else "pyarmor"
    return os.path.isfile(os.path.join(os.path.dirname(python_exe), name))


def find_obfuscation_python(explicit=None):
    """Pick the interpreter that runs scripts/_obfuscate.py.

    Priority:
      1. --obfuscate-python / POLARIS_OBFUSCATE_PYTHON  (trusted verbatim)
      2. <project_root>/venv                            (auto-detected)
      3. sys.executable                                 (last resort)
    Returns None if no auto candidate has PyArmor installed.
    """
    chosen = explicit or os.environ.get("POLARIS_OBFUSCATE_PYTHON")
    if chosen:
        return chosen
    for cand in (_venv_python(PROJECT_ROOT), sys.executable):
        if _has_pyarmor(cand):
            return cand
    return None


def build_builder_image():
    """Build (or reuse, via layer cache) the Ubuntu 22.04 builder image.

    Uses a throwaway context holding only the Dockerfile and
    requirements.txt so we never upload the whole repo to the daemon.
    """
    dockerfile = os.path.join("scripts", "docker", "Dockerfile.servers-linux")
    with tempfile.TemporaryDirectory(prefix="ainara-builder-ctx-") as ctx:
        shutil.copy("requirements.txt", os.path.join(ctx, "requirements.txt"))
        shutil.copy(dockerfile, os.path.join(ctx, "Dockerfile"))
        run_command(["docker", "build", "-t", BUILDER_IMAGE, ctx])


def run_container_build():
    """Run the PyInstaller stage inside the glibc-2.35 builder container.

    The repo is bind-mounted at /work; the container runs with the invoking
    user's UID so build/ and dist/ land on the host already owned by you
    (no root-owned artifacts, no chown dance).
    """
    project_root = os.path.abspath(os.getcwd())
    run_command([
        "docker", "run", "--rm", "--init",
        "-v", f"{project_root}:/work", "-w", "/work",
        "-e", "POLARIS_EDITION", "-e", "POLARIS_TARGET",
        "-u", f"{os.getuid()}:{os.getgid()}",
        BUILDER_IMAGE,
        "/bin/bash", "-c", CONTAINER_BUILD_SCRIPT,
    ])


def run_smoke_test(target):
    """Boot every built server in a glibc-2.35 container (ubuntu:22.04).

    PASS = the process survives 30 s without dying with a loader/import
    error (servers normally keep running and are killed by the timeout).
    """
    if target == "all":
        dist_name, exes = "servers", ["orakle", "pybridge", "bureau", "sentinel"]
    else:
        dist_name, exes = target, [target]

    base = os.path.abspath(os.path.join("dist", dist_name))
    available = [e for e in exes if os.path.isfile(os.path.join(base, e))]
    if not available:
        print(f"Smoke test skipped: no executables found in {base}")
        return

    script = "set +e\n"
    for exe in available:
        script += (
            f"timeout -k 5 30 /d/{exe} > /tmp/smoke.log 2>&1\n"
            "rc=$?\n"
            'if grep -Eq "GLIBC(X)?_[0-9]|ImportError|ModuleNotFoundError|'
            'cannot (open shared object file|load library)|error while loading shared libs" /tmp/smoke.log; then\n'
            f'  echo "SMOKE FAIL: {exe}"; cat /tmp/smoke.log; exit 1\n'
            "fi\n"
            f'echo "smoke ok: {exe} (exit code $rc)"\n'
        )
    run_command(["docker", "run", "--rm", "-v", f"{base}:/d",
                 SMOKE_IMAGE, "/bin/bash", "-c", script])


def check_bundle_integrity(dist_name):
    """Fail if a shadowed runtime library leaked into the bundle.

    servers.spec is supposed to strip these before COLLECT; this walks
    the produced tree to confirm it did. Runs on every build (not only
    under --smoke-test) because it is a cheap filename scan, and because
    _build.py can short-circuit with "already exists", in which case the
    spec never ran at all.
    """
    root = os.path.join("dist", dist_name)
    if not os.path.isdir(root):
        return  # nothing produced; the caller already failed elsewhere

    hits = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn in SHADOWED_RUNTIME_LIBS:
                hits.append(os.path.join(dirpath, fn))

    if not hits:
        return

    print("\nBundle integrity check FAILED — shadowed runtime libraries "
          "found in the built tree:")
    for h in hits:
        print(f"  - {h}")
    print(
        "These precede the host's copies on the loader search path and "
        "break system libraries (libjack, libportaudio, ...) that look "
        "for newer GLIBCXX symbols. servers.spec's SHADOWED_RUNTIME_LIBS "
        "strip did not take effect — check Analysis.binaries, or whether "
        "a pyinstaller hook re-added them after the filter."
    )
    sys.exit(1)


def run_command(cmd):
    """Run a command and print its output"""
    print(f"Running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    # Print output in real-time
    for line in process.stdout:
        print(line, end="")

    process.wait()
    if process.returncode != 0:
        print(f"Error: Command failed with exit code {process.returncode}")
        sys.exit(1)


def check_dependencies():
    """Check if all required dependencies are installed"""
    if not HAVE_PKG_RESOURCES:
        print("Warning: pkg_resources not available, skipping dependency check")
        return True

    print("\n=== Reading dependencies from requirements.txt... ===")
    try:
        with open('requirements.txt', 'r') as f:
            lines = f.readlines()

        required_packages = []
        for line in lines:
            line = line.strip()
            # Ignore comments, blank lines, and special flags
            if not line or line.startswith('#') or line.startswith('--'):
                continue
            # Strip version specifiers and extras (e.g., "mcp[cli]==1.7.1" -> "mcp")
            package_name = line.split('==')[0].split('>=')[0].split('<=')[0].split('@')[0].split('[')[0].strip()
            required_packages.append(package_name)
    except FileNotFoundError:
        print("Error: requirements.txt not found. Cannot check dependencies.")
        return False

    print("\n=== Checking for required packages... ===")
    missing = []
    for package in required_packages:
        try:
            pkg_resources.get_distribution(package)
        except pkg_resources.DistributionNotFound:
            missing.append(package)

    if missing:
        print("\n=== Missing dependencies detected ===")
        print("The following packages are required but not installed:")
        for package in missing:
            print(f"  - {package}")
        print("\nPlease install them using:")
        print(f"  pip install {' '.join(missing)}")
        print("\nAdditionally, ensure the Spacy model is downloaded:")
        print("  python -m spacy download en_core_web_sm")
        print("\nThen run this script again.")
        return False

    print("All required packages are installed.")
    return True


def build_executables(force=False, target="all", use_container=False, smoke=False,
                      obfuscate_python=None):
    """Build the server executables (joined bundle or a single target)."""
    if use_container and sys.platform != "linux":
        print("Error: --container builds require a Linux host (docker + uid mapping).")
        return False

    # Get paths to spec files
    servers_spec = os.path.join("scripts", "pyinstaller", "servers.spec")

    # Create a combined distribution directory
    dist_dir = "dist/"
    os.makedirs(dist_dir, exist_ok=True)

    # Clean up build and dist directories if force is True
    if force:
        print("\n=== Cleaning up build and dist directories ===\n")
        if os.path.exists("build"):
            shutil.rmtree("build")
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)

    dist_name = "servers" if target == "all" else target
    out_path = os.path.join(dist_dir, dist_name)
    if not force and os.path.isdir(out_path) and os.listdir(out_path):
        print(f"\n=== Skipping build ({out_path} already exists) ===\n")
        print("Use --force to rebuild anyway")
        return True

    if use_container:
        if shutil.which("docker") is None:
            print("Error: docker not found — required for --container builds.")
            return False
        build_builder_image()
    elif not check_dependencies():
        # Host dependency check only applies to native builds; the
        # container installs its own environment from requirements.txt.
        return False

    # Host stage: obfuscation (licensed PyArmor and the build secret stay
    # on the host; the container only consumes build/supporters_compiled/).
    # The interpreter is discovered, not inherited from the caller's shell:
    # the licensed PyArmor lives in ./venv, and _build.py may be started
    # from a different (e.g. system) Python.
    obf_exe = find_obfuscation_python(obfuscate_python)
    if not obf_exe:
        print(
            "Error: no interpreter with the licensed PyArmor found.\n"
            f"  Looked in: {_venv_python(PROJECT_ROOT)}, {sys.executable}\n"
            "  Install PyArmor into ./venv, or pass --obfuscate-python "
            "<path> (or set POLARIS_OBFUSCATE_PYTHON)."
        )
        return False
    obf_ver = subprocess.check_output(
        [obf_exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
        text=True,
    ).strip()
    print(f"\n=== Obfuscation stage (host: {obf_exe} — Python {obf_ver}) ===\n")
    run_command([obf_exe, os.path.join("scripts", "_obfuscate.py")])

    if use_container:
        print("\n=== PyInstaller stage (glibc 2.35 container) ===\n")
        run_container_build()
    else:
        print("\n=== PyInstaller stage (native — inherits this host's glibc; "
              "use --container for distributable Linux bundles) ===\n")
        run_command([
            "pyinstaller", servers_spec, "--clean", "--noconfirm",
            "--distpath", "dist", "--workpath", "build/pyi",
        ])

    # Independent verifier for the servers.spec strip. Runs on every
    # invocation (not only --smoke-test): cheap, and the only guard on
    # the "dist/ already existed" short-circuit path.
    if sys.platform != "win32":
        check_bundle_integrity(dist_name)

    if smoke:
        print(f"\n=== Smoke test ({SMOKE_IMAGE}, glibc 2.35) ===\n")
        run_smoke_test(target)

    print(f"\nBuild complete! Executables are in {os.path.abspath(out_path)}")
    return True


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build Orakle and/or PyBridge executables"
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force rebuild even if executables already exist",
    )
    parser.add_argument(
        "-e",
        "--edition",
        choices=["public", "supporters"],
        default=None,
        help=(
            "Distribution edition (public|supporters). "
            "Required unless POLARIS_EDITION is set."
        ),
    )
    parser.add_argument(
        "-t",
        "--target",
        choices=["all", "orakle", "pybridge", "bureau", "sentinel"],
        default="all",
        help=(
            "Build only this server (default: all). Passed to servers.spec "
            "as POLARIS_TARGET."
        ),
    )
    parser.add_argument(
        "-c",
        "--container",
        action="store_true",
        help=(
            "Run the PyInstaller stage inside a glibc-2.35 container "
            "(python:3.12-slim-jammy / Ubuntu 22.04). Linux hosts only."
        ),
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "After building, boot each server in a glibc-2.35 container "
            "(ubuntu:22.04) and fail on loader/import errors."
        ),
    )
    parser.add_argument(
        "--obfuscate-python",
        default=None,
        help=(
            "Interpreter that has the licensed PyArmor installed. "
            "Default: ./venv/bin/python, falling back to the current "
            "interpreter. Overrides POLARIS_OBFUSCATE_PYTHON."
        ),
    )
    args = parser.parse_args()

    edition = args.edition or os.environ.get("POLARIS_EDITION")
    if edition not in ("public", "supporters"):
        if args.edition is None and "POLARIS_EDITION" not in os.environ:
            parser.error(
                "edition is required (use -e/--edition or set POLARIS_EDITION)"
            )
        parser.error(f"Invalid edition: {edition!r} (expected 'public' or 'supporters')")
    os.environ["POLARIS_EDITION"] = edition
    os.environ["POLARIS_TARGET"] = args.target

    sys.exit(0 if build_executables(
        force=args.force,
        target=args.target,
        use_container=args.container,
        smoke=args.smoke_test,
        obfuscate_python=args.obfuscate_python,
    ) else 1)
