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

"""Files the executor's processes use to talk to each other.

The watchdog writes an alarm file the daemon serves on /health and a heartbeat
file the scheduler uses to decide whether the watchdog is alive. Each is
written by one process and read by another on a loop, so every one of them
resolves the path HERE: the watchdog, the daemon and the scheduler used to
each build it themselves, and a writer and reader that disagree look exactly
like a healthy system with nothing to report.

Stdlib only: the watchdog's risk logic is tested under any virtualenv, and
the scheduler (main venv) imports this too.
"""

import contextlib
import os
import platform
import re
import tempfile
import time

ALARM_FILENAME = "watchdog_alarm.json"
HEARTBEAT_FILENAME = "watchdog_heartbeat.txt"
STATE_FILENAME = "watchdog_state.json"
LEASE_DIRNAME = "opening_leases"
_LEASE_NAME = re.compile(r"^(?P<coin>[A-Z0-9]+)\.(?P<expires_ms>\d+)\.lease$")


def default_data_dir():
    """Ainara's default data directory, as framework/config.py computes it.

    The executor cannot import the framework (separate virtualenv), so this
    mirrors ConfigManager.get_default_data_dir. On Windows it takes the
    default "Saved Games" location, as executor/config.py does for the config
    file; the framework writes the resolved data.directory into ainara.yaml,
    which runtime_dir() reads first.
    """
    system = platform.system()
    if system == "Windows":
        return os.path.join(os.path.expanduser("~"), "Saved Games", "Ainara",
                            "Data")
    if system == "Darwin":
        return os.path.join(os.path.expanduser("~/Library/Application Support"),
                            "ainara")
    return os.path.join(os.path.expanduser("~/.local/state"), "ainara")


def runtime_dir(config):
    """Directory for the executor's runtime files: <data.directory>/executor.

    These used to default to the system temp directory, which is cleaned
    without notice, shared by every user of the machine, and per-user on
    Windows, so two processes started differently could disagree on it.
    Resolving only: nothing is created until a file is written.
    """
    base = config.get("data.directory") or default_data_dir()
    return os.path.join(os.path.expanduser(str(base)), "executor")


def alarm_path(config):
    """The watchdog's alarm file. trading.watchdog.alarm_file pins it."""
    return (config.get("trading.watchdog.alarm_file")
            or os.path.join(runtime_dir(config), ALARM_FILENAME))


def heartbeat_path(config):
    """The watchdog's heartbeat file. trading.watchdog.heartbeat_file pins it."""
    return (config.get("trading.watchdog.heartbeat_file")
            or os.path.join(runtime_dir(config), HEARTBEAT_FILENAME))


def state_path(config):
    """The watchdog's durable shave state. trading.watchdog.state_file pins it."""
    return (config.get("trading.watchdog.state_file")
            or os.path.join(runtime_dir(config), STATE_FILENAME))


# ---------------------------------------------------------------------------
# Opening leases: the daemon telling the watchdog "this coin is mid-open".
#
# While /hedge/open is between its two legs, the coin looks exactly like a
# broken hedge. The watchdog's only protection used to be its debounce
# (confirm_polls polls, and a poll takes the venue reads plus the interval),
# which is of the same order as the daemon's fill_timeout_s, so a slow open
# could be flattened by the guard while the daemon was still building it.
#
# Each lease is an empty file whose NAME carries everything, <COIN>.<expires
# epoch ms>.lease, so a reader never parses content a writer might be halfway
# through, and nothing needs locking. An expired lease is ignored, so a daemon
# that dies mid-open cannot leave the guard disarmed for that coin.
# ---------------------------------------------------------------------------

def _lease_coin(symbol):
    return str(symbol or "").upper().split("-")[0].strip()


def lease_dir(config):
    return os.path.join(runtime_dir(config), LEASE_DIRNAME)


def acquire_lease(config, coin, ttl_s):
    """Mark `coin` as mid-open for `ttl_s` seconds. Returns a token for
    release_lease. Raises OSError when the lease cannot be written."""
    directory = lease_dir(config)
    os.makedirs(directory, exist_ok=True)
    now_ms = int(time.time() * 1000)
    # Sweep leases a crashed daemon left behind. Already ignored by readers;
    # this only stops them accumulating.
    for name in os.listdir(directory):
        m = _LEASE_NAME.match(name)
        if m and int(m.group("expires_ms")) <= now_ms:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(directory, name))
    expires_ms = now_ms + int(float(ttl_s) * 1000)
    path = os.path.join(directory, f"{_lease_coin(coin)}.{expires_ms}.lease")
    with open(path, "x", encoding="utf-8"):
        pass
    return path


def release_lease(token):
    """Drop a lease taken by acquire_lease. Never raises."""
    if token:
        with contextlib.suppress(OSError):
            os.remove(token)


def active_leases(config, now=None):
    """Coins with an unexpired opening lease. Raises OSError if unreadable."""
    directory = lease_dir(config)
    if not os.path.isdir(directory):
        return set()
    now_ms = int((time.time() if now is None else now) * 1000)
    coins = set()
    for name in os.listdir(directory):
        m = _LEASE_NAME.match(name)
        if m and int(m.group("expires_ms")) > now_ms:
            coins.add(m.group("coin"))
    return coins

# A Windows reader holding the destination open makes os.replace fail with a
# sharing violation for a few microseconds; a short bounded retry clears it.
_REPLACE_ATTEMPTS = 8
_REPLACE_BACKOFF_S = 0.01


def write_text_atomic(path, text):
    """Replace the contents of `path` in one step.

    A plain open(path, "w") truncates first, so a reader polling the file can
    see it empty or half-written, and both readers here get that wrong:
    the daemon reads a torn alarm as "no alarm" and reports clear during an
    emergency, and the scheduler reads a torn heartbeat as a dead watchdog and
    restarts a healthy one, discarding its in-memory retry state.

    Writes a temporary file in the same directory (a replace across
    filesystems is not atomic) and os.replace()s it over the target, which is
    atomic on Windows and POSIX. The replace is retried briefly on
    PermissionError, the Windows sharing violation described above. No fsync:
    the point is that no reader sees a partial file, not that the last write
    survives a power cut.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ainara-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_BACKOFF_S)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
