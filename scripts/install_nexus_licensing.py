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

"""Install the prebuilt private `nexuslicensing` wheel into the project venv.

End users running from source need this wheel for license-gated Nexus
bundles (open bundles work with no licensing setup at all). This script
replaces the manual `pip install https://.../<wheel>.whl` step described
in the README:

1. Detects the current platform tag (win_amd64, linux_x86_64,
   macosx_11_0_x86_64, macosx_11_0_arm64).
2. Fetches the version manifest (`latest.json`) published next to the
   wheels on the download server.
3. Skips the install if the manifest version is already present in the
   venv (idempotent; override with --force).
4. Downloads the wheel, verifies its sha256 against the manifest, and
   pip-installs it into the venv.

stdlib-only; safe to re-run.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request

DEFAULT_MANIFEST_URL = (
    "https://download.ainara.app/nexuslicensing/latest.json"
)
PACKAGE = "nexuslicensing"

SUPPORTED_PLATFORMS = (
    "win_amd64",
    "linux_x86_64",
    "macosx_11_0_x86_64",
    "macosx_11_0_arm64",
)


def log(msg: str) -> None:
    print(f"[nexus-licensing] {msg}")


def fatal(msg: str, hint: str = "") -> None:
    print(f"[nexus-licensing] ERROR: {msg}", file=sys.stderr)
    if hint:
        print(f"[nexus-licensing] hint: {hint}", file=sys.stderr)
    sys.exit(1)


def detect_platform_tag(explicit: str = "") -> str:
    if explicit:
        if explicit not in SUPPORTED_PLATFORMS:
            fatal(
                f"unknown platform tag {explicit!r}",
                hint=f"supported tags: {', '.join(SUPPORTED_PLATFORMS)}",
            )
        return explicit
    machine = platform.machine().lower()
    if sys.platform == "win32":
        if machine not in ("amd64", "x86_64"):
            fatal(f"unsupported Windows architecture: {machine!r}")
        return "win_amd64"
    if sys.platform == "darwin":
        if machine in ("arm64", "aarch64"):
            return "macosx_11_0_arm64"
        return "macosx_11_0_x86_64"
    if sys.platform == "linux":
        if machine == "x86_64":
            return "linux_x86_64"
        fatal(
            f"unsupported Linux architecture: {machine!r}",
            hint="no prebuilt wheel exists for this platform; the wheel "
                 "can be rebuilt from the closed licensing checkout.",
        )
    fatal(
        f"unsupported platform: {sys.platform} / {machine}",
        hint="use --platform to force one of: "
             + ", ".join(SUPPORTED_PLATFORMS),
    )


def venv_python(venv_dir: str) -> str:
    if sys.platform == "win32":
        python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        python = os.path.join(venv_dir, "bin", "python")
    if not os.path.isfile(python):
        fatal(
            f"no venv interpreter found at {python}",
            hint="run `npm run setup` first, or pass --venv-dir / set "
                 "AINARA_VENV_DIR.",
        )
    return python


def installed_version(python: str) -> str:
    """Version of the package inside the venv, or '' if not installed."""
    code = (
        "import importlib.metadata as m;"
        "print(m.version(%r))" % PACKAGE
    )
    result = subprocess.run(
        [python, "-c", code],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return ""  # not installed


def fetch_json(url: str):
    req = urllib.request.Request(
        url, headers={"User-Agent": "ainara-bootstrap/1"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "ainara-bootstrap/1"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install the prebuilt private nexuslicensing wheel into the "
            "project venv (idempotent)."
        )
    )
    parser.add_argument(
        "--venv-dir",
        default=None,
        help="Virtualenv location (default: .venv, or $AINARA_VENV_DIR).",
    )
    parser.add_argument(
        "--platform",
        default="",
        help="Force a platform tag instead of auto-detecting "
             f"({', '.join(SUPPORTED_PLATFORMS)}).",
    )
    parser.add_argument(
        "--manifest-url",
        default=DEFAULT_MANIFEST_URL,
        help="URL of the latest.json version manifest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall even if the manifest version is already installed.",
    )
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_dir = args.venv_dir or os.environ.get("AINARA_VENV_DIR")
    if not venv_dir:
        # Default to .venv, but honour a pre-existing legacy venv/ so older
        # checkouts don't get a duplicate virtualenv (same rule as bootstrap).
        if not os.path.isdir(os.path.join(repo_root, ".venv")) and os.path.isdir(
            os.path.join(repo_root, "venv")
        ):
            venv_dir = os.path.join(repo_root, "venv")
        else:
            venv_dir = os.path.join(repo_root, ".venv")
    python = venv_python(venv_dir)
    plat = detect_platform_tag(args.platform)

    log(f"venv: {venv_dir}")
    log(f"platform tag: {plat}")

    try:
        manifest = fetch_json(args.manifest_url)
    except Exception as e:
        fatal(
            f"could not fetch version manifest from {args.manifest_url}: {e}",
            hint="check your network connection; if the problem persists "
                 "the wheel can be installed manually (see README, "
                 "'Nexus licensing').",
        )
    version = manifest.get("version")
    entry = (manifest.get("platforms") or {}).get(plat)
    if not version or not entry:
        fatal(
            f"manifest does not list a wheel for platform {plat!r}",
            hint=f"manifest keys: {', '.join((manifest.get('platforms') or {}).keys())}",
        )
    filename = entry.get("file")
    expected_sha = entry.get("sha256")
    if not filename or not expected_sha:
        fatal(
            f"manifest entry for {plat!r} is missing 'file' or 'sha256'",
        )

    current = installed_version(python)
    if current == version and not args.force:
        log(f"{PACKAGE} {version} already installed — nothing to do")
        return

    base_url = args.manifest_url.rsplit("/", 1)[0]
    url = f"{base_url}/{filename}"
    log(f"downloading {url}")
    try:
        data = fetch_bytes(url)
    except Exception as e:
        fatal(f"download failed: {e}")
    actual_sha = sha256_hex(data)
    if actual_sha != expected_sha:
        fatal(
            f"sha256 mismatch for {filename}: expected {expected_sha}, "
            f"got {actual_sha}",
            hint="the file on the server may be corrupt or tampered with; "
                 "do NOT install it.",
        )
    log(f"sha256 verified: {actual_sha[:16]}…")

    with tempfile.TemporaryDirectory(prefix="nexuslicensing-") as tmp:
        wheel_path = os.path.join(tmp, filename)
        with open(wheel_path, "wb") as f:
            f.write(data)
        cmd = [python, "-m", "pip", "install", "--no-deps", wheel_path]
        if args.force:
            cmd.insert(-1, "--force-reinstall")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            fatal(f"pip install failed (exit code {result.returncode})")

    final = installed_version(python)
    if final != version:
        fatal(
            f"installed version check failed: expected {version}, "
            f"found {final!r}"
        )
    log(f"{PACKAGE} {version} installed successfully")
    log("gated Nexus bundles can now verify subscriptions; no env var "
        "or secret file is needed")


if __name__ == "__main__":
    main()
