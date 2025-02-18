# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

import argparse
from typing import Dict

import json
import time
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from pygame import mixer

from ainara.framework.capabilities_manager import CapabilitiesManager
from ainara.framework.config import ConfigManager
from ainara.framework.logging_setup import logging_manager

config_manager = ConfigManager()
config_manager.load_config()

# Get Orakle servers from config
ORAKLE_SERVERS = config_manager.get(
    "orakle.servers", ["http://127.0.0.1:5000"]
)


def parse_args():
    parser = argparse.ArgumentParser(description="Orakle Server")
    parser.add_argument(
        "--port", type=int, default=5000, help="Port to run the server on"
    )
    parser.add_argument(
        "--log-dir", type=str, help="Directory for log files (optional)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args()


app = Flask(__name__)
CORS(app)


def register_framework_endpoints(app):
    """Register framework-specific endpoints for non-Python clients"""
    # Framework endpoints moved to PyBridge server
    pass


def create_app():
    """Create and configure the Flask application"""
    capabilities_manager = CapabilitiesManager(app)
    # Store reference to capabilities manager
    app.capabilities_manager = capabilities_manager
    return app


if __name__ == "__main__":
    args = parse_args()
    logging_manager.setup(log_dir=args.log_dir, log_level=args.log_level)
    # Get logger after setup
    logger = logging_manager.logger
    logger.info(f"Starting Orakle development server on port {args.port}")

    app = create_app()
    app.run(port=args.port)
