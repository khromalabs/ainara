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
import logging
import os
import shutil
import threading
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, Tuple

# Ensure mcp-sdk is installed: pip install mcp-sdk
try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

    # Define dummy types if mcp is not available to avoid runtime errors on import
    class ClientSession:
        pass

    class StdioServerParameters:
        pass

    def stdio_client(params):
        pass


logger = logging.getLogger(__name__)


class MCPTool:
    """Represents a discovered MCP tool."""

    def __init__(
        self,
        server_name: str,
        name: str,
        description: str,
        input_schema: dict,
        prefixed_name: str,
    ):
        self.server_name = server_name
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.prefixed_name = prefixed_name  # Name including the prefix

    def __repr__(self):
        return (
            f"MCPTool(server='{self.server_name}',"
            f" name='{self.prefixed_name}')"
        )

    def format_for_llm(self) -> str:
        """Format tool information for LLM to closely mimic native skills with Annotated metadata."""
        args_desc = []
        if "properties" in self.input_schema:
            for param_name, param_info in self.input_schema.get(
                "properties", {}
            ).items():
                # Map JSON schema type to Python type
                param_type = param_info.get("type", "string")
                type_mapping = {
                    "string": "str",
                    "number": "float",
                    "integer": "int",
                    "boolean": "bool",
                    "object": "dict",
                    "array": "list",
                }
                python_type = type_mapping.get(param_type, param_type)

                # Handle array items type if specified
                if param_type == "array" and "items" in param_info:
                    item_type = param_info["items"].get("type", "any")
                    python_item_type = type_mapping.get(item_type, item_type)
                    python_type = f"List[{python_item_type}]"

                # Handle enum or literal types
                if "enum" in param_info and isinstance(
                    param_info["enum"], list
                ):
                    python_type = (
                        f"Literal[{', '.join([repr(opt) for opt in param_info['enum']])}]"
                    )

                # Build constraints description
                constraints = []
                if param_type == "string":
                    if "minLength" in param_info:
                        constraints.append(
                            f"min length: {param_info['minLength']}"
                        )
                    if "maxLength" in param_info:
                        constraints.append(
                            f"max length: {param_info['maxLength']}"
                        )
                    if "pattern" in param_info:
                        constraints.append(f"pattern: {param_info['pattern']}")
                elif param_type in ("number", "integer"):
                    if "minimum" in param_info:
                        constraints.append(f"minimum: {param_info['minimum']}")
                    if "maximum" in param_info:
                        constraints.append(f"maximum: {param_info['maximum']}")

                constraints_str = (
                    f", constraints: {'; '.join(constraints)}"
                    if constraints
                    else ""
                )

                # Extract description and default value
                param_desc = param_info.get(
                    "description", "No description provided"
                )
                param_default = param_info.get("default", None)
                default_str = (
                    f", default: {repr(param_default)}"
                    if param_default is not None
                    else ""
                )

                # Build the description line similar to Annotated style
                arg_desc = (
                    f"- {param_name}:"
                    f" {param_desc}"
                    f" (type: {python_type}{default_str}{constraints_str})"
                )
                if param_name in self.input_schema.get("required", []):
                    arg_desc += " (required)"
                args_desc.append(arg_desc)

        return f"""
Tool: {self.prefixed_name}
Description: {self.description}
Arguments:
{chr(10).join(args_desc) if args_desc else "None"}
"""


