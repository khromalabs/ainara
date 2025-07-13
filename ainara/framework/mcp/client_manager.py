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
MCP client manager for connecting to and interacting with MCP servers.
"""

import asyncio
import concurrent.futures
import logging
import threading
import time
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from .errors import MCPToolExecutionError
# from .errors import (MCPAuthenticationError, MCPConnectionError, MCPError,
#                      MCPToolDiscoveryError, MCPToolExecutionError)
from .strategy import MCPStrategyBase, MCPStrategyHttpBearer, MCPStrategyStdio
from .tool import MCPTool

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Manages connections and interactions with multiple MCP servers."""

    def __init__(self, mcp_config: Optional[Dict[str, Any]] = None):
        """
        Initialize the MCP client manager.

        Args:
            mcp_config: Configuration for MCP servers
        """
        self.mcp_config = mcp_config if mcp_config else {}
        self._server_configs: Dict[str, Dict[str, Any]] = (
            {}
        )  # server_name -> config
        self._strategies: Dict[str, MCPStrategyBase] = (
            {}
        )  # server_name -> strategy
        self._tools: List[MCPTool] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._manager_future: Optional[concurrent.futures.Future] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._lock = (
            threading.Lock()
        )  # For thread-safe access to tools/strategies
        self._dynamic_auth_tokens: Dict[str, str] = {}  # server_name -> token
        self._strategy_classes: Dict[str, Type[MCPStrategyBase]] = {
            "stdio_mcp_lib": MCPStrategyStdio,
            "http_bearer": MCPStrategyHttpBearer,
            # Add more strategy types here as they are implemented
        }

        logger.info("MCP Client Manager initialized")
        self._prepare_servers()

    def _prepare_servers(self):
        """Prepare server configurations based on the main config."""
        for name, config in self.mcp_config.items():
            if not config.get("enabled", True):
                logger.debug(f"Skipping disabled MCP server: {name}")
                continue

            connection_type = config.get("connection_type", "stdio_mcp_lib")

            # Check if we have a strategy class for this connection type
            if connection_type not in self._strategy_classes:
                logger.warning(
                    f"Unsupported connection type '{connection_type}' for MCP"
                    f" server '{name}'. Supported types:"
                    f" {list(self._strategy_classes.keys())}"
                )
                continue

            # Basic validation based on connection type
            if connection_type == "stdio_mcp_lib":
                if not (
                    "stdio_params" in config
                    and "command" in config["stdio_params"]
                ):
                    logger.warning(
                        f"Skipping MCP server '{name}': Missing 'stdio_params'"
                        " or 'command'"
                    )
                    continue
            elif connection_type == "http_bearer":
                if not config.get("url"):
                    logger.warning(
                        f"Skipping MCP server '{name}': Missing 'url' for"
                        f" connection type '{connection_type}'"
                    )
                    continue

            # Store the validated config
            self._server_configs[name] = config
            logger.info(
                f"Prepared MCP server config: {name} with type:"
                f" {connection_type}"
            )

    def _run_event_loop(self):
        """Runs the asyncio event loop in a separate thread."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        except Exception as e:
            logger.error(f"Error in MCP client event loop: {e}", exc_info=True)
        finally:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            logger.info("MCP Client event loop stopped")

    def _create_strategy(
        self, name: str, config: Dict[str, Any]
    ) -> Optional[MCPStrategyBase]:
        """
        Create a strategy instance for the given server configuration.

        Args:
            name: Server name
            config: Server configuration

        Returns:
            Strategy instance or None if creation fails
        """
        if not self._loop:
            logger.error("Event loop not available for creating strategy")
            return None

        connection_type = config.get("connection_type", "stdio_mcp_lib")
        strategy_class = self._strategy_classes.get(connection_type)

        if not strategy_class:
            logger.warning(
                "No strategy class found for connection type"
                f" '{connection_type}'"
            )
            return None

        try:
            # Check if we have a dynamic auth token for this server
            if (
                connection_type == "http_bearer"
                and name in self._dynamic_auth_tokens
                and "authentication" in config
            ):
                # Create a copy of the config to avoid modifying the original
                config_copy = dict(config)
                auth_config = dict(config_copy.get("authentication", {}))
                auth_config["token"] = self._dynamic_auth_tokens[name]
                config_copy["authentication"] = auth_config
                config = config_copy

            # Create the strategy instance
            strategy = strategy_class(name, config, self._loop)
            return strategy
        except Exception as e:
            logger.error(
                f"Error creating strategy for server '{name}': {e}",
                exc_info=True,
            )
            return None

    async def _connect_and_discover_single_server(
        self, name: str, strategy: MCPStrategyBase
    ) -> Tuple[str, Union[List[MCPTool], Exception]]:
        """
        Connect to a single server and discover its tools.
        Returns a tuple of (server_name, tools_list_or_exception).

        Args:
            name: Server name
            strategy: Strategy instance

        Returns:
            Tuple of (server_name, tools_list_or_exception)
        """
        try:
            if not self._exit_stack:
                raise RuntimeError("AsyncExitStack not initialized")

            # Connect using the strategy
            await strategy.connect(self._exit_stack)

            # Discover tools
            tools = await strategy.list_tools()
            return (name, tools)

        except Exception as e:
            logger.error(
                "Error connecting to or discovering tools for MCP server"
                f" '{name}': {e}",
                exc_info=True,
            )
            return (name, e)

    async def _manager_coro(self, discovery_future: concurrent.futures.Future):
        """
        Long-running coroutine that manages connection, discovery, and shutdown.
        """
        try:
            # Part 1: Connect and Discover
            self._exit_stack = AsyncExitStack()
            connect_tasks = []
            temp_strategies = {}

            for name, config in self._server_configs.items():
                try:
                    strategy = self._create_strategy(name, config)
                    if strategy:
                        temp_strategies[name] = strategy
                        connect_tasks.append(
                            self._connect_and_discover_single_server(
                                name, strategy
                            )
                        )
                except Exception as e:
                    logger.error(
                        f"Error creating strategy for server '{name}': {e}",
                        exc_info=True,
                    )

            results = await asyncio.gather(
                *connect_tasks, return_exceptions=True
            )

            temp_tools = []
            for result in results:
                if isinstance(result, tuple) and len(result) == 2:
                    s_name, tools_or_exc = result
                    if isinstance(tools_or_exc, Exception):
                        logger.error(
                            "Failed to connect/discover for MCP server"
                            f" '{s_name}': {tools_or_exc}"
                        )
                        if s_name in temp_strategies:
                            del temp_strategies[s_name]
                    elif isinstance(tools_or_exc, list):
                        temp_tools.extend(tools_or_exc)
                        logger.info(
                            f"Connected to MCP server '{s_name}' and"
                            f" discovered {len(tools_or_exc)} tools"
                        )
                else:
                    logger.error(f"Unexpected result from task: {result}")

            with self._lock:
                self._strategies = temp_strategies
                self._tools = temp_tools

            if not discovery_future.done():
                discovery_future.set_result(self._tools)

            # Part 2: Wait for shutdown signal
            self._shutdown_event = asyncio.Event()
            await self._shutdown_event.wait()

        except asyncio.CancelledError:
            logger.info("MCP manager coroutine is being cancelled.")
            # Re-raise to allow proper cleanup
            raise
        except Exception as e:
            logger.error(f"Error in MCP manager lifecycle: {e}", exc_info=True)
            if not discovery_future.done():
                discovery_future.set_exception(e)
        finally:
            # Part 3: Shutdown - ensure this happens in the same task
            logger.info("Shutting down MCP client connections...")
            try:
                if self._exit_stack:
                    await self._exit_stack.aclose()
                    self._exit_stack = None
            except Exception as e:
                # Log but don't re-raise during cleanup
                logger.debug(f"Error during exit stack cleanup: {e}")

            with self._lock:
                self._strategies.clear()
                self._tools.clear()
            logger.info("MCP client connections closed")

    def connect_and_discover(self) -> List[MCPTool]:
        """
        Start the manager coroutine, connect to servers, and discover tools.

        Returns:
            List of discovered MCPTool objects
        """
        if not self._server_configs:
            logger.info("No enabled MCP servers configured")
            return []

        with self._lock:
            if self._manager_future and not self._manager_future.done():
                logger.info(
                    "MCP manager already running. Returning existing tools."
                )
                return list(self._tools)

            if self._thread is None or not self._thread.is_alive():
                logger.info("Starting MCP client event loop thread")
                self._thread = threading.Thread(
                    target=self._run_event_loop, daemon=True
                )
                self._thread.start()
                time.sleep(0.1)

            if not self._loop:
                logger.error("MCP event loop failed to start")
                return []

            discovery_future = concurrent.futures.Future()
            self._manager_future = asyncio.run_coroutine_threadsafe(
                self._manager_coro(discovery_future), self._loop
            )

        try:
            discovered_tools = discovery_future.result(timeout=60)
            logger.info(
                f"MCP discovery complete. Found {len(discovered_tools)} tools"
            )
            return discovered_tools
        except Exception as e:
            logger.error(
                f"Error during MCP connection/discovery: {e}", exc_info=True
            )
            if self._manager_future and not self._manager_future.done():
                self._manager_future.cancel()
            return []

    def get_discovered_tools(self) -> List[MCPTool]:
        """
        Get the list of discovered tools (thread-safe).

        Returns:
            List of MCPTool objects
        """
        with self._lock:
            return list(self._tools)  # Return a copy

    def set_auth_token_for_server(self, server_name: str, token: str) -> bool:
        """
        Set or update the authentication token for a server.
        This is useful for dynamically updating tokens after initial connection.

        Args:
            server_name: Name of the server
            token: Authentication token

        Returns:
            True if the token was set, False otherwise
        """
        # Store the token for future connections
        with self._lock:
            self._dynamic_auth_tokens[server_name] = token
            strategy = self._strategies.get(server_name)

        # If the strategy is already active, update its token
        if strategy:
            # Run the async update in the event loop thread
            if self._loop and self._loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    strategy.update_auth_token(token), self._loop
                )
                try:
                    future.result(timeout=10)
                    logger.info(
                        "Updated auth token for active MCP server:"
                        f" {server_name}"
                    )
                    return True
                except Exception as e:
                    logger.error(
                        "Error updating auth token for MCP server"
                        f" '{server_name}': {e}",
                        exc_info=True,
                    )
                    if future and not future.done():
                        future.cancel()
                    return False
            else:
                logger.warning(
                    "Event loop not running, cannot update token for"
                    f" '{server_name}'"
                )
                return False
        else:
            logger.info(
                f"No active strategy for server '{server_name}'. Token stored"
                " for future connection"
            )
            return True

    def execute_tool(
        self, prefixed_tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """
        Execute a tool by its prefixed name.

        Args:
            prefixed_tool_name: Prefixed name of the tool to execute
            arguments: Arguments to pass to the tool

        Returns:
            Result of the tool execution

        Raises:
            MCPToolExecutionError: If tool execution fails
        """
        if not self._loop or not self._loop.is_running():
            raise MCPToolExecutionError("MCP client event loop is not running")

        # Find the tool by its prefixed name
        target_tool: Optional[MCPTool] = None
        server_name: Optional[str] = None
        original_tool_name: Optional[str] = None

        with self._lock:
            for tool in self._tools:
                if tool.prefixed_name == prefixed_tool_name:
                    target_tool = tool
                    server_name = tool.server_name
                    original_tool_name = tool.name
                    break

        if not target_tool:
            raise MCPToolExecutionError(
                f"MCP tool '{prefixed_tool_name}' not found"
            )

        # Get the strategy for the tool's server
        strategy = None
        with self._lock:
            strategy = self._strategies.get(server_name)

        if not strategy:
            raise MCPToolExecutionError(
                f"No active strategy found for MCP server '{server_name}'. Is"
                " it connected?"
            )

        # Run the async execution logic within the event loop thread
        future = asyncio.run_coroutine_threadsafe(
            strategy.call_tool(original_tool_name, arguments),
            self._loop,
        )
        try:
            # Wait for the execution to complete
            result = future.result(timeout=120)  # Adjust timeout as needed
            return result
        except Exception as e:
            logger.error(
                f"Error waiting for MCP tool execution result: {e}",
                exc_info=True,
            )
            if future and not future.done():
                future.cancel()
            raise MCPToolExecutionError(
                f"Failed to execute tool '{prefixed_tool_name}': {str(e)}"
            ) from e

    def shutdown(self):
        """Shut down connections and stop the event loop thread."""
        logger.info("Initiating MCP Client Manager shutdown...")

        # First, check if we have an active manager
        if not self._manager_future or self._manager_future.done():
            logger.info("No active MCP manager to shut down")
            return

        if self._loop and self._loop.is_running():
            # Instead of setting the shutdown event directly, schedule it in the loop
            if self._shutdown_event:
                # Signal shutdown in the correct thread
                self._loop.call_soon_threadsafe(self._shutdown_event.set)

                # Wait for the manager coroutine to complete its cleanup
                try:
                    # Don't wait for the result directly, as this causes the context issue
                    # Instead, just wait for the future to be done
                    self._manager_future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    logger.warning("MCP manager shutdown timed out")
                    # Cancel the future if it's still running
                    self._manager_future.cancel()
                except Exception as e:
                    # Log but don't re-raise, as the error is likely the context issue
                    logger.debug(
                        f"Expected error during MCP manager shutdown: {e}"
                    )

            # Stop the event loop
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            logger.info("Waiting for MCP client thread to terminate...")
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning(
                    "MCP client thread did not terminate gracefully"
                )

        # Clear references
        with self._lock:
            self._strategies.clear()
            self._tools.clear()

        self._loop = None
        self._thread = None
        self._manager_future = None
        self._shutdown_event = None
        logger.info("MCP Client Manager shutdown complete")
