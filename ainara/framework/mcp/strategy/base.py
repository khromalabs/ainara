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
Base class for MCP connection strategies.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from typing import Any, Dict, List

# from ..errors import MCPError
from ..tool import MCPTool

logger = logging.getLogger(__name__)


class MCPStrategyBase(ABC):
    """
    Abstract base class for MCP server connection and interaction strategies.
    """

    def __init__(
        self,
        server_name: str,
        config: Dict[str, Any],
        loop: asyncio.AbstractEventLoop,
    ):
        """
        Initialize the strategy.

        Args:
            server_name: Name of the MCP server
            config: Configuration for this server
            loop: Asyncio event loop to use for async operations
        """
        self.server_name = server_name
        self.config = config
        self.loop = loop
        self.prefix = config.get("prefix", "")
        self._active_session_or_client: Any = (
            None  # Stores the active connection
        )

    @abstractmethod
    async def connect(self, exit_stack: AsyncExitStack) -> None:
        """
        Establishes a connection to the MCP server.
        Should register resources with the exit_stack.

        Args:
            exit_stack: AsyncExitStack to register resources with

        Raises:
            MCPConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def list_tools(self) -> List[MCPTool]:
        """
        Lists available tools from the MCP server using the established connection.

        Returns:
            List of MCPTool objects

        Raises:
            MCPToolDiscoveryError: If tool discovery fails
        """
        pass

    @abstractmethod
    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """
        Calls a specific tool on the MCP server.

        Args:
            tool_name: Name of the tool to call (original name, not prefixed)
            arguments: Arguments to pass to the tool

        Returns:
            Result of the tool execution

        Raises:
            MCPToolExecutionError: If tool execution fails
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        Closes the connection and cleans up resources.
        Often managed by the exit_stack, but can be explicit.

        Raises:
            MCPError: If cleanup fails
        """
        pass

    def get_prefixed_tool_name(self, tool_name: str) -> str:
        """
        Get the prefixed tool name.

        Args:
            tool_name: Original tool name

        Returns:
            Prefixed tool name
        """
        return f"{self.prefix}{tool_name}"

    async def update_auth_token(self, token: str) -> None:
        """
        Updates authentication token if strategy supports it.
        Default implementation does nothing, override in relevant strategies.

        Args:
            token: New authentication token
        """
        # Default implementation does nothing
        logger.debug(
            f"update_auth_token not implemented for {self.__class__.__name__}"
        )
