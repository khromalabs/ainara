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
written by one process and read by another on a loop.

Stdlib only: the watchdog's risk logic is tested under any virtualenv, and
the scheduler (main venv) imports this too.
"""

import contextlib
import os
import tempfile
import time

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
