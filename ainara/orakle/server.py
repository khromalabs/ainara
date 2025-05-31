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
import socket
import time
from datetime import datetime

from flask import Flask, jsonify, request
from flask_cors import CORS

from ainara.framework.capabilities_manager import CapabilitiesManager
from ainara.framework.config import config  # Use the global config instance
from ainara.framework.logging_setup import logging_manager
from ainara.framework.mcp_client_manager import \
    MCP_AVAILABLE  # Check MCP availability
from ainara.orakle import __version__


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
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable profiling for the server",
    )
    return parser.parse_args()


app = Flask(__name__)
CORS(app)


# Add at module level
startup_time = datetime.utcnow()


def check_internet_connection(logger_instance, timeout=3):
    """
    Check for internet connectivity by trying to connect to a known host.
    Tries a list of reliable public DNS servers.
    """
    # List of reliable hosts (IP, port) to check.
    # Using common DNS servers on their standard port 53.
    reliable_hosts = [
        ("8.8.8.8", 53),  # Google DNS
        ("1.1.1.1", 53),  # Cloudflare DNS
        ("9.9.9.9", 53),  # Quad9 DNS
    ]

    socket.setdefaulttimeout(timeout)
    for host, port in reliable_hosts:
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            logger_instance.info(f"Internet connection test to {host}:{port} successful.")
            return True  # Connection successful to at least one host
        except socket.error as ex:
            logger_instance.debug(f"Internet connection test to {host}:{port} failed: {ex}")
            continue  # Try the next host

    logger_instance.warning("Internet connection test failed for all reliable hosts.")
    return False


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
        "internet_available": getattr(app, "internet_available", False),
        "services": {
            "capabilities_manager": app.capabilities_manager is not None,
            "config": config is not None,
            "logging": logging_manager is not None,
        },
        "dependencies": {
            "mcp_sdk_available": MCP_AVAILABLE,
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


def create_app(internet_available: bool):
    """Create and configure the Flask application"""
    # Store internet status on the app object for access in routes like /health
    app.internet_available = internet_available

    # Store reference to capabilities manager, passing the global config
    app.capabilities_manager = CapabilitiesManager(app, config, internet_available)

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

    # Add a route to execute a capability (native or MCP)
    @app.route("/run", methods=["POST"])
    def execute_capability_route():
        if not hasattr(app, "capabilities_manager"):
            return (
                jsonify({"error": "CapabilitiesManager not initialized"}),
                500,
            )
        data = request.get_json()
        if not data or "name" not in data or "arguments" not in data:
            return (
                jsonify({"error": "Missing 'name' or 'arguments' in request"}),
                400,
            )

        capability_name = data["name"]
        arguments = data["arguments"]

        try:
            result = app.capabilities_manager.execute_capability(
                capability_name, arguments
            )
            return jsonify({"success": True, "result": result})
        except (ValueError, TypeError, RuntimeError) as e:
            logger.error(
                f"Error executing capability '{capability_name}': {e}",
                exc_info=True,
            )
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error(
                "Unexpected error executing capability"
                f" '{capability_name}': {e}",
                exc_info=True,
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "An unexpected server error occurred",
                    }
                ),
                500,
            )

    return app


if __name__ == "__main__":
    args = parse_args()
    logging_manager.setup(log_level=args.log_level, log_name="orakle.log")
    # Get logger after setup
    logger = logging_manager.logger

    # Perform internet check after logger is configured
    is_online = check_internet_connection(logger)
    logger.info(f"Internet connection available at startup: {is_online}")

    logger.info(f"Starting Orakle development server on port {args.port}")
    logger.info(f"MCP SDK Available: {MCP_AVAILABLE}")

    # Set up profiling if enabled (needs to be before create_app if it profiles app creation)
    if args.profile:
        import cProfile
        import pstats
        import os
        # Use the log directory from logging_manager
        log_dir = logging_manager._log_directory
        profile_output = os.path.join(log_dir, "orakle_profile.prof")
        logger.info(f"Profiling enabled. Output will be saved to {profile_output}")
        profiler = cProfile.Profile()
        profiler.enable()

    app = create_app(internet_available=is_online)

    # Run the app with or without profiling
    try:
        app.run(port=args.port)
    finally:
        # If profiling is enabled, save the profile data
        if args.profile:
            profiler.disable()
            logger.info(f"Saving profiling data to {profile_output}")
            profiler.dump_stats(profile_output)
            # Print some basic stats to the log
            stats = pstats.Stats(profile_output)
            logger.info("Top 10 functions by cumulative time:")
            stats.sort_stats('cumulative').print_stats(10)
