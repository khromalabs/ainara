import argparse
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask
from flask_cors import CORS

from ainara.orakle.framework.recipe_manager import RecipeManager


def setup_logging(log_dir=None, log_level="INFO"):
    """Configure logging to console and optionally to rotating file"""
    # logger = logging.getLogger('orakle')
    logger = logging.getLogger()
    log_level = getattr(logging, log_level.upper())
    logger.setLevel(log_level)

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


def parse_args():
    parser = argparse.ArgumentParser(description="Orakle Server")
    parser.add_argument(
        "--port", type=int, default=5000, help="Port to run the server on"
    )
    parser.add_argument(
        "--log-dir", type=str, help="Directory for log files (optional)"
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)"
    )
    return parser.parse_args()


app = Flask(__name__)
CORS(app)

if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_dir, args.log_level)

    logger = logging.getLogger(__name__)
    logger.info(f"Starting Orakle server on port {args.port}")

    recipe_manager = RecipeManager(app)
    app.run(port=args.port)
