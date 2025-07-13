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
MCP connection strategy for HTTP servers with Bearer token authentication.
"""

import logging
import threading
from contextlib import AsyncExitStack
from typing import Any, Dict, List

# Import httpx for HTTP requests
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

    # Define a dummy class for type checking
    class httpx:
        class AsyncClient:
            pass

        class HTTPStatusError(Exception):
            pass

        class RequestError(Exception):
            pass


from ..errors import (MCPAuthenticationError, MCPConnectionError,
                      MCPToolDiscoveryError, MCPToolExecutionError)
from ..tool import MCPTool
from .base import MCPStrategyBase

logger = logging.getLogger(__name__)


class MCPStrategyHttpBearer(MCPStrategyBase):
    """
    Strategy for connecting to MCP servers via HTTP with Bearer token authentication.
    """

    def __init__(self, server_name: str, config: Dict[str, Any], loop):
        """
        Initialize the HTTP Bearer strategy.

        Args:
            server_name: Name of the MCP server
            config: Configuration for this server
            loop: Asyncio event loop to use for async operations
        """
        super().__init__(server_name, config, loop)

        if not HTTPX_AVAILABLE:
            raise ImportError(
                "httpx package is required for HTTP Bearer strategy. "
                "Install it with: pip install httpx"
            )

        self.base_url = self.config.get("url")
        if not self.base_url:
            raise ValueError(
                "URL not configured for HTTP Bearer strategy server"
                f" '{self.server_name}'"
            )

        self.timeout = self.config.get("timeout", 60)
        self._token = self.config.get("authentication", {}).get(
            "token"
        )  # Initial token from config
        self._headers = {}
        self._lock = threading.Lock()  # For thread-safe header updates
        self._update_auth_header()

    def _update_auth_header(self):
        """Update the authorization header with the current token."""
        with self._lock:
            self._headers = {"Content-Type": "application/json"}
            if self._token:
                self._headers["Authorization"] = f"Bearer {self._token}"
            else:
                # No token, remove Authorization header if it was set
                self._headers.pop("Authorization", None)

    async def update_auth_token(self, token: str) -> None:
        """
        Update the authentication token.

        Args:
            token: New authentication token
        """
        logger.info(
            f"Updating auth token for HTTP Bearer strategy: {self.server_name}"
        )
        with self._lock:
            self._token = token
            self._update_auth_header()

            # If we have an active client, update its headers
            if isinstance(self._active_session_or_client, httpx.AsyncClient):
                # Create new headers dict to avoid modifying the client's headers directly
                new_headers = dict(self._active_session_or_client.headers)
                if self._token:
                    new_headers["Authorization"] = f"Bearer {self._token}"
                else:
                    new_headers.pop("Authorization", None)
                self._active_session_or_client.headers = new_headers

    async def connect(self, exit_stack: AsyncExitStack) -> None:
        """
        Connect to an MCP server via HTTP.

        Args:
            exit_stack: AsyncExitStack to register resources with

        Raises:
            MCPConnectionError: If connection fails
        """
        try:
            if not self._token:
                logger.warning(
                    "No bearer token available for MCP server"
                    f" '{self.server_name}'. Authentication might fail."
                )

            # Create and register httpx.AsyncClient with the exit_stack
            client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=dict(self._headers),  # Use a copy of headers
                follow_redirects=True,
            )
            self._active_session_or_client = (
                await exit_stack.enter_async_context(client)
            )

            # Test the connection with a simple request
            # This could be a dedicated health check endpoint or the list-tools endpoint
            try:
                # Assuming the server has a health check endpoint
                response = await client.get(
                    f"{self.base_url.rstrip('/')}/health",
                    headers=self._headers,
                )
                response.raise_for_status()
                logger.info(
                    "Successfully connected to MCP server"
                    f" '{self.server_name}' via HTTP"
                )
            except httpx.HTTPStatusError as e:
                if (
                    e.response.status_code == 401
                    or e.response.status_code == 403
                ):
                    raise MCPAuthenticationError(
                        "Authentication failed for MCP server"
                        f" '{self.server_name}': {e.response.text}"
                    ) from e
                elif e.response.status_code == 404:
                    # Health endpoint might not exist, that's okay
                    logger.info(
                        "Health check endpoint not found for MCP server"
                        f" '{self.server_name}'. Continuing anyway."
                    )
                else:
                    raise MCPConnectionError(
                        "HTTP error connecting to MCP server"
                        f" '{self.server_name}': {e.response.status_code} -"
                        f" {e.response.text}"
                    ) from e
            except httpx.RequestError as e:
                raise MCPConnectionError(
                    "Request error connecting to MCP server"
                    f" '{self.server_name}': {str(e)}"
                ) from e

        except (MCPAuthenticationError, MCPConnectionError):
            # Re-raise these specific exceptions
            raise
        except Exception as e:
            logger.error(
                f"Error connecting to MCP server '{self.server_name}' via"
                f" HTTP: {e}",
                exc_info=True,
            )
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.server_name}' via"
                f" HTTP: {str(e)}"
            ) from e

    async def list_tools(self) -> List[MCPTool]:
        """
        List tools from the MCP server.

        Returns:
            List of MCPTool objects

        Raises:
            MCPToolDiscoveryError: If tool discovery fails
        """
        if not isinstance(self._active_session_or_client, httpx.AsyncClient):
            raise MCPToolDiscoveryError(
                f"HTTP client not connected for '{self.server_name}'"
            )

        client: httpx.AsyncClient = self._active_session_or_client
        try:
            # Assuming MCP standard defines an endpoint like GET /tools or POST /list-tools
            # This needs to be defined by your MCP server implementation
            response = await client.post(
                f"{self.base_url.rstrip('/')}/list-tools",
                headers=self._headers,
            )
            response.raise_for_status()

            tools_data = (
                response.json()
            )  # Expecting a JSON list of tool definitions
            discovered_tools = []

            # Parse tools_data (assuming it's a list of dicts matching MCPTool structure)
            if isinstance(tools_data, list):
                for tool_info_dict in tools_data:
                    # Example: tool_info_dict = {"name": "tool1", "description": "...", "inputSchema": {...}}
                    if all(
                        key in tool_info_dict
                        for key in ["name", "description", "inputSchema"]
                    ):
                        prefixed_name = self.get_prefixed_tool_name(
                            tool_info_dict["name"]
                        )
                        mcp_tool = MCPTool(
                            server_name=self.server_name,
                            name=tool_info_dict["name"],
                            description=tool_info_dict["description"],
                            input_schema=tool_info_dict["inputSchema"],
                            prefixed_name=prefixed_name,
                        )
                        discovered_tools.append(mcp_tool)
                        logger.debug(
                            f"Discovered MCP tool: {prefixed_name} from server"
                            f" {self.server_name}"
                        )
                    else:
                        logger.warning(
                            f"Invalid tool data from {self.server_name}:"
                            f" {tool_info_dict}"
                        )
            else:
                logger.warning(
                    "Unexpected tools response format from"
                    f" {self.server_name}: {type(tools_data)}"
                )

            return discovered_tools

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401 or e.response.status_code == 403:
                logger.error(
                    "Authentication error listing tools from"
                    f" '{self.server_name}': {e.response.status_code} -"
                    f" {e.response.text}"
                )
                raise MCPAuthenticationError(
                    "Authentication failed when listing tools from MCP server"
                    f" '{self.server_name}'"
                ) from e
            else:
                logger.error(
                    f"HTTP error listing tools from '{self.server_name}': "
                    f"{e.response.status_code} - {e.response.text}"
                )
                raise MCPToolDiscoveryError(
                    "HTTP error when listing tools from MCP server"
                    f" '{self.server_name}'"
                ) from e
        except httpx.RequestError as e:
            logger.error(
                f"Request error listing tools from '{self.server_name}': {e}"
            )
            raise MCPToolDiscoveryError(
                "Network error when listing tools from MCP server"
                f" '{self.server_name}'"
            ) from e
        except Exception as e:
            logger.error(
                f"Error processing tools from '{self.server_name}': {e}",
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
        if not isinstance(self._active_session_or_client, httpx.AsyncClient):
            raise MCPToolExecutionError(
                f"HTTP client not connected for '{self.server_name}'"
            )

        client: httpx.AsyncClient = self._active_session_or_client
        try:
            # Assuming MCP standard defines an endpoint like POST /call-tool
            payload = {"tool_name": tool_name, "arguments": arguments}
            response = await client.post(
                f"{self.base_url.rstrip('/')}/call-tool",
                json=payload,
                headers=self._headers,
            )
            response.raise_for_status()

            # Parse the response
            result = response.json()
            logger.info(f"MCP tool '{tool_name}' execution result: {result}")
            return result

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401 or e.response.status_code == 403:
                logger.error(
                    f"Authentication error calling tool '{tool_name}' on"
                    f" '{self.server_name}': {e.response.status_code} -"
                    f" {e.response.text}"
                )
                raise MCPAuthenticationError(
                    f"Authentication failed when calling tool '{tool_name}' on"
                    f" MCP server '{self.server_name}'"
                ) from e
            else:
                logger.error(
                    f"HTTP error calling tool '{tool_name}' on"
                    f" '{self.server_name}': {e.response.status_code} -"
                    f" {e.response.text}"
                )
                raise MCPToolExecutionError(
                    f"HTTP error when calling tool '{tool_name}' on MCP server"
                    f" '{self.server_name}'"
                ) from e
        except httpx.RequestError as e:
            logger.error(
                f"Request error calling tool '{tool_name}' on"
                f" '{self.server_name}': {e}"
            )
            raise MCPToolExecutionError(
                f"Network error when calling tool '{tool_name}' on MCP server"
                f" '{self.server_name}'"
            ) from e
        except Exception as e:
            logger.error(
                f"Error during tool call '{tool_name}' on"
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
