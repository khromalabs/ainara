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

import logging
import os
import signal
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitors health check pings and shuts down the server if they stop.
    This acts as a watchdog to prevent orphaned server processes if the main
    application crashes.
    """

    def __init__(self, timeout: int = 20, shutdown_callback: Callable = None):
        """
        Initialize the HealthMonitor.
        Args:
            timeout: Time in seconds to wait for a health check before shutting down.
            shutdown_callback: The function to call to shut down the server.
                               If None, it will use a default os._exit(1).
        """
        self.started = False
        self.timeout = timeout
        self.last_health_check = time.time()
        self.health_check_timestamps = []
        self.activation_threshold = 6  # seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._monitor, daemon=True)

        if shutdown_callback:
            self.shutdown = shutdown_callback
        else:
            self.shutdown = self._default_shutdown

    def _default_shutdown(self):
        """Default shutdown mechanism."""
        logger.critical(
            "Default shutdown called. Forcing exit. This is not a clean shutdown."
        )
        os._exit(1)  # Force exit

    def start(self):
        """Start the monitoring thread."""
        if not self._thread.is_alive():
            self.last_health_check = time.time()  # Reset on start
            self._thread.start()
            logger.info(
                f"Health monitor started with a {self.timeout}s timeout."
            )
            self.started = True

    def stop(self):
        """Stop the monitoring thread."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Health monitor stopped.")

    def record_health_check(self, status: str = "ok"):
        """Record that a health check has been received."""
        if status != "ok":
            # Reset timestamp tracking if we get an unhealthy check,
            # so we require two *consecutive* healthy checks.
            self.health_check_timestamps = []
            return

        current_time = time.time()
        self.last_health_check = current_time
        logger.debug("Health check recorded.")

        if not self.started:
            self.health_check_timestamps.append(current_time)
            # Keep only the last 2 timestamps
            if len(self.health_check_timestamps) > 2:
                self.health_check_timestamps.pop(0)

            if len(self.health_check_timestamps) == 2:
                time_diff = (
                    self.health_check_timestamps[1]
                    - self.health_check_timestamps[0]
                )
                if time_diff < self.activation_threshold:
                    self.start()
                else:
                    # If the gap is too large, we reset and wait for a new pair of close pings.
                    # The current ping becomes the first of a potential new pair.
                    self.health_check_timestamps.pop(0)

    def _monitor(self):
        """The monitoring loop that runs in a separate thread."""
        logger.info("Health monitor thread running.")
        while not self._stop_event.is_set():
            time_since_last_check = time.time() - self.last_health_check
            if time_since_last_check > self.timeout:
                logger.critical(
                    f"No health check received for {time_since_last_check:.2f} "
                    f"seconds (timeout is {self.timeout}s). Shutting down."
                )
                self.shutdown()
                break  # Exit the loop after calling shutdown
            # Sleep for a short interval before checking again
            self._stop_event.wait(1)
        logger.info("Health monitor thread finished.")
