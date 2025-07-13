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

"""
MCP connection strategy for stdio-based servers.
"""

import logging
import os
import shutil
from contextlib import AsyncExitStack
from typing import Any, Dict, List

from ..errors import (MCPConnectionError, MCPToolDiscoveryError,
                      MCPToolExecutionError)
from ..tool import MCPTool
from .base import MCPStrategyBase

logger = logging.getLogger(__name__)

# Check if MCP SDK is available
try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    MCP_SDK_AVAILABLE = True
except ImportError:
    MCP_SDK_AVAILABLE = False

    # Define dummy types for type checking
    class ClientSession:
        pass

    class StdioServerParameters:
        pass

    def stdio_client(params):
        pass


class MCPStrategyStdio(MCPStrategyBase):
    """
    Strategy for connecting to MCP servers via standard I/O.
    Uses the MCP SDK's stdio client.
    """

    async def connect(self, exit_stack: AsyncExitStack) -> None:
        """
        Connect to an MCP server via stdio.

        Args:
            exit_stack: AsyncExitStack to register resources with

        Raises:
            MCPConnectionError: If connection fails
        """
        if not MCP_SDK_AVAILABLE:
            raise MCPConnectionError(
                "MCP SDK not available for stdio connection to"
                f" '{self.server_name}'"
            )

        try:
            stdio_params = self.config["stdio_params"]
            command_list = stdio_params["command"]

            # Resolve command path (e.g., npx)
            command_path = shutil.which(command_list[0])
            if not command_path:
                raise MCPConnectionError(
                    f"Command '{command_list[0]}' not found in PATH for MCP"
                    f" server '{self.server_name}'"
                )

            resolved_command = [command_path] + command_list[1:]
            logger.info(
                f"Starting MCP server '{self.server_name}' with command:"
                f" {' '.join(resolved_command)}"
            )

            # Split command into base command and arguments for StdioServerParameters
            base_command = resolved_command[0]
            command_args = (
                resolved_command[1:] if len(resolved_command) > 1 else []
            )

            server_params = StdioServerParameters(
                command=base_command,  # Base command (e.g., /usr/bin/npx)
                args=command_args,  # Arguments (e.g., @modelcontextprotocol/server-google-maps)
                env={**os.environ, **stdio_params.get("env", {})},
            )

            # stdio_client needs to be managed by the exit stack
            stdio_transport = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport

            # ClientSession also needs to be managed by the exit stack
            session = await exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()

            # Store the session for later use
            self._active_session_or_client = session
            logger.info(
                f"Successfully connected to MCP server '{self.server_name}'"
                " via stdio"
            )

        except Exception as e:
            logger.error(
                f"Error connecting to MCP server '{self.server_name}' via"
                f" stdio: {e}",
                exc_info=True,
            )
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.server_name}' via"
                f" stdio: {str(e)}"
            ) from e

    async def list_tools(self) -> List[MCPTool]:
        """
        List tools from the MCP server.

        Returns:
            List of MCPTool objects

        Raises:
            MCPToolDiscoveryError: If tool discovery fails
        """
        if not self._active_session_or_client:
            raise MCPToolDiscoveryError(
                f"Not connected to MCP server '{self.server_name}'"
            )

        try:
            session: ClientSession = self._active_session_or_client
            tools_response = await session.list_tools()
            discovered_tools = []

            # Handle different possible response formats dynamically
            tools_list = []
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
                    "Unexpected tools response format from server"
                    f" {self.server_name}: {type(tools_response)}"
                )

            for tool_info in tools_list:
                try:
                    # Assume tool_info is an object with attributes like name, description, inputSchema
                    if (
                        hasattr(tool_info, "name")
                        and hasattr(tool_info, "description")
                        and hasattr(tool_info, "inputSchema")
                    ):
                        prefixed_name = self.get_prefixed_tool_name(
                            tool_info.name
                        )
                        mcp_tool = MCPTool(
                            server_name=self.server_name,
                            name=tool_info.name,
                            description=tool_info.description,
                            input_schema=tool_info.inputSchema,
                            prefixed_name=prefixed_name,
                        )
                        discovered_tools.append(mcp_tool)
                        logger.debug(
                            f"Discovered MCP tool: {prefixed_name} from server"
                            f" {self.server_name}"
                        )
                    else:
                        logger.warning(
                            "Tool info missing expected attributes from"
                            f" server {self.server_name}: {tool_info}"
                        )
                except Exception as e:
                    logger.error(
                        "Error processing tool info from server"
                        f" {self.server_name}: {e}",
                        exc_info=True,
                    )

            return discovered_tools

        except Exception as e:
            logger.error(
                "Error discovering tools from MCP server"
                f" '{self.server_name}': {e}",
                exc_info=True,
            )
            raise MCPToolDiscoveryError(
                "Failed to discover tools from MCP server"
                f" '{self.server_name}': {str(e)}"
            ) from e

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call (original name, not prefixed)
            arguments: Arguments to pass to the tool

        Returns:
            Result of the tool execution

        Raises:
            MCPToolExecutionError: If tool execution fails
        """
        if not self._active_session_or_client:
            raise MCPToolExecutionError(
                f"Not connected to MCP server '{self.server_name}'"
            )

        try:
            session: ClientSession = self._active_session_or_client
            logger.info(
                f"Executing MCP tool '{tool_name}' on server"
                f" '{self.server_name}' with args: {arguments}"
            )
            result = await session.call_tool(tool_name, arguments)
            logger.info(f"MCP tool '{tool_name}' execution result: {result}")
            return result

        except Exception as e:
            logger.error(
                f"Error executing MCP tool '{tool_name}' on server"
                f" '{self.server_name}': {e}",
                exc_info=True,
            )
            raise MCPToolExecutionError(
                f"Failed to execute tool '{tool_name}' on MCP server"
                f" '{self.server_name}': {str(e)}"
            ) from e

    async def close(self) -> None:
        """
        Close the connection to the MCP server.
        Resources are managed by the exit stack, so this is mostly a cleanup of internal state.
        """
        logger.info(f"Closing connection to MCP server '{self.server_name}'")
        # Resources are managed by exit_stack, just clear our reference
        self._active_session_or_client = None
