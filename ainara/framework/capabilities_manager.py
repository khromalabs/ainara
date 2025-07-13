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

import asyncio
import atexit
import importlib
import inspect
import logging
# import pprint
# import sys
import re
from pathlib import Path
from typing import (Annotated, Any, Dict, Optional, get_args, get_origin,
                    get_type_hints)

from flask import jsonify, request

# Import the new manager and related types
from ainara.framework.mcp.client_manager import MCPClientManager
from ainara.framework.mcp.tool import MCPTool

logger = logging.getLogger(__name__)  # Use module-level logger


class CapabilitiesManager:
    # Modified __init__ to accept config and initialize MCP manager
    def __init__(self, flask_app, config, internet_available: bool):
        self.app = flask_app
        self.config = config
        self.internet_available = internet_available
        self.capabilities: Dict[str, Dict[str, Any]] = (
            {}
        )  # Unified capabilities store
        self.mcp_client_manager = None

        # Initialize MCP Client Manager (if available and configured)
        if self.internet_available:
            # Expect mcp_clients to be a dictionary directly
            mcp_clients_config = self.config.get("mcp_clients", None)
            if mcp_clients_config and isinstance(mcp_clients_config, dict) and len(mcp_clients_config) > 0:
                logger.info(
                    "MCP SDK available, internet connected, and 'mcp_clients' (dictionary) configured. "
                    f"Found {len(mcp_clients_config)} client(s). Initializing MCP Client Manager..."
                )
                try:
                    # Pass the dictionary directly to MCPClientManager
                    self.mcp_client_manager = MCPClientManager(mcp_clients_config)
                    # Register shutdown hook for MCP cleanup
                    atexit.register(self.shutdown_mcp)
                    logger.info("Registered MCP shutdown hook.")
                except Exception as e:
                    logger.error(f"Failed to initialize MCPClientManager: {e}", exc_info=True)
                    self.mcp_client_manager = None  # Ensure it's None on failure
            else:
                logger.info(
                    "MCP SDK available and internet connected, but 'mcp_clients' section in config is missing, empty, or not a dictionary. Skipping MCP initialization."
                )
        elif not self.internet_available:
            logger.warning(
                "MCP SDK is available, but no internet connection detected at startup. Skipping MCP Client Manager initialization."
            )
        else:
            logger.warning(
                "MCP SDK not found. Skipping MCP initialization. Install with"
                " 'pip install mcp-sdk'"
            )

        # Load all capabilities
        self.load_capabilities()

        # Register API endpoints for capabilities
        self.register_capability_endpoints()

    def load_capabilities(self):
        """Load native skills and discover MCP tools, populating self.capabilities."""
        logger.info("Loading capabilities...")
        self.capabilities = {}  # Clear existing capabilities

        # 1. Load native skills
        self._load_native_skills()

        # 2. Discover MCP tools
        self._discover_mcp_tools()

        logger.info(
            f"Loaded {len(self.capabilities)} capabilities in total."
            f" ({len([c for c in self.capabilities.values() if c['type'] == 'skill'])} native"
            " skills,"
            f" {len([c for c in self.capabilities.values() if c['type'] == 'mcp'])} MCP"
            " tools)"
        )

    def _load_native_skills(self):
        """Load native skills and add them to the capabilities dictionary."""
        skills_dir = Path(__file__).parent.parent / "orakle" / "skills"
        logger.debug(f"Scanning for native skills in: {skills_dir}")
        loaded_count = 0

        for skill_file in skills_dir.rglob("*.py"):

            # Skip files in nested directories (assuming skills are category/skill.py)
            if skill_file.parent.parent != skills_dir:
                # Allow one level deeper for potential organization like skills/category/backends/file.py
                # Adjust this condition if your structure is different
                if skill_file.parent.parent.parent != skills_dir:
                    continue
            # Skip __init__ files and base files
            if skill_file.stem.startswith("__") or skill_file.stem == "base":
                continue

            try:
                # Get relative path from skills directory
                rel_path = skill_file.relative_to(skills_dir)
                # Convert path to module path
                module_path = ".".join(rel_path.with_suffix("").parts)

                # Construct class name (e.g., system/finder -> SystemFinder)
                # Handle potential subdirectories in class name if needed,
                # assuming CategoryFilename structure for now.
                parts = rel_path.with_suffix("").parts
                if len(parts) == 2:
                    dir_name, file_name = parts
                    # Simple title case conversion
                    class_name = dir_name.capitalize() + file_name.capitalize()
                    # Handle potential variations like 'llm' -> 'LLM' if needed manually
                    class_name = class_name.replace(
                        "Llm", "LLM"
                    )  # Example specific fix
                else:
                    # Fallback or error for unexpected structure
                    logger.warning(
                        "Skipping skill file with unexpected path structure:"
                        f" {skill_file}"
                    )
                    continue

                # Import the module and get the skill class
                full_module_path = f"ainara.orakle.skills.{module_path}"
                logger.debug(f"Importing module: {full_module_path}")
                module = importlib.import_module(full_module_path)
                if hasattr(module, class_name):
                    skill_class = getattr(module, class_name)

                    if inspect.isclass(skill_class):
                        try:
                            instance = skill_class()
                            snake_name = self.camel_to_snake(class_name)
                            # Get embeddings_boost_factor from the skill instance, default to 1.0
                            embeddings_boost_factor = 1.0
                            if hasattr(instance, "embeddings_boost_factor"):
                                embeddings_boost_factor = float(getattr(instance, "embeddings_boost_factor"))

                            capability_info = {
                                "instance": instance,
                                "type": "skill",
                                "origin": "local",
                                "description": (
                                    getattr(instance.__class__, "__doc__", "")
                                    or ""
                                ),
                                "matcher_info": getattr(
                                    instance, "matcher_info", ""
                                ),
                                "hidden": getattr(
                                    instance, "hiddenCapability", False
                                ),
                                "embeddings_boost_factor": embeddings_boost_factor,  # Store the boost factor
                                "run_info": self._get_method_details(
                                    instance, "run", snake_name
                                ),
                            }
                            self.capabilities[snake_name] = capability_info
                            loaded_count += 1
                            logger.info(
                                f"Loaded native skill: {class_name} as"
                                f" {snake_name} with embeddings_boost_factor: {embeddings_boost_factor}"
                            )
                        except Exception as inst_e:
                            logger.error(
                                "Failed to instantiate skill"
                                f" {class_name} from {skill_file}: {inst_e}",
                                exc_info=True,
                            )
                    else:
                        logger.warning(
                            f"Found {class_name} in {full_module_path}, but"
                            " it's not a class."
                        )
                else:
                    logger.warning(
                        f"Class {class_name} not found in module"
                        f" {full_module_path}"
                    )

            except (ImportError, AttributeError, TypeError) as e:
                logger.error(
                    f"Failed to load native skill from {skill_file}: {str(e)}",
                    exc_info=True,
                )
            except (
                Exception
            ) as e:  # Catch broader exceptions during import/instantiation
                logger.error(
                    f"Unexpected error loading native skill from {skill_file}:"
                    f" {str(e)}",
                    exc_info=True,
                )
        logger.info(f"Loaded {loaded_count} native skills.")

    def _discover_mcp_tools(self):
        """Discover MCP tools and add them to the capabilities dictionary."""
        if not self.mcp_client_manager:
            logger.info(
                "MCP Client Manager not available, skipping MCP tool"
                " discovery."
            )
            return

        logger.info("Discovering MCP tools...")
        discovered_count = 0
        try:
            # This blocks until discovery is done (or times out)
            mcp_tools = self.mcp_client_manager.connect_and_discover()
            for tool in mcp_tools:
                capability_info = {
                    "instance": tool,
                    "type": "mcp",
                    "origin": "remote",
                    "description": tool.description,
                    "server": tool.server_name,
                    "hidden": (
                        False
                    ),  # Assuming MCP tools are not hidden by default
                    "run_info": self._get_mcp_tool_details(tool),
                }
                self.capabilities[tool.prefixed_name] = capability_info
                discovered_count += 1
                logger.info(
                    f"Discovered MCP tool: {tool.prefixed_name} from"
                    f" {tool.server_name}"
                )
        except Exception as e:
            logger.error(
                f"Failed during MCP tool discovery: {e}", exc_info=True
            )

        logger.info(f"Discovered {discovered_count} MCP tools.")

    def _get_method_details(
        self, instance: Any, method_name: str, capability_name: str
    ) -> Dict[str, Any]:
        """Inspect a method (like 'run') and return its details."""
        method = getattr(instance, method_name, None)
        details = {
            "description": f"Executes the '{capability_name}' capability.",
            "parameters": {},
            "return_type": "unknown",
            "error": None,
        }

        if not (method and callable(method)):
            details["error"] = f"No callable '{method_name}' method found."
            return details

        details["description"] = method.__doc__ or details["description"]

        try:
            sig = inspect.signature(method)
            type_hints = get_type_hints(method, include_extras=True)

            if "return" in type_hints:
                details["return_type"] = str(type_hints["return"])

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue

                param_type_hint = type_hints.get(param_name, Any)
                param_desc = f"Parameter '{param_name}'"
                origin = get_origin(param_type_hint)
                args = get_args(param_type_hint)
                actual_type = param_type_hint

                if origin is Annotated and len(args) >= 2:
                    actual_type = args[0]
                    if isinstance(args[1], str):
                        param_desc = args[1]
                    else:
                        logger.warning(
                            f"Annotated metadata for '{param_name}' in"
                            f" capability '{capability_name}' is not a string."
                        )

                details["parameters"][param_name] = {
                    "type": str(actual_type),
                    "default": (
                        "None"
                        if param.default is param.empty
                        else repr(param.default)
                    ),
                    "required": param.default is param.empty,
                    "description": param_desc,
                }
        except Exception as e:
            logger.error(
                f"Error inspecting '{method_name}' method for capability"
                f" '{capability_name}': {e}",
                exc_info=True,
            )
            details["error"] = f"Failed to inspect method: {e}"

        return details

    def _get_mcp_tool_details(self, tool: MCPTool) -> Dict[str, Any]:
        """Format MCP tool details similar to native skill run_info."""
        details = {
            "description": (
                f"Executes the MCP tool '{tool.name}' on server"
                f" '{tool.server_name}'."
            ),
            "parameters": {},
            "return_type": (
                "any"
            ),  # MCP doesn't define return type in discovery
            "error": None,
        }
        try:
            if "properties" in tool.input_schema:
                required_params = tool.input_schema.get("required", [])
                for param_name, param_schema in tool.input_schema[
                    "properties"
                ].items():
                    details["parameters"][param_name] = {
                        "type": param_schema.get("type", "any"),
                        "default": "None",  # Not specified in MCP schema
                        "required": param_name in required_params,
                        "description": param_schema.get(
                            "description", "No description provided."
                        ),
                    }
        except Exception as e:
            logger.error(
                "Error parsing input schema for MCP tool"
                f" '{tool.prefixed_name}': {e}",
                exc_info=True,
            )
            details["error"] = f"Failed to parse input schema: {e}"
        return details

    def reload_capabilities(self):
        """Reload all capabilities (native skills and MCP tools)."""
        logger.info("Reloading all capabilities...")
        # Simply re-run the loading process
        self.load_capabilities()
        # Note: Endpoint re-registration might be needed if Flask doesn't handle
        # updates to route handlers gracefully, but typically it does for changes
        # within the handler logic itself. If routes were dynamically added/removed,
        # more complex handling would be required here.
        logger.info("Capabilities reload complete.")

    def get_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all available capabilities (skills and tools)."""
        output_capabilities = {}
        for name, cap_data in self.capabilities.items():
            if cap_data.get("hidden", False):
                continue

            # Prepare output structure, excluding the instance itself
            info = {
                "type": cap_data["type"],
                "origin": cap_data["origin"],
                "description": cap_data["description"],
                "run_info": cap_data["run_info"],
            }
            # Add type-specific fields
            if cap_data["type"] == "skill":
                info["matcher_info"] = cap_data.get("matcher_info", "")
                # Expose embeddings_boost_factor if it's not the default 1.0
                embeddings_boost_factor = cap_data.get("embeddings_boost_factor", 1.0)
                if embeddings_boost_factor != 1.0:
                    info["embeddings_boost_factor"] = embeddings_boost_factor
            elif cap_data["type"] == "mcp":
                info["server"] = cap_data.get("server", "unknown")

            output_capabilities[name] = info

        return output_capabilities

    def get_all_capabilities_description(self) -> str:
        """Generate a combined description of all capabilities for an LLM."""
        description = "You have access to the following capabilities:\n"
        native_skills_desc = "\n=== Native Skills ===\n"
        mcp_tools_desc = "\n=== MCP Tools ===\n"
        native_found = False
        mcp_found = False

        for name, cap_data in self.capabilities.items():
            if cap_data.get("hidden", False):
                continue

            cap_type = cap_data["type"]
            instance = cap_data["instance"]
            run_info = cap_data.get("run_info", {})
            params = run_info.get("parameters", {})

            current_desc = ""
            if cap_type == "skill":
                native_found = True
                current_desc += f"Skill: {name}\n"
                current_desc += f"Description: {cap_data['description']}\n"
                if params:
                    current_desc += "Arguments:\n"
                    for p_name, p_info in params.items():
                        current_desc += f"- {p_name} (type: {p_info['type']})"
                        if p_info["required"]:
                            current_desc += " (required)"
                        current_desc += f": {p_info['description']}\n"
                native_skills_desc += current_desc + "---\n"
            elif cap_type == "mcp":
                mcp_found = True
                # Use the MCPTool's dedicated formatter if available and suitable
                if hasattr(instance, "format_for_llm"):
                    mcp_tools_desc += instance.format_for_llm() + "---\n"
                else:
                    # Fallback formatting
                    current_desc += f"Tool: {name}\n"
                    current_desc += f"Description: {cap_data['description']}\n"
                    current_desc += f"Server: {cap_data['server']}\n"
                    if params:
                        current_desc += "Arguments:\n"
                        for p_name, p_info in params.items():
                            current_desc += (
                                f"- {p_name} (type: {p_info['type']})"
                            )
                            if p_info["required"]:
                                current_desc += " (required)"
                            current_desc += f": {p_info['description']}\n"
                    mcp_tools_desc += current_desc + "---\n"

        if not native_found:
            native_skills_desc += "(No native skills available)\n"
        if not mcp_found:
            mcp_tools_desc += "(No MCP tools available or connected)\n"

        return description + native_skills_desc + mcp_tools_desc

    def get_capability(self, name: str) -> Optional[Any]:
        """Get the instance (skill object or MCPTool) of a capability by name."""
        capability_data = self.capabilities.get(name)
        if capability_data:
            return capability_data.get("instance")
        return None

    def execute_capability(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a capability (native skill or MCP tool) by its name."""
        capability_data = self.capabilities.get(name)

        if capability_data is None:
            raise ValueError(f"Capability '{name}' not found.")

        instance = capability_data["instance"]
        cap_type = capability_data["type"]

        if cap_type == "mcp":
            if not self.mcp_client_manager:
                raise RuntimeError(
                    "MCP Client Manager not available for execution."
                )
            logger.info(f"Executing MCP tool: {name} with args: {arguments}")
            try:
                # MCPClientManager.execute_tool expects the prefixed name
                return self.mcp_client_manager.execute_tool(name, arguments)
            except Exception as e:
                logger.error(
                    f"Error executing MCP tool '{name}': {e}", exc_info=True
                )
                raise RuntimeError(
                    f"Failed to execute MCP tool '{name}': {e}"
                ) from e

        elif cap_type == "skill":
            run_method = getattr(instance, "run", None)
            if not (run_method and callable(run_method)):
                raise TypeError(
                    f"Native skill '{name}' has no callable 'run' method."
                )

            logger.info(
                f"Executing native skill: {name} with args: {arguments}"
            )
            try:
                if inspect.iscoroutinefunction(run_method):
                    # Handle async execution
                    loop = None
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:  # No running loop
                        pass

                    if loop and loop.is_running():
                        # If called within an existing running loop (e.g. from async code)
                        # We might need special handling depending on context,
                        # but often just awaiting works if the caller is async.
                        # For simplicity here, assume we need run_coroutine_threadsafe
                        # if called from Flask (sync context) targeting an async skill.
                        # Let's check if MCP loop exists first.
                        if (
                            self.mcp_client_manager
                            and self.mcp_client_manager._loop
                        ):
                            logger.debug(
                                f"Executing async native skill '{name}' using"
                                " MCP event loop."
                            )
                            future = asyncio.run_coroutine_threadsafe(
                                run_method(**arguments),
                                self.mcp_client_manager._loop,
                            )
                            # Consider adding a timeout from config
                            return future.result(
                                timeout=self.config.get(
                                    "framework.async_skill_timeout", 120
                                )
                            )
                        else:
                            # If no MCP loop, run in a new loop (less ideal but works)
                            logger.warning(
                                f"Executing async native skill '{name}' in a"
                                " temporary event loop."
                            )
                            # This blocks the Flask thread until the async skill completes.
                            return asyncio.run(run_method(**arguments))
                    else:
                        # No running loop, likely called from sync context without MCP loop
                        logger.warning(
                            f"Executing async native skill '{name}' in a new"
                            " event loop."
                        )
                        return asyncio.run(run_method(**arguments))
                else:
                    # Synchronous execution
                    return run_method(**arguments)
            except Exception as e:
                logger.error(
                    f"Error executing native skill '{name}': {e}",
                    exc_info=True,
                )
                raise RuntimeError(
                    f"Failed to execute native skill '{name}': {e}"
                ) from e
        else:
            # Should not happen due to initial check
            raise TypeError(
                f"Unknown capability type '{cap_type}' for '{name}'."
            )

    def register_capability_endpoints(self):
        """Register Flask endpoints for listing and executing capabilities."""
        logger.info("Registering capability API endpoints...")

        # 1. Endpoint to list all available capabilities
        self.register_list_capabilities_endpoint()

        # 2. Endpoint to execute a specific capability
        self.register_execute_capability_endpoint()

    def register_list_capabilities_endpoint(self):
        """Register the /capabilities endpoint to list all capabilities."""
        endpoint_name = "list_capabilities"
        route_path = "/capabilities"

        @self.app.route(route_path, methods=["GET"], endpoint=endpoint_name)
        def get_capabilities_list():
            try:
                return jsonify(self.get_capabilities())
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

    def register_execute_capability_endpoint(self):
        """Register the /run/{capability_name} endpoint."""
        # endpoint_name_prefix = "execute_capability_"
        route_path_base = "/run"

        # We need a single route that handles any capability name
        @self.app.route(
            f"{route_path_base}/<capability_name>", methods=["POST"]
        )
        def handle_execute_capability(capability_name):
            logger.debug(
                f"Received execution request for capability: {capability_name}"
            )

            if not request.is_json:
                # Allow empty body for simple POST triggers if needed, but usually expect args
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
                # Use the unified execute_capability method
                result = self.execute_capability(capability_name, data)

                # Handle different result types consistently
                if (
                    isinstance(result, (dict, list, str, int, float, bool))
                    or result is None
                ):
                    # Directly jsonify common serializable types
                    return jsonify({"result": result})
                else:
                    # Attempt to convert other types to string
                    logger.warning(
                        f"Result for {capability_name} is of non-standard type"
                        f" {type(result)}. Converting to string."
                    )
                    return jsonify({"result": str(result)})

            except ValueError as e:  # Capability not found
                logger.error(
                    f"Execution error for '{capability_name}': {e}",
                    exc_info=False,
                )  # Log less verbosely for not found
                return jsonify({"error": str(e)}), 404  # Not Found
            except (
                TypeError,
                RuntimeError,
            ) as e:  # Execution errors (bad args, internal skill/tool error)
                logger.error(
                    f"Execution error for '{capability_name}': {e}",
                    exc_info=True,
                )
                # Distinguish between client error (TypeError?) and server error (RuntimeError?)
                status_code = 400 if isinstance(e, TypeError) else 500
                return jsonify({"error": str(e)}), status_code
            except Exception as e:  # Catch any other unexpected errors
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

    def camel_to_snake(self, name):
        # Improved camel_to_snake to handle sequences of capitals (like LLM)
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
        return name.lower()
