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
import time
from datetime import datetime

from flask import Flask
from flask_cors import CORS

from ainara.framework.capabilities_manager import CapabilitiesManager
from ainara.framework.config import ConfigManager
from ainara.framework.logging_setup import logging_manager
from ainara.orakle import __version__
from ainara.framework.llm import create_llm_backend

config_manager = ConfigManager()
config_manager.load_config()
llm = create_llm_backend(config_manager.get("llm", {}))


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


# Add at module level
startup_time = datetime.utcnow()


@app.route("/health", methods=["GET"])
def health_check():
    """Comprehensive health check endpoint"""
    start_time = time.time()

    # Get memory configuration
    memory_config = config_manager.get("memory", {})
    memory_enabled = memory_config.get("enabled", False)

    status = {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": (datetime.utcnow() - startup_time).total_seconds(),
        "services": {
            "capabilities_manager": app.capabilities_manager is not None,
            "config_manager": config_manager is not None,
            "logging": logging_manager is not None,
        },
        "dependencies": {
            "llm_available": llm and llm.is_available(),
        },
    }

    # Only include storage check if memory is enabled
    if memory_enabled:
        status["dependencies"][
            "storage_available"
        ] = False  # Should implement actual storage check

    # Check if all essential services are available
    all_services_ok = all(status["services"].values())
    all_dependencies_ok = all(status["dependencies"].values())

    if not all_services_ok or not all_dependencies_ok:
        status["status"] = "degraded"
        status["message"] = "Some services or dependencies are unavailable"

    # Add response time measurement
    status["response_time_ms"] = (time.time() - start_time) * 1000

    return status


# def register_framework_endpoints(app):
#     """Register framework-specific endpoints for non-Python clients"""
#     # Framework endpoints moved to PyBridge server
#     pass


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