class MCPClientManager:
    """Manages connections and interactions with multiple MCP servers."""

    def __init__(self, mcp_config: Optional[Dict[str, Any]]):
        if not MCP_AVAILABLE:
            logger.warning(
                "MCP SDK not installed. MCP client functionality disabled."
            )
            self.mcp_config = {}
            self._servers = {}
            self._sessions = {}
            self._tools: List[MCPTool] = []
            self._loop = None
            self._thread = None
            self._exit_stack = None
            self._lock = (
                threading.Lock()
            )  # For thread-safe access to tools/sessions
            return

        self.mcp_config = mcp_config if mcp_config else {}
        self._servers: Dict[str, Dict[str, Any]] = {}  # server_name -> config
        self._sessions: Dict[str, ClientSession] = {}  # server_name -> session
        self._tools: List[MCPTool] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._lock = (
            threading.Lock()
        )  # For thread-safe access to tools/sessions

        logger.info("MCP Client Manager initialized.")
        self._prepare_servers()

    def _prepare_servers(self):
        """Prepare server configurations based on the main config."""
        if not MCP_AVAILABLE:
            return
        for name, config in self.mcp_config.items():
            if (
                config.get("enabled", True)
                and config.get("connection_type", "stdio_mcp_lib") == "stdio_mcp_lib"
            ):
                if (
                    "stdio_params" in config
                    and "command" in config["stdio_params"]
                ):
                    self._servers[name] = config
                    logger.info(f"Prepared MCP server config: {name}")
                else:
                    logger.warning(
                        f"Skipping MCP server '{name}': Missing 'stdio_params'"
                        " or 'command'."
                    )
            else:
                logger.debug(
                    f"Skipping disabled or unsupported MCP server: {name}"
                )

    def _run_event_loop(self):
        """Runs the asyncio event loop in a separate thread."""
        if not MCP_AVAILABLE:
            return
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        finally:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            logger.info("MCP Client event loop stopped.")

    async def _connect_and_discover_async(self):
        """Async function to connect to servers and discover tools."""
        if not MCP_AVAILABLE:
            return []
        self._exit_stack = AsyncExitStack()
        connect_tasks = []

        for name, config in self._servers.items():
            connect_tasks.append(self._connect_single_server(name, config))

        results = await asyncio.gather(*connect_tasks, return_exceptions=True)

        temp_sessions = {}
        temp_tools = []
        for i, result in enumerate(results):
            server_name = list(self._servers.keys())[i]
            if isinstance(result, Exception):
                logger.error(
                    "Failed to connect or discover tools for MCP server"
                    f" '{server_name}': {result}"
                )
            elif result:
                session, tools = result
                temp_sessions[server_name] = session
                temp_tools.extend(tools)
                logger.info(
                    f"Successfully connected to MCP server '{server_name}' and"
                    f" discovered {len(tools)} tools."
                )
            else:
                logger.error(
                    f"Connection attempt for MCP server '{server_name}'"
                    " returned None."
                )

        with self._lock:
            self._sessions = temp_sessions
            self._tools = temp_tools

        return self._tools  # Return the discovered tools

    async def _connect_single_server(
        self, name: str, config: Dict[str, Any]
    ) -> Optional[Tuple[ClientSession, List[MCPTool]]]:
        """Connects to a single MCP server and discovers its tools."""
        if not MCP_AVAILABLE:
            return None
        stdio_params = config["stdio_params"]
        prefix = config.get("prefix", "")

        command_list = stdio_params["command"]
        # Resolve command path (e.g., npx)
        command_path = shutil.which(command_list[0])
        if not command_path:
            logger.error(
                f"Command '{command_list[0]}' not found in PATH for MCP server"
                f" '{name}'."
            )
            return None

        resolved_command = [command_path] + command_list[1:]
        logger.info(
            f"Starting MCP server '{name}' with command:"
            f" {' '.join(resolved_command)}"
        )

        # Split command into base command and arguments for StdioServerParameters
        if isinstance(resolved_command, list) and len(resolved_command) > 0:
            base_command = resolved_command[0]
            command_args = (
                resolved_command[1:] if len(resolved_command) > 1 else []
            )
        else:
            base_command = resolved_command
            command_args = []

        server_params = StdioServerParameters(
            command=base_command,  # Base command (e.g., /usr/bin/npx)
            args=command_args,  # Arguments (e.g., @modelcontextprotocol/server-google-maps)
            env={**os.environ, **stdio_params.get("env", {})},
        )

        try:
            # stdio_client needs to be managed by the exit stack
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport

            # ClientSession also needs to be managed by the exit stack
            session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()

            # Discover tools
            tools_response = await session.list_tools()
            discovered_tools = []
            logger.debug(
                f"Tools response from server {name}: {tools_response}"
            )

            # Handle different possible response formats dynamically
            if isinstance(tools_response, list):
                tools_list = tools_response
            elif (
                isinstance(tools_response, tuple)
                and len(tools_response) > 1
                and tools_response[0] == "tools"
            ):
                tools_list = (
                    tools_response[1]
                    if isinstance(tools_response[1], list)
                    else []
                )
            elif hasattr(tools_response, "tools") and isinstance(
                tools_response.tools, list
            ):
                tools_list = tools_response.tools
            else:
                logger.warning(
                    f"Unexpected tools response format from server {name}:"
                    f" {type(tools_response)}"
                )
                tools_list = []

            for tool_info in tools_list:
                try:
                    # Assume tool_info is an object with attributes like name, description, inputSchema
                    # Adjust based on actual response structure if needed
                    if (
                        hasattr(tool_info, "name")
                        and hasattr(tool_info, "description")
                        and hasattr(tool_info, "inputSchema")
                    ):
                        prefixed_name = f"{prefix}{tool_info.name}"
                        mcp_tool = MCPTool(
                            server_name=name,
                            name=tool_info.name,
                            description=tool_info.description,
                            input_schema=tool_info.inputSchema,
                            prefixed_name=prefixed_name,
                        )
                        discovered_tools.append(mcp_tool)
                        logger.debug(
                            f"Discovered MCP tool: {prefixed_name} from server"
                            f" {name}"
                        )
                    else:
                        logger.warning(
                            "Tool info missing expected attributes from"
                            f" server {name}: {tool_info}"
                        )
                except Exception as e:
                    logger.error(
                        f"Error processing tool info from server {name}: {e}",
                        exc_info=True,
                    )

            return session, discovered_tools

        except Exception as e:
            logger.error(
                "Error connecting to or discovering tools for MCP server"
                f" '{name}': {e}"
            )
            # The exit stack will handle cleanup for this failed connection
            return None  # Indicate failure

    def connect_and_discover(self) -> List[MCPTool]:
        """Starts the event loop thread, connects to servers, discovers tools."""
        if not MCP_AVAILABLE or not self._servers:
            logger.info(
                "No enabled MCP servers configured or MCP SDK not available."
            )
            return []

        if self._thread is None or not self._thread.is_alive():
            logger.info("Starting MCP client event loop thread.")
            self._thread = threading.Thread(
                target=self._run_event_loop, daemon=True
            )
            self._thread.start()
            # Give the loop a moment to start
            import time

            time.sleep(0.1)

        if not self._loop:
            logger.error("MCP event loop failed to start.")
            return []

        # Run the async connection/discovery logic within the event loop thread
        future = asyncio.run_coroutine_threadsafe(
            self._connect_and_discover_async(), self._loop
        )
        try:
            # Wait for the connection and discovery process to complete
            discovered_tools = future.result(
                timeout=60
            )  # Adjust timeout as needed
            logger.info(
                f"MCP discovery complete. Found {len(discovered_tools)} tools."
            )
            return discovered_tools
        except Exception as e:
            logger.error(f"Error during MCP connection/discovery: {e}")
            future.cancel()  # Attempt to cancel the coroutine
            return []

    def get_discovered_tools(self) -> List[MCPTool]:
        """Returns the list of discovered tools (thread-safe)."""
        with self._lock:
            return list(self._tools)  # Return a copy

    async def _execute_tool_async(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Async function to execute a tool on a specific server."""
        if not MCP_AVAILABLE:
            raise RuntimeError("MCP SDK not available.")

        session = None
        with self._lock:
            session = self._sessions.get(server_name)

        if not session:
            raise ValueError(
                f"No active session found for MCP server '{server_name}'. Is"
                " it connected?"
            )

        logger.info(
            f"Executing MCP tool '{tool_name}' on server '{server_name}' with"
            f" args: {arguments}"
        )
        try:
            # TODO: Add retry logic similar to the example if needed
            result = await session.call_tool(tool_name, arguments)
            logger.info(f"MCP tool '{tool_name}' execution result: {result}")
            return result
        except Exception as e:
            logger.error(
                f"Error executing MCP tool '{tool_name}' on server"
                f" '{server_name}': {e}"
            )
            raise  # Re-raise the exception to be handled by the caller

    def execute_tool(
        self, prefixed_tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Executes a tool by its prefixed name (thread-safe)."""
        if not MCP_AVAILABLE:
            raise RuntimeError("MCP SDK not available.")
        if not self._loop or not self._loop.is_running():
            raise RuntimeError("MCP client event loop is not running.")

        target_tool: Optional[MCPTool] = None
        with self._lock:
            for tool in self._tools:
                if tool.prefixed_name == prefixed_tool_name:
                    target_tool = tool
                    break

        if not target_tool:
            raise ValueError(f"MCP tool '{prefixed_tool_name}' not found.")

        # Run the async execution logic within the event loop thread
        future = asyncio.run_coroutine_threadsafe(
            self._execute_tool_async(
                target_tool.server_name, target_tool.name, arguments
            ),
            self._loop,
        )
        try:
            # Wait for the execution to complete
            result = future.result(timeout=120)  # Adjust timeout as needed
            return result
        except Exception as e:
            logger.error(f"Error waiting for MCP tool execution result: {e}")
            future.cancel()
            raise  # Re-raise the exception

    async def _shutdown_async(self):
        """Async function to clean up resources."""
        if not MCP_AVAILABLE:
            return
        logger.info("Shutting down MCP client connections...")
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        with self._lock:
            self._sessions.clear()
            self._tools.clear()
        logger.info("MCP client connections closed.")

    def shutdown(self):
        """Shuts down connections and stops the event loop thread."""
        if not MCP_AVAILABLE:
            return
        logger.info("Initiating MCP Client Manager shutdown...")
        if self._loop and self._loop.is_running():
            # Shutdown async resources first
            if self._exit_stack:
                future = asyncio.run_coroutine_threadsafe(
                    self._shutdown_async(), self._loop
                )
                try:
                    future.result(timeout=30)
                except Exception as e:
                    logger.error(f"Error during async MCP shutdown: {e}")
                    future.cancel()

            # Stop the loop
            self._loop.call_soon_threadsafe(self._loop.stop)

        # Wait for the thread to finish
        if self._thread and self._thread.is_alive():
            logger.info("Waiting for MCP client thread to terminate...")
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning(
                    "MCP client thread did not terminate gracefully."
                )

        self._loop = None
        self._thread = None
        logger.info("MCP Client Manager shutdown complete.")
