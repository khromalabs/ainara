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
from typing import (Annotated, Any, Dict, List, Optional, get_args, get_origin,
                    get_type_hints)

from flask import jsonify, request

# Import the new manager and related types
from .mcp_client_manager import MCP_AVAILABLE, MCPClientManager, MCPTool

logger = logging.getLogger(__name__)  # Use module-level logger


class CapabilitiesManager:
    # Modified __init__ to accept config and initialize MCP manager
    def __init__(self, flask_app, config):
        self.app = flask_app
        self.config = config  # Store config
        self.skills = {}  # Your existing skills dictionary for native skills
        self.mcp_tools: List[MCPTool] = []  # Store discovered MCP tools

        # Initialize MCP Client Manager
        self.mcp_client_manager = None
        if MCP_AVAILABLE:
            mcp_config_section = self.config.get("mcp_clients")
            if mcp_config_section:
                logger.info("Initializing MCP Client Manager...")
                self.mcp_client_manager = MCPClientManager(mcp_config_section)
                # Register shutdown hook for MCP cleanup
                atexit.register(self.shutdown_mcp)
                logger.info("Registered MCP shutdown hook.")
            else:
                logger.info(
                    "No 'mcp_clients' section found in config. Skipping MCP"
                    " initialization."
                )
        else:
            logger.warning(
                "MCP SDK not found. Skipping MCP initialization. Install with"
                " 'pip install mcp-sdk'"
            )

        # Load native skills and discover MCP tools
        self.load_capabilities()

        # Register endpoints after loading/discovering capabilities
        self.register_skills_endpoints()  # For native skills
        self.register_mcp_tool_endpoints()  # For MCP tools (optional, direct access)
        self.register_capabilities_endpoint()  # Combined capabilities endpoint

    def load_capabilities(self):
        """Load native skills and discover MCP tools."""
        # 1. Load native skills (using your existing logic)
        self._load_native_skills()
        logger.info(f"Loaded {len(self.skills)} native skills.")

        # 2. Discover MCP tools if manager is available
        if self.mcp_client_manager:
            logger.info("Discovering MCP tools...")
            try:
                # This blocks until discovery is done (or times out)
                self.mcp_tools = self.mcp_client_manager.connect_and_discover()
                logger.info(f"Discovered {len(self.mcp_tools)} MCP tools.")
            except Exception as e:
                logger.error(
                    f"Failed during MCP tool discovery: {e}", exc_info=True
                )
                self.mcp_tools = []  # Ensure it's an empty list on failure

    def _load_native_skills(self):
        """Load all available native skills from the skills directory"""
        # This is your existing load_skills logic, renamed for clarity
        skills_dir = Path(__file__).parent.parent / "orakle" / "skills"
        logger.debug(f"Loading native skills from: {skills_dir}")
        self.skills = {}  # Clear existing native skills before loading

        # Get all Python files in the skills directory and subdirectories
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

                    # Instantiate the skill and add it to the skills dictionary
                    # Ensure it's actually a class and callable
                    if inspect.isclass(skill_class):
                        self.skills[class_name] = skill_class()
                        logger.info(f"Loaded native skill: {class_name}")
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

    def reload_skills(self):
        """Reload native skills and re-discover MCP tools."""
        logger.info(
            "Reloading all capabilities (native skills and MCP tools)..."
        )
        # 1. Reload native skills
        self._load_native_skills()
        logger.info(f"Reloaded {len(self.skills)} native skills.")
        # You might need to re-register native skill endpoints if routes are dynamic

        # 2. Re-discover MCP tools
        if self.mcp_client_manager:
            logger.info("Re-discovering MCP tools...")
            # Shutdown existing connections first
            self.mcp_client_manager.shutdown()
            # Re-initialize (optional, depends if config changed) or just reconnect
            # Assuming config hasn't changed fundamentally, just reconnect
            try:
                self.mcp_tools = self.mcp_client_manager.connect_and_discover()
                logger.info(f"Re-discovered {len(self.mcp_tools)} MCP tools.")
            except Exception as e:
                logger.error(
                    f"Failed during MCP tool re-discovery: {e}", exc_info=True
                )
                self.mcp_tools = []
            # You might need to re-register MCP tool endpoints

        logger.info("Capabilities reload complete.")

    def get_capabilities(self):
        """Get information about all available NATIVE skills and MCP tools"""
        # logger.critical(f"CRITICAL: Running CapabilitiesManager with Python version: {sys.version}")
        # logger.critical(f"CRITICAL: Python executable: {sys.executable}")

        capabilities = {"skills": {}, "mcp_tools": {}}  # Separate sections

        # --- Native Skills ---
        for skill_name, skill_instance in self.skills.items():
            # logging.info(f"Processing native skill: {skill_name}")
            if getattr(skill_instance, "hiddenCapability", False):
                # logging.info(f"Skipping hidden native skill: {skill_name}")
                continue

            skill_info = {
                "description": (
                    getattr(skill_instance.__class__, "__doc__", "") or ""
                ),
                "matcher_info": getattr(skill_instance, "matcher_info", ""),
                "type": "native",  # Indicate type
            }

            if not skill_info["description"]:
                logger.warning(
                    f"No description found for native skill '{skill_name}'."
                )
                # Decide if you want to skip or allow skills without descriptions
                # continue

            # Get information about the primary execution method (assuming 'run')
            run_method = getattr(skill_instance, "run", None)
            if run_method and callable(run_method):
                method_info = {
                    "description": run_method.__doc__ or "",
                    "parameters": {},
                    "return_type": "unknown",
                }

                try:
                    sig = inspect.signature(run_method)
                    # Use include_extras=True for Annotated
                    type_hints = get_type_hints(
                        run_method, include_extras=True
                    )

                    if "return" in type_hints:
                        method_info["return_type"] = str(type_hints["return"])

                    for param_name, param in sig.parameters.items():
                        if param_name == "self":
                            continue  # Skip self

                        param_type_hint = type_hints.get(param_name, Any)
                        param_desc = (  # Default description
                            f"Parameter '{param_name}'"
                        )

                        # Check if Annotated is used
                        origin = get_origin(param_type_hint)
                        args = get_args(param_type_hint)

                        actual_type = param_type_hint
                        if origin is Annotated and len(args) >= 2:
                            actual_type = args[0]
                            # Assume the second arg is the description string
                            if isinstance(args[1], str):
                                param_desc = args[1]
                            else:
                                logger.warning(
                                    f"Annotated metadata for '{param_name}' in"
                                    f" skill '{skill_name}' is not a string."
                                )
                        # else: # Optional: Warn if Annotated is not used
                        #     logger.warning(f"Parameter '{param_name}' in skill '{skill_name}' does not use Annotated for description.")

                        param_info = {
                            "type": str(actual_type),
                            "default": (
                                "None"
                                if param.default is param.empty
                                else repr(param.default)
                            ),
                            "required": param.default is param.empty,
                            "description": param_desc,
                        }
                        method_info["parameters"][param_name] = param_info

                    skill_info["run"] = method_info

                except (
                    Exception
                ) as e:  # Catch potential errors during inspection
                    logger.error(
                        "Error inspecting 'run' method for skill"
                        f" '{skill_name}': {e}",
                        exc_info=True,
                    )
                    skill_info["run"] = {
                        "error": f"Failed to inspect method: {e}"
                    }
            else:
                skill_info["run"] = {
                    "error": "No callable 'run' method found."
                }

            capabilities["skills"][
                self.camel_to_snake(skill_name)
            ] = skill_info

        # --- MCP Tools ---
        if self.mcp_client_manager:
            for tool in self.mcp_tools:
                tool_info = {
                    "description": tool.description,
                    "server": tool.server_name,
                    "type": "mcp",  # Indicate type
                    "run": {  # Mimic skill structure for consistency
                        "description": (
                            f"Executes the MCP tool '{tool.name}' on server"
                            f" '{tool.server_name}'."
                        ),
                        "parameters": {},
                        "return_type": (  # MCP doesn't define return type in list_tools
                            "any"
                        ),
                    },
                }
                # Parse MCP input schema into parameter info
                if "properties" in tool.input_schema:
                    required_params = tool.input_schema.get("required", [])
                    for param_name, param_schema in tool.input_schema[
                        "properties"
                    ].items():
                        param_info = {
                            "type": param_schema.get("type", "any"),
                            "default": (
                                "None"
                            ),  # MCP schema doesn't specify defaults here
                            "required": param_name in required_params,
                            "description": param_schema.get(
                                "description", "No description provided."
                            ),
                        }
                        tool_info["run"]["parameters"][param_name] = param_info

                capabilities["mcp_tools"][tool.prefixed_name] = tool_info

        return capabilities

    def get_all_capabilities_description(self) -> str:
        """Generate a combined description of native skills and MCP tools for an LLM."""
        description = "You have access to the following capabilities:\n\n"
        description += "=== Native Skills ===\n"
        native_skills_found = False
        for skill_name, skill_instance in self.skills.items():
            if getattr(skill_instance, "hiddenCapability", False):
                continue
            native_skills_found = True
            snake_name = self.camel_to_snake(skill_name)
            description += f"Skill: {snake_name}\n"
            description += (
                "Description:"
                f" {getattr(skill_instance.__class__, '__doc__', 'No description')}\n"
            )
            # Add parameters from run method if available
            run_method = getattr(skill_instance, "run", None)
            if run_method and callable(run_method):
                try:
                    sig = inspect.signature(run_method)
                    type_hints = get_type_hints(
                        run_method, include_extras=True
                    )
                    params_desc = []
                    for param_name, param in sig.parameters.items():
                        if param_name == "self":
                            continue
                        param_type_hint = type_hints.get(param_name, Any)
                        param_desc_str = f"- {param_name}"
                        origin = get_origin(param_type_hint)
                        args = get_args(param_type_hint)
                        actual_type = (
                            args[0]
                            if origin is Annotated and args
                            else param_type_hint
                        )
                        param_desc_str += f" (type: {str(actual_type)})"
                        if param.default is param.empty:
                            param_desc_str += " (required)"
                        # Add description from Annotated if present
                        if (
                            origin is Annotated
                            and len(args) >= 2
                            and isinstance(args[1], str)
                        ):
                            param_desc_str += f": {args[1]}"
                        params_desc.append(param_desc_str)
                    if params_desc:
                        description += (
                            "Arguments:\n" + "\n".join(params_desc) + "\n"
                        )
                except Exception as e:
                    description += f"Arguments: (Error inspecting: {e})\n"
            description += "---\n"

        if not native_skills_found:
            description += "(No native skills available)\n"

        if self.mcp_tools:
            description += "\n=== MCP Tools ===\n"
            for tool in self.mcp_tools:
                description += (
                    tool.format_for_llm()
                )  # Use the detailed format from MCPTool
                description += "---\n"
        else:
            description += (
                "\n=== MCP Tools ===\n(No MCP tools available or connected)\n"
            )

        return description

    def get_capability(self, name: str) -> Optional[Any]:
        """Get a native skill instance or MCPTool object by name."""
        # Check native skills (using snake_case name)
        for skill_class_name, skill_instance in self.skills.items():
            if self.camel_to_snake(skill_class_name) == name:
                return skill_instance  # Return the instance

        # Check MCP tools by prefixed name
        if self.mcp_client_manager:
            # Access tools safely - assuming MCPClientManager handles internal locking
            for (
                tool
            ) in self.mcp_client_manager.get_discovered_tools():  # Use getter
                if tool.prefixed_name == name:
                    return tool  # Return the MCPTool object
        return None

    def execute_capability(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a native skill or an MCP tool by its registered name."""
        capability = self.get_capability(name)

        if capability is None:
            raise ValueError(f"Capability '{name}' not found.")

        # Check if it's an MCP tool
        if isinstance(capability, MCPTool):
            if not self.mcp_client_manager:
                raise RuntimeError(
                    "MCP Client Manager not available for execution."
                )
            logger.info(f"Executing MCP tool: {name} with args: {arguments}")
            # The execute_tool method handles the async call in the background thread
            try:
                return self.mcp_client_manager.execute_tool(name, arguments)
            except Exception as e:
                logger.error(
                    f"Error executing MCP tool '{name}': {e}", exc_info=True
                )
                # Re-raise or return an error structure
                raise RuntimeError(
                    f"Failed to execute MCP tool '{name}': {e}"
                ) from e

        # Else, assume it's a native skill instance
        elif hasattr(capability, "run") and callable(capability.run):
            logger.info(
                f"Executing native skill: {name} with args: {arguments}"
            )
            try:
                # Handle both sync and async run methods
                if inspect.iscoroutinefunction(capability.run):
                    # If called from a sync context (like Flask route),
                    # need to run the coroutine.
                    # This requires an event loop. If MCP manager is running,
                    # we can try using its loop, otherwise, need another solution.
                    if (
                        self.mcp_client_manager
                        and self.mcp_client_manager._loop
                    ):
                        logger.debug(
                            f"Executing async native skill '{name}' using MCP"
                            " event loop."
                        )
                        future = asyncio.run_coroutine_threadsafe(
                            capability.run(**arguments),
                            self.mcp_client_manager._loop,
                        )
                        return future.result(timeout=120)  # Add timeout
                    else:
                        # Fallback: Run in a new temporary event loop (less efficient)
                        logger.warning(
                            f"Executing async native skill '{name}' in a"
                            " temporary event loop."
                        )
                        return asyncio.run(capability.run(**arguments))
                else:
                    # Synchronous execution
                    return capability.run(**arguments)
            except Exception as e:
                logger.error(
                    f"Error executing native skill '{name}': {e}",
                    exc_info=True,
                )
                # Re-raise or return an error structure
                raise RuntimeError(
                    f"Failed to execute native skill '{name}': {e}"
                ) from e
        else:
            # Should not happen if get_capability worked, but good failsafe
            raise TypeError(
                f"Capability '{name}' found but is not an MCPTool and has no"
                " callable 'run' method."
            )

    def register_capabilities_endpoint(self):
        """Register the /capabilities endpoint to list all capabilities."""

        @self.app.route("/capabilities", methods=["GET"])
        def get_capabilities_endpoint():  # Renamed function to avoid conflict
            try:
                return jsonify(self.get_capabilities())
            except Exception as e:
                logger.error(
                    f"Error generating capabilities list: {e}", exc_info=True
                )
                return (
                    jsonify({"error": "Failed to retrieve capabilities"}),
                    500,
                )

    def register_skills_endpoints(self):
        """Register direct endpoints ONLY for NATIVE skills."""
        logger.info("Registering native skill endpoints...")
        # Use a set to track registered routes to prevent duplicates if reload is called improperly
        registered_routes = set()

        for skill_name, skill_instance in self.skills.items():
            snake_name = self.camel_to_snake(skill_name)
            route_path = f"/skills/{snake_name}"  # Endpoint for native skills

            # Check if route already exists for this path (simple check)
            # A more robust check might involve inspecting app.url_map
            if route_path in registered_routes:
                logger.warning(
                    f"Route {route_path} already registered. Skipping."
                )
                continue

            endpoint_name = (  # Unique endpoint name
                f"native_skill_{snake_name}"
            )

            # Ensure the skill instance has a callable 'run' method
            if not (
                hasattr(skill_instance, "run") and callable(skill_instance.run)
            ):
                logger.warning(
                    f"Native skill '{skill_name}' has no callable 'run'"
                    " method. Skipping endpoint registration for"
                    f" {route_path}."
                )
                continue

            # --- Create handler using a closure ---
            def create_skill_handler(
                skill_name_closure, skill_instance_closure, snake_name_closure
            ):
                # Assign a unique name based on the skill
                handler_name = f"handle_native_{snake_name_closure}"

                def handler():
                    logger.debug(
                        "Handling request for native skill:"
                        f" {skill_name_closure}"
                    )
                    if not request.is_json:
                        # Allow empty body for GET requests if needed, but POST usually expects JSON
                        if request.method == "POST" and not request.data:
                            logger.error(
                                f"Request for {skill_name_closure} is not JSON"
                                " or has no data."
                            )
                            return (
                                jsonify(
                                    {"error": "Request must contain JSON data"}
                                ),
                                400,
                            )
                        # If GET or other methods allowed, handle appropriately
                        data = {}  # Assume empty dict if no JSON body
                    else:
                        try:
                            data = request.get_json()
                            if not isinstance(data, dict):
                                logger.error(
                                    f"Request data for {skill_name_closure} is"
                                    " not a JSON object."
                                )
                                return (
                                    jsonify(
                                        {
                                            "error": (
                                                "Request data must be a JSON"
                                                " object"
                                            )
                                        }
                                    ),
                                    400,
                                )
                        except Exception as e:
                            logger.error(
                                "Failed to parse JSON for"
                                f" {skill_name_closure}: {e}"
                            )
                            return (
                                jsonify({"error": f"Invalid JSON data: {e}"}),
                                400,
                            )

                    try:
                        # Use the execute_capability method for consistency
                        result = self.execute_capability(
                            snake_name_closure, data
                        )

                        # Handle different result types (dict, string, etc.)
                        if isinstance(result, (dict, list)):
                            return jsonify(result)
                        elif isinstance(result, str):
                            # Return as plain text or JSON string
                            return jsonify(
                                {"result": result}
                            )  # Or return Response(result, mimetype='text/plain')
                        elif result is None:
                            return (
                                jsonify({"result": None}),
                                200,
                            )  # Or 204 No Content
                        else:
                            # Try to convert to string or return as is if Flask handles it
                            return jsonify({"result": str(result)})

                    except (ValueError, TypeError, RuntimeError) as e:
                        # Errors during execution (e.g., capability not found, execution failed)
                        logger.error(
                            "Execution error for native skill"
                            f" '{skill_name_closure}': {e}",
                            exc_info=True,
                        )
                        return (
                            jsonify({"error": str(e)}),
                            400,
                        )  # Or 500 for server errors
                    except Exception as e:
                        # Catch unexpected errors during execution
                        logger.error(
                            "Unexpected error executing native skill"
                            f" '{skill_name_closure}': {e}",
                            exc_info=True,
                        )
                        return (
                            jsonify(
                                {"error": "An internal server error occurred"}
                            ),
                            500,
                        )

                # Set the unique name to the function object
                handler.__name__ = handler_name
                return handler

            # --- End of closure ---

            try:
                # Create the handler for this specific skill
                skill_handler = create_skill_handler(
                    skill_name, skill_instance, snake_name
                )
                # Register the route
                self.app.route(
                    route_path, methods=["POST"], endpoint=endpoint_name
                )(skill_handler)
                registered_routes.add(route_path)
                logger.info(
                    f"Registered native skill endpoint: POST {route_path} ->"
                    f" {endpoint_name}"
                )
            except Exception as e:
                logger.error(
                    "Failed to register route for native skill"
                    f" {skill_name} at {route_path}: {e}",
                    exc_info=True,
                )

    def register_mcp_tool_endpoints(self):
        """Register direct endpoints for discovered MCP tools (Optional)."""
        # Decide if you want direct HTTP access to MCP tools.
        # This might bypass central logic/logging you implement elsewhere.
        # If enabled, it mirrors the native skill endpoints.
        ENABLE_DIRECT_MCP_ENDPOINTS = False  # Set to True to enable

        if not ENABLE_DIRECT_MCP_ENDPOINTS:
            logger.info("Direct MCP tool endpoint registration is disabled.")
            return

        if not self.mcp_client_manager:
            logger.info(
                "MCP Client Manager not available, skipping MCP endpoint"
                " registration."
            )
            return

        logger.info("Registering MCP tool endpoints...")
        registered_routes = set()  # Track routes within this function

        for (
            tool
        ) in self.mcp_client_manager.get_discovered_tools():  # Use getter
            route_path = (  # Separate namespace
                f"/mcp_tools/{tool.prefixed_name}"
            )

            if route_path in registered_routes:
                logger.warning(
                    f"Route {route_path} already registered for MCP tool."
                    " Skipping."
                )
                continue

            endpoint_name = (  # Unique endpoint name
                f"mcp_tool_{tool.prefixed_name}"
            )

            # --- Create handler using a closure ---
            def create_mcp_handler(tool_closure):
                handler_name = f"handle_mcp_{tool_closure.prefixed_name}"

                def handler():
                    logger.debug(
                        "Handling request for MCP tool:"
                        f" {tool_closure.prefixed_name}"
                    )
                    if not request.is_json:
                        if request.method == "POST" and not request.data:
                            logger.error(
                                "Request for MCP tool"
                                f" {tool_closure.prefixed_name} is not JSON or"
                                " has no data."
                            )
                            return (
                                jsonify(
                                    {"error": "Request must contain JSON data"}
                                ),
                                400,
                            )
                        data = {}
                    else:
                        try:
                            data = request.get_json()
                            if not isinstance(data, dict):
                                logger.error(
                                    "Request data for MCP tool"
                                    f" {tool_closure.prefixed_name} is not a"
                                    " JSON object."
                                )
                                return (
                                    jsonify(
                                        {
                                            "error": (
                                                "Request data must be a JSON"
                                                " object"
                                            )
                                        }
                                    ),
                                    400,
                                )
                        except Exception as e:
                            logger.error(
                                "Failed to parse JSON for MCP tool"
                                f" {tool_closure.prefixed_name}: {e}"
                            )
                            return (
                                jsonify({"error": f"Invalid JSON data: {e}"}),
                                400,
                            )

                    try:
                        # Use the execute_capability method
                        result = self.execute_capability(
                            tool_closure.prefixed_name, data
                        )
                        # MCP results can be varied, try to return as JSON
                        return jsonify({"result": result})
                    except (ValueError, TypeError, RuntimeError) as e:
                        logger.error(
                            "Execution error for MCP tool"
                            f" '{tool_closure.prefixed_name}': {e}",
                            exc_info=True,
                        )
                        return jsonify({"error": str(e)}), 400  # Or 500
                    except Exception as e:
                        logger.error(
                            "Unexpected error executing MCP tool"
                            f" '{tool_closure.prefixed_name}': {e}",
                            exc_info=True,
                        )
                        return (
                            jsonify(
                                {"error": "An internal server error occurred"}
                            ),
                            500,
                        )

                handler.__name__ = handler_name
                return handler

            # --- End of closure ---

            try:
                mcp_handler = create_mcp_handler(tool)
                self.app.route(
                    route_path, methods=["POST"], endpoint=endpoint_name
                )(mcp_handler)
                registered_routes.add(route_path)
                logger.info(
                    f"Registered MCP tool endpoint: POST {route_path} ->"
                    f" {endpoint_name}"
                )
            except Exception as e:
                logger.error(
                    "Failed to register route for MCP tool"
                    f" {tool.prefixed_name} at {route_path}: {e}",
                    exc_info=True,
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

    def preview_dict(self, input_params, step_name=""):
        self.logger.debug(f"=== Parameter Preview for step: {step_name} ===")
        self.logger.debug("Input parameters:")
        for key, value in input_params.items():
            self.logger.debug(f"Key: {key}")
            self.logger.debug(f"Value type: {type(value)}")
            self.logger.debug(f"Value: {value}")
            self.logger.debug("-" * 50)
