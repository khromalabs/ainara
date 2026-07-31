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

import sys
import atexit
import logging
import copy
from typing import Any, Dict, Optional
from pathlib import Path

from flask import jsonify, request

# Import the new manager and related types
from ainara.framework.mcp.client_manager import MCPClientManager
from ainara.framework.connectors.manager import ConnectorManager
from ainara.framework.connectors.router import ConnectorRouter

# Import providers
from .mcp import MCPToolProvider
from .nexus import NexusSkillProvider
from .skills import NativeSkillProvider, UserSkillProvider

logger = logging.getLogger(__name__)  # Use module-level logger


class CapabilitiesManager:
    def __init__(self, flask_app, config, internet_available: bool, startup_time: float = None):
        self.app = flask_app
        self.config = config
        self.internet_available = internet_available
        self.startup_time = startup_time
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        self.mcp_client_manager = None
        # self.connector_manager = None
        self.nexus_provider = None
        self.user_provider = None
        self.providers = []
        self.provider_map: Dict[str, Any] = {}
        resource_base_dir = self._get_resource_base_dir()

        # Initialize Connector Router
        self.router = ConnectorRouter(resource_base_dir / "resources/contracts")
        logger.info("Initialized ConnectorRouter.")

        # Initialize Connector Manager
        try:
            self.connector_manager = ConnectorManager(self.config, self.router)
            logger.info("Initialized ConnectorManager.")
        except Exception as e:
            logger.error(f"Failed to initialize ConnectorManager: {e}", exc_info=True)

        # Initialize MCP Client Manager (if available and configured)
        if self.internet_available:
            mcp_clients_config = self.config.get("mcp_clients", None)
            if (
                mcp_clients_config
                and isinstance(mcp_clients_config, dict)
                and len(mcp_clients_config) > 0
            ):
                logger.info(
                    "MCP SDK available, internet connected, and 'mcp_clients'"
                    " (dictionary) configured. Found"
                    f" {len(mcp_clients_config)} client(s). Initializing MCP"
                    " Client Manager..."
                )
                try:
                    self.mcp_client_manager = MCPClientManager(
                        mcp_clients_config
                    )
                    atexit.register(self.shutdown_mcp)
                    logger.info("Registered MCP shutdown hook.")
                except Exception as e:
                    logger.error(
                        f"Failed to initialize MCPClientManager: {e}",
                        exc_info=True,
                    )
                    self.mcp_client_manager = None
            else:
                logger.info(
                    "MCP SDK available and internet connected, but"
                    " 'mcp_clients' section in config is missing, empty, or"
                    " not a dictionary. Skipping MCP initialization."
                )
        elif not self.internet_available:
            logger.warning(
                "MCP SDK is available, but no internet connection detected at"
                " startup. Skipping MCP Client Manager initialization."
            )
        else:
            logger.warning(
                "MCP SDK not found. Skipping MCP initialization. Install with"
                " 'pip install mcp-sdk'"
            )

        # Initialize providers
        self._initialize_providers()

        # Load all capabilities
        self.load_capabilities()

        # Register API endpoints for capabilities
        self.register_capability_endpoints()

    def _get_resource_base_dir(self) -> Path:
        """Determine the base directory for resources (project root or MEIPASS)."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # Running as a bundled app (PyInstaller)
            return Path(sys._MEIPASS)
        else:
            # Running from source
            # __file__ -> capabilities -> framework -> ainara -> repo_root
            return Path(__file__).parent.parent.parent.parent

    def _initialize_providers(self):
        """Instantiate and register all capability providers."""
        logger.info("Initializing capability providers...")
        # Native Skill Provider is always available
        skill_provider = NativeSkillProvider(
            self.config, self.mcp_client_manager, self.router
        )
        self.providers.append(skill_provider)
        self.provider_map["skill"] = skill_provider
        logger.info("Initialized NativeSkillProvider.")

        # Nexus Skill Provider for bundled applications
        nexus_path = self.config.get("nexus.path", "ainara/nexus")
        try:
            self.nexus_provider = NexusSkillProvider(
                nexus_path, self.config, self.mcp_client_manager
            )
            self.providers.append(self.nexus_provider)
            self.provider_map["nexus"] = self.nexus_provider
            logger.info(
                f"Initialized NexusSkillProvider with path: {nexus_path}"
            )
        except Exception as e:
            logger.error(
                f"Failed to initialize NexusSkillProvider: {e}", exc_info=True
            )
            self.nexus_provider = None

        # MCP Tool Provider is only available if the manager was created
        if self.mcp_client_manager:
            mcp_provider = MCPToolProvider(self.mcp_client_manager)
            self.providers.append(mcp_provider)
            self.provider_map["mcp"] = mcp_provider
            logger.info("Initialized MCPToolProvider.")

        # User Skill Provider
        if self.config.get("user_skills.enabled", False):
            try:
                self.user_provider = UserSkillProvider(
                    self.config, self.mcp_client_manager, self.router, self.startup_time
                )
                self.providers.append(self.user_provider)
                self.provider_map["user_skill"] = self.user_provider
                logger.info("Initialized UserSkillProvider.")
            except Exception as e:
                logger.error(f"Failed to initialize UserSkillProvider: {e}", exc_info=True)
                self.user_provider = None

    def load_capabilities(self):
        """Load all capabilities by delegating to registered providers."""
        logger.info("Loading capabilities from all providers...")
        self.capabilities = {}  # Clear existing capabilities
        self.load_errors = []   # Clear previous errors

        for provider in self.providers:
            try:
                discovered_caps = provider.discover()
                self.capabilities.update(discovered_caps)
                if hasattr(provider, 'load_errors'):
                    self.load_errors.extend(provider.load_errors)
            except Exception as e:
                logger.error(
                    "Failed to discover capabilities from provider"
                    f" {type(provider).__name__}: {e}",
                    exc_info=True,
                )

        num_skills = len(
            [c for c in self.capabilities.values() if c["type"] == "skill"]
        )
        num_mcp = len(
            [c for c in self.capabilities.values() if c["type"] == "mcp"]
        )
        num_nexus = len(
            [c for c in self.capabilities.values() if c["type"] == "nexus"]
        )

        logger.info(
            f"Loaded {len(self.capabilities)} capabilities in total."
            f" ({num_skills} native skills, {num_mcp} MCP tools,"
            f" {num_nexus} Nexus skills)"
        )

    def reload_capabilities(self):
        """Reload all capabilities (native skills and MCP tools)."""
        logger.info("Reloading all capabilities...")
        self.load_capabilities()
        logger.info("Capabilities reload complete.")

    def get_capabilities(self, view_mode: str = "llm") -> Dict[str, Dict[str, Any]]:
        """
        Get information about all available capabilities.

        Args:
            view_mode: "llm" (default) for lean output (no schemas, no hidden params),
                       or "full" for complete details (schemas, hidden params, schedules).
        """
        output_capabilities = {}
        for name, cap_data in self.capabilities.items():
            if cap_data.get("hidden", False):
                continue

            # Create a deep copy of run_info to safely modify parameters for the view
            run_info = copy.deepcopy(cap_data["run_info"])

            # Prepare output structure
            info = {
                "type": cap_data["type"],
                "origin": cap_data["origin"],
                "description": cap_data["description"],
                "run_info": run_info,
            }

            # Filter parameters based on view_mode
            params = run_info.get("parameters", {})
            params_to_remove = []

            for param_name, param_data in params.items():
                if view_mode == "llm":
                    # 1. Remove hidden parameters entirely
                    if param_data.get("hidden", False):
                        params_to_remove.append(param_name)
                        continue

                    # 2. Remove verbose schema
                    if "schema" in param_data:
                        del param_data["schema"]

                    # 3. Remove redundant 'hidden' flag (it's False if we are here)
                    if "hidden" in param_data:
                        del param_data["hidden"]

            # Apply removals
            for p in params_to_remove:
                del params[p]

            # Add type-specific fields
            if cap_data["type"] in ("skill", "user_skill"):
                info["matcher_info"] = cap_data.get("matcher_info", "")
                embeddings_boost_factor = cap_data.get(
                    "embeddings_boost_factor", 1.0
                )
                if embeddings_boost_factor != 1.0:
                    info["embeddings_boost_factor"] = embeddings_boost_factor
                if "ui" in cap_data:
                    info["ui"] = cap_data["ui"]
            elif cap_data["type"] == "mcp":
                info["server"] = cap_data.get("server", "unknown")
            elif cap_data["type"] == "nexus":
                info["vendor"] = cap_data.get("vendor")
                info["bundle"] = cap_data.get("bundle")
                if "ui" in cap_data:
                    info["ui"] = cap_data["ui"]

            # Expose default schedule only in 'full' mode
            if view_mode == "full":
                instance = cap_data.get("instance")
                if instance and hasattr(instance, "default_schedule"):
                    info["default_schedule"] = instance.default_schedule

            output_capabilities[name] = info

        return output_capabilities

    def get_all_capabilities_description(self) -> str:
        """Generate a combined description of all capabilities for an LLM."""
        description = "You have access to the following capabilities:\n"
        sections = {
            "skill": "\n=== Native Skills ===\n",
            "user_skill": "\n=== User Skills ===\n",
            "nexus": "\n=== Nexus Skills ===\n",
            "mcp": "\n=== MCP Tools ===\n",
        }
        content = {"skill": "", "user_skill": "", "nexus": "", "mcp": ""}
        found = {"skill": False, "user_skill": False, "nexus": False, "mcp": False}

        for name, cap_data in self.capabilities.items():
            if cap_data.get("hidden", False):
                continue

            cap_type = cap_data["type"]
            if cap_type in self.provider_map:
                provider = self.provider_map[cap_type]
                content[cap_type] += provider.format_for_llm(cap_data)
                found[cap_type] = True

        if not found["skill"]:
            content["skill"] = "(No native skills available)\n"
        if not found["user_skill"]:
            content["user_skill"] = "(No user skills available)\n"
        if not found["nexus"]:
            content["nexus"] = "(No Nexus skills available)\n"
        if not found["mcp"]:
            content["mcp"] = "(No MCP tools available or connected)\n"

        return (
            description
            + sections["skill"]
            + content["skill"]
            + sections["user_skill"]
            + content["user_skill"]
            + sections["nexus"]
            + content["nexus"]
            + sections["mcp"]
            + content["mcp"]
        )

    def get_capability(self, name: str) -> Optional[Any]:
        """Get the instance (skill object or MCPTool) of a capability by name."""
        capability_data = self.capabilities.get(name)
        if capability_data:
            return capability_data.get("instance")
        return None

    def execute_capability(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a capability by delegating to the appropriate provider."""
        capability_data = self.capabilities.get(name)

        if capability_data is None:
            raise ValueError(f"Capability '{name}' not found.")

        cap_type = capability_data["type"]
        provider = self.provider_map.get(cap_type)

        if provider is None:
            raise TypeError(
                f"No provider found for capability type '{cap_type}'."
            )

        return provider.execute(name, arguments)

    def register_capability_endpoints(self):
        """Register Flask endpoints for listing and executing capabilities."""
        logger.info("Registering capability API endpoints...")
        self.register_list_capabilities_endpoint()
        self.register_execute_capability_endpoint()
        self.register_nexus_component_endpoint()
        self.register_user_component_endpoint()

    def register_list_capabilities_endpoint(self):
        """Register the /capabilities endpoint to list all capabilities."""
        endpoint_name = "list_capabilities"
        route_path = "/capabilities"

        @self.app.route(route_path, methods=["GET"], endpoint=endpoint_name)
        def get_capabilities_list():
            try:
                # Get view mode from query param, default to 'llm'
                view_mode = request.args.get("view", "llm")
                return jsonify(self.get_capabilities(view_mode=view_mode))
            except Exception as e:
                logger.error(
                    "Error generating capabilities list for endpoint"
                    f" {route_path}: {e}",
                    exc_info=True,
                )
                return (
                    jsonify({"error": "Failed to retrieve capabilities list"}),
                    500,
                )

        logger.info(
            f"Registered capability list endpoint: GET {route_path} ->"
            f" {endpoint_name}"
        )

    def register_nexus_component_endpoint(self):
        """Register the /nexus/<path:component_path> endpoint to serve component files."""
        if not self.nexus_provider:
            logger.debug(
                "Nexus provider not available, skipping component endpoint"
                " registration."
            )
            return

        route_path_base = "/nexus"

        @self.app.route(
            f"{route_path_base}/<path:component_path>", methods=["GET"]
        )
        def serve_nexus_component(component_path):
            """Serve a file from a Nexus component's UI directory."""
            try:
                # Delegate serving to the provider, which handles security and path resolution
                return self.nexus_provider.serve_component(component_path)
            except FileNotFoundError as e:
                logger.warning(
                    "Nexus component file not found for path"
                    f" '{component_path}': {e}"
                )
                return jsonify({"error": "Component file not found"}), 404
            except PermissionError as e:
                logger.error(
                    "Security violation: access denied for Nexus component"
                    f" path '{component_path}': {e}"
                )
                return jsonify({"error": "Access denied"}), 403
            except Exception as e:
                logger.error(
                    "Error serving nexus component for path"
                    f" '{component_path}': {e}",
                    exc_info=True,
                )
                return jsonify({"error": "Internal server error"}), 500

        logger.info(
            "Registered Nexus component endpoint: GET"
            f" {route_path_base}/<path:component_path>"
        )

    def register_user_component_endpoint(self):
        """Register the /user_skills/components/<path:component_path> endpoint."""
        if not self.user_provider:
            logger.debug("User provider not available, skipping component endpoint registration.")
            return

        route_path_base = "/user_skills/components"

        @self.app.route(f"{route_path_base}/<path:component_path>", methods=["GET"])
        def serve_user_component(component_path):
            try:
                return self.user_provider.serve_component(component_path)
            except FileNotFoundError as e:
                logger.warning(f"User component file not found for path '{component_path}': {e}")
                return jsonify({"error": "Component file not found"}), 404
            except PermissionError as e:
                logger.error(f"Security violation: access denied for user component path '{component_path}': {e}")
                return jsonify({"error": "Access denied"}), 403
            except Exception as e:
                logger.error(f"Error serving user component for path '{component_path}': {e}", exc_info=True)
                return jsonify({"error": "Internal server error"}), 500

        logger.info(f"Registered User component endpoint: GET {route_path_base}/<path:component_path>")

    def register_execute_capability_endpoint(self):
        """Register the /run/{capability_name} endpoint."""
        route_path_base = "/run"

        @self.app.route(
            f"{route_path_base}/<capability_name>", methods=["POST"]
        )
        def handle_execute_capability(capability_name):
            logger.debug(
                f"Received execution request for capability: {capability_name}"
            )

            if not request.is_json:
                if not request.data:
                    logger.warning(
                        f"Request for {capability_name} has no JSON data."
                        " Assuming empty args."
                    )
                    data = {}
                else:
                    logger.error(f"Request for {capability_name} is not JSON.")
                    return (
                        jsonify({"error": "Request must contain JSON data"}),
                        400,
                    )
            else:
                try:
                    data = request.get_json()
                    if not isinstance(data, dict):
                        logger.error(
                            f"Request data for {capability_name} is not a JSON"
                            " object."
                        )
                        return (
                            jsonify(
                                {"error": "Request data must be a JSON object"}
                            ),
                            400,
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to parse JSON for {capability_name}: {e}"
                    )
                    return jsonify({"error": f"Invalid JSON data: {e}"}), 400

            try:
                result = self.execute_capability(capability_name, data)

                if (
                    isinstance(result, (dict, list, str, int, float, bool))
                    or result is None
                ):
                    return jsonify({"result": result})
                else:
                    logger.warning(
                        f"Result for {capability_name} is of non-standard type"
                        f" {type(result)}. Converting to string."
                    )
                    return jsonify({"result": str(result)})

            except ValueError as e:
                logger.error(
                    f"Execution error for '{capability_name}': {e}",
                    exc_info=False,
                )
                return jsonify({"error": str(e)}), 404
            except (
                TypeError,
                RuntimeError,
            ) as e:
                logger.error(
                    f"Execution error for '{capability_name}': {e}",
                    exc_info=True,
                )
                status_code = 400 if isinstance(e, TypeError) else 500
                return jsonify({"error": str(e)}), status_code
            except Exception as e:
                logger.error(
                    f"Unexpected error executing '{capability_name}': {e}",
                    exc_info=True,
                )
                return (
                    jsonify({"error": "An internal server error occurred"}),
                    500,
                )

        logger.info(
            "Registered capability execution endpoint: POST"
            f" {route_path_base}/<capability_name>"
        )

    def shutdown_mcp(self):
        """Shutdown the MCP client manager if it exists."""
        if self.mcp_client_manager:
            logger.info(
                "Shutting down MCP Client Manager via CapabilitiesManager."
            )
            self.mcp_client_manager.shutdown()
        else:
            logger.debug(
                "MCP Client Manager was not initialized, nothing to shut down."
            )
