# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the scheduler's log-rotation housekeeping.

Runs under the main venv (needs psutil/apscheduler, same as scheduler.py
itself):
    python -m unittest scripts.evaluation.tests.test_scheduler_log_rotation

Covers rotate_log_if_large — the copytruncate rotation for logs a subprocess
holds open as its stdout/stderr for its whole lifetime — and
_load_log_rotation_config's defaults/overrides. Does NOT test watchdog_loop
itself: that's an I/O-heavy orchestration loop with no existing test coverage
of its own, same boundary the rest of this test suite already draws around
decide()-style orchestration methods.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts import scheduler as S  # noqa: E402


class RotateLogIfLarge(unittest.TestCase):
    def test_untouched_when_under_the_limit(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "small.log")
            with open(path, "w") as f:
                f.write("x" * 10)
            S.rotate_log_if_large(path, max_bytes=1000, backup_count=3)
            with open(path) as f:
                self.assertEqual(f.read(), "x" * 10)
            self.assertFalse(os.path.exists(f"{path}.1"))

    def test_missing_file_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "does-not-exist.log")
            S.rotate_log_if_large(path, max_bytes=10, backup_count=3)  # no raise

    def test_rotates_when_over_the_limit(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.log")
            with open(path, "w") as f:
                f.write("x" * 100)
            S.rotate_log_if_large(path, max_bytes=50, backup_count=3)
            with open(path) as f:
                self.assertEqual(f.read(), "")  # truncated, not deleted
            with open(f"{path}.1") as f:
                self.assertEqual(f.read(), "x" * 100)  # old content preserved

    def test_backup_count_zero_truncates_without_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.log")
            with open(path, "w") as f:
                f.write("x" * 100)
            S.rotate_log_if_large(path, max_bytes=50, backup_count=0)
            with open(path) as f:
                self.assertEqual(f.read(), "")
            self.assertFalse(os.path.exists(f"{path}.1"))

    def test_numbered_backups_shift_and_the_oldest_is_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.log")
            with open(f"{path}.1", "w") as f:
                f.write("gen1")
            with open(f"{path}.2", "w") as f:
                f.write("gen2")
            with open(path, "w") as f:
                f.write("x" * 100)  # current, over the limit
            S.rotate_log_if_large(path, max_bytes=50, backup_count=2)
            with open(f"{path}.1") as f:
                self.assertEqual(f.read(), "x" * 100)  # yesterday's current
            with open(f"{path}.2") as f:
                self.assertEqual(f.read(), "gen1")  # shifted from .1
            # gen2 (the oldest, beyond backup_count=2) must be gone.
            self.assertFalse(os.path.exists(f"{path}.3"))

    def test_open_handle_keeps_writing_to_the_original_path_after_rotation(self):
        # The property that actually matters: renaming the live file would
        # leave a subprocess's existing stdout fd writing into a now-invisible
        # inode forever. Copytruncate must NOT do that — a handle opened
        # before rotation must still land its writes at the original path.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "held-open.log")
            with open(path, "w") as f:
                f.write("A" * 100)
            handle = open(path, "a")
            try:
                handle.write("before-rotation")
                handle.flush()
                S.rotate_log_if_large(path, max_bytes=50, backup_count=3)
                handle.write("after-rotation")
                handle.flush()
            finally:
                handle.close()

            with open(path) as f:
                current = f.read()
            with open(f"{path}.1") as f:
                backup = f.read()

            self.assertIn("after-rotation", current)
            self.assertNotIn("before-rotation", current)
            self.assertIn("before-rotation", backup)


class LoadLogRotationConfig(unittest.TestCase):
    class _FakeConfigManager:
        def __init__(self, values):
            self._values = values

        def get(self, key, default=None):
            return self._values.get(key, default)

    def test_defaults_when_unset(self):
        with patch.object(S, "ConfigManager", lambda: self._FakeConfigManager({})):
            max_bytes, backups = S._load_log_rotation_config()
        self.assertEqual(max_bytes, S.DEFAULT_LOG_ROTATE_MAX_MB * 1024 * 1024)
        self.assertEqual(backups, S.DEFAULT_LOG_ROTATE_BACKUP_COUNT)

    def test_custom_values_are_honoured(self):
        cfg = self._FakeConfigManager({
            "logging.rotation.max_size_mb": 2,
            "logging.rotation.backup_count": 1,
        })
        with patch.object(S, "ConfigManager", lambda: cfg):
            max_bytes, backups = S._load_log_rotation_config()
        self.assertEqual(max_bytes, 2 * 1024 * 1024)
        self.assertEqual(backups, 1)

    def test_unreadable_config_falls_back_to_defaults(self):
        def raising_ctor():
            raise RuntimeError("boom")
        with patch.object(S, "ConfigManager", raising_ctor):
            max_bytes, backups = S._load_log_rotation_config()
        self.assertEqual(max_bytes, S.DEFAULT_LOG_ROTATE_MAX_MB * 1024 * 1024)
        self.assertEqual(backups, S.DEFAULT_LOG_ROTATE_BACKUP_COUNT)


if __name__ == "__main__":
    unittest.main()
