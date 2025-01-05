import logging
import os
from logging.handlers import RotatingFileHandler


class LoggingManager:
    """Manages application-wide logging configuration"""
    _instance = None
    _logger = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggingManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._logger is None:
            self._logger = logging.getLogger()
            self._logger.setLevel(logging.INFO)

    def setup(self, log_dir=None, log_level="INFO", log_filter=None):
        """Configure logging to console and optionally to rotating file"""
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

        # File handler if log_dir specified
        if log_dir:
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            log_file = os.path.join(log_dir, "orakle.log")
            file_handler = RotatingFileHandler(
                log_file, maxBytes=1024 * 1024, backupCount=5  # 1MB
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
