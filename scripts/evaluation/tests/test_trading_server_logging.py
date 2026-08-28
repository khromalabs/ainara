# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""The daemon's access-log filter (executor venv).

The scheduler polls /health every 10s, which was ~700 KB/day of
`"GET /health HTTP/1.1" 200` in the one log whose job is telling you what happened
to your orders. QuietHealthProbes drops those lines.

What matters is what it must NOT drop. This is a filter sitting in front of the
order log, so an over-broad pattern would silently delete the evidence a future
incident depends on — the same class of loss as truncating the file.

Run:
  executor/.venv/Scripts/python.exe \
    scripts/evaluation/tests/test_trading_server_logging.py
"""

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.evaluation.tests._executor_env import (  # noqa: E402
    require_executor_deps)

# Before the executor imports below: they need the venue signing SDKs, which
# live only in the executor's virtualenv. Skips with a reason there instead of
# failing to import.
require_executor_deps()

from executor.server import QuietHealthProbes  # noqa: E402

STAMP = '127.0.0.1 - - [28/Jul/2026 12:38:02] '


def line(request, status):
    return f'{STAMP}"{request}" {status} -'


class QuietHealthProbesFilter(unittest.TestCase):
    def setUp(self):
        self.f = QuietHealthProbes()

    def _kept(self, msg):
        rec = logging.LogRecord("werkzeug", logging.INFO, "", 0, msg, None, None)
        return bool(self.f.filter(rec))

    def test_successful_health_probes_are_dropped(self):
        self.assertFalse(self._kept(line("GET /health HTTP/1.1", 200)))
        self.assertFalse(self._kept(line("GET /health HTTP/1.1", 204)))
        self.assertFalse(self._kept(line("GET /health?x=1 HTTP/1.1", 200)))

    def test_a_FAILING_health_probe_is_kept(self):
        # The daemon failing its own liveness check is exactly the line you go
        # looking for afterwards.
        for status in (500, 502, 404, 401):
            self.assertTrue(self._kept(line("GET /health HTTP/1.1", status)),
                            f"status {status} must survive")

    def test_order_traffic_is_never_touched(self):
        for request in ("POST /hedge/open HTTP/1.1", "POST /hedge/close HTTP/1.1",
                        "POST /venues/hyperliquid/order HTTP/1.1",
                        "POST /venues/dydx/cancel HTTP/1.1",
                        "GET /venues/dydx/state HTTP/1.1"):
            self.assertTrue(self._kept(line(request, 200)), request)

    def test_a_similarly_named_route_is_not_swallowed(self):
        # /health[^"]* would have eaten these too.
        for request in ("GET /healthz HTTP/1.1", "GET /healthcheck HTTP/1.1",
                        "GET /health/deep HTTP/1.1"):
            self.assertTrue(self._kept(line(request, 200)), request)

    def test_non_GET_health_calls_are_kept(self):
        self.assertTrue(self._kept(line("POST /health HTTP/1.1", 200)))

    def test_a_record_that_cannot_render_is_kept_not_dropped(self):
        # Filtering must never be the thing that loses a line.
        rec = logging.LogRecord("werkzeug", logging.INFO, "", 0,
                                "%d items", ("not-an-int",), None)
        self.assertTrue(bool(self.f.filter(rec)))

    def test_the_filter_is_attached_to_the_werkzeug_logger_on_import(self):
        # Attached at import so it applies however the daemon is launched.
        self.assertTrue(any(isinstance(f, QuietHealthProbes)
                            for f in logging.getLogger("werkzeug").filters))


if __name__ == "__main__":
    unittest.main()
