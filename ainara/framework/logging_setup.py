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
from logging.handlers import RotatingFileHandler

from ainara.framework.config import config


class LoggingManager:
    """Manages application-wide logging configuration"""

    _instance = None
    _logger = None
    _filters = set()  # Add this to track filters

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggingManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self._logger = None
        self._filters = set()  # Initialize filters set

    def addFilter(self, log_filter):
        """Add filtering criteria

        Args:
            log_filter: str or list of str - Names to filter logging on
        """
        if isinstance(log_filter, (list, tuple)):
            self._filters.update(log_filter)
        else:
            self._filters.add(log_filter)

        # Create a new logger that combines all filters
        if self._logger:
            self._logger = logging.getLogger("|".join(self._filters))
            # Preserve existing handlers and their configuration
            handlers = self._logger.handlers
            level = self._logger.level
            self._logger.handlers = handlers
            self._logger.setLevel(level)

    def setup(
        self,
        log_dir=None,
        log_level="INFO",
        log_filter=None,
        log_name="ainara.log",
    ):
        """Configure logging to console and optionally to rotating file"""

        if log_filter:
            self.addFilter(log_filter)

        # Initialize logger with combined filters
        filter_string = "|".join(self._filters) if self._filters else ""
        self._logger = logging.getLogger(filter_string)
        logger = self._logger
        log_level = getattr(logging, log_level.upper())
        logger.setLevel(log_level)

        # Remove existing handlers
        logger.handlers.clear()

        # Console handler - INFO and above
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_formatter = logging.Formatter("%(levelname)s: %(message)s")
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # Use provided log_dir or get from config
        if log_dir is None:
            log_dir = config.get("logging.directory")

        # File handler setup
        if log_dir:
            log_file = os.path.join(log_dir, log_name)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=config.get("logging.max_size_mb", 1024 * 1024),
                backupCount=config.get("logging.backup_count", 5),
            )
            file_handler.setLevel(log_level)
            file_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)

        return logger

    @property
    def logger(self):
        """Get the configured logger instance"""
        return self._logger


# Create singleton instance
logging_manager = LoggingManager()
logger = logging_manager.logger