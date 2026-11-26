# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
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

"""Source-checkout dependency guard.

People following the project via git get new Python dependencies the
moment they pull, and nothing in git itself can react to that (hooks do
not transfer across clones). This module closes the gap at the only
point every startup path shares: service startup.

``ensure_requirements()`` compares a digest of the checkout's
``requirements.txt`` against one stored in the running virtualenv; on
mismatch (first start after a dependency bump) it runs
``pip install -r requirements.txt`` once, records the digest, and only
then lets startup continue. When the digests match the whole check
costs one stat and one small-file hash.

Behavioral contract:
  - stdlib-only and side-effect-free on the happy path, so it is safe
    to call from package import time (it runs before the heavy imports
    of every service entry point).
  - Three services may start in parallel (Polaris spawns them): a lock
    file in the venv serializes the install; the losers poll until the
    winner has recorded the new digest.
  - Fail-open: if pip fails or a poller times out, startup proceeds
    anyway and the real ImportError surfaces with its actual name.
    The digest is not written on failure, so the next start retries.
  - Skipped entirely for frozen (PyInstaller) builds, for checkouts
    without a ``requirements.txt`` (pip-installed installs), and when
    ``AINARA_SKIP_REQUIREMENTS_GUARD`` is set.
"""

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

DIGEST_FILE = ".ainara-requirements.sha256"
LOCK_FILE = ".ainara-requirements.lock"
LOCK_STALE_SECONDS = 15 * 60
WAIT_TIMEOUT_SECONDS = 10 * 60
POLL_INTERVAL_SECONDS = 2

_guard_ran = False


def _log(message: str) -> None:
    """Emit a guard log line.

    Import-time logging may not be configured yet, and service managers
    capture stderr, so print is the channel that always lands somewhere.
    """
    print(f"[requirements-guard] {message}", file=sys.stderr, flush=True)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_digest(digest_path: Path, digest: str) -> None:
    digest_path.write_text(digest + "\n", encoding="utf-8")


def requirements_digest_file(venv_dir: Path) -> Path:
    return venv_dir / DIGEST_FILE


def _lock_is_stale(lock_path: Path) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    return age > LOCK_STALE_SECONDS


def _acquire_lock(lock_path: Path) -> bool:
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        if _lock_is_stale(lock_path):
            # Steal: the previous holder crashed or hung far too long.
            _log(f"stealing stale lock {lock_path.name}")
            lock_path.unlink(missing_ok=True)
            return _acquire_lock(lock_path)
        return False


def _wait_for_new_digest(
    lock_path: Path, digest_path: Path, current: str
) -> None:
    """Poll while another process installs; fail-open on timeout."""
    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        if not lock_path.exists():
            if digest_path.is_file() and \
                    digest_path.read_text().strip() == current:
                return
            # Lock released without a matching digest: the install
            # failed; let startup continue and surface the real error.
            return
    _log("timed out waiting for a concurrent dependency install")


def _install(requirements: Path) -> None:
    _log(
        "requirements.txt changed since the last install; running"
        " pip install (this may take a while on the first start after a"
        " pull)"
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check",
            "-r", str(requirements),
        ],
        check=False,
    )
    if result.returncode != 0:
        _log(
            "pip install FAILED; starting anyway (a missing-module error"
            " below names the real gap), the next start will retry"
        )


def ensure_requirements() -> None:
    """Bring the running virtualenv in sync with requirements.txt.

    See the module docstring for the full contract. Never raises.
    """
    global _guard_ran
    if _guard_ran:
        return
    _guard_ran = True

    try:
        _ensure_requirements_inner()
    except Exception as e:  # noqa: BLE001 - import-time safety net
        _log(f"unexpected error, skipping check: {e!r}")


def _ensure_requirements_inner() -> None:
    if getattr(sys, "frozen", False):
        return
    if os.environ.get("AINARA_SKIP_REQUIREMENTS_GUARD"):
        return

    package_root = Path(__file__).resolve().parent.parent  # .../ainara/
    requirements = package_root.parent / "requirements.txt"
    if not requirements.is_file():
        # Not a source checkout (e.g. pip-installed package).
        return

    venv_dir = Path(sys.prefix)
    digest_path = requirements_digest_file(venv_dir)
    current = _digest(requirements)

    if digest_path.is_file() and digest_path.read_text().strip() == current:
        return

    lock_path = venv_dir / LOCK_FILE
    if not _acquire_lock(lock_path):
        _wait_for_new_digest(lock_path, digest_path, current)
        return

    try:
        _install(requirements)
        _write_digest(digest_path, current)
    finally:
        lock_path.unlink(missing_ok=True)
