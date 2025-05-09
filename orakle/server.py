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


import argparse
import time
from datetime import datetime

from flask import Flask, jsonify, request
from flask_cors import CORS

from ainara.framework.capabilities_manager import CapabilitiesManager
from ainara.framework.config import ConfigManager
from ainara.framework.logging_setup import logging_manager
from ainara.orakle import __version__

config = ConfigManager()
config.load_config()


def parse_args():
    parser = argparse.ArgumentParser(description="Orakle Server")
    parser.add_argument(
        "--port", type=int, default=5000, help="Port to run the server on"
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
    memory_config = config.get("memory", {})
    memory_enabled = memory_config.get("enabled", False)

    status = {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": (datetime.utcnow() - startup_time).total_seconds(),
        "services": {
            "capabilities_manager": app.capabilities_manager is not None,
            "config": config is not None,
            "logging": logging_manager is not None,
        },
        "dependencies": {
            "dummy": True
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


def create_app():
    """Create and configure the Flask application"""
    # Store reference to capabilities manager
    app.capabilities_manager = CapabilitiesManager(app)

    @app.route("/config", methods=["PUT"])
    def update_config():
        """Update the configuration"""
        try:
            data = request.get_json()
            if not data:
                return (
                    jsonify({"success": False, "error": "No data provided"}),
                    400,
                )

            # Validate the configuration
            validation_result = config.validate_config(data)
            if not validation_result["valid"]:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Invalid configuration",
                            "errors": validation_result["errors"],
                        }
                    ),
                    400,
                )

            # Update the configuration without saving
            config.update_config(new_config=data, save=False)

            # # Reload skills without registering new routes
            # app.capabilities_manager.reload_skills()

            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Error updating configuration: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

    return app


if __name__ == "__main__":
    args = parse_args()
    logging_manager.setup(log_level=args.log_level, log_name="orakle.log")
    # Get logger after setup
    logger = logging_manager.logger
    logger.info(f"Starting Orakle development server on port {args.port}")

    app = create_app()
    app.run(port=args.port)