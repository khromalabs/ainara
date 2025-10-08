import asyncio
import logging
import os
from typing import Any, Dict, Optional

import pynvim


class NeovimConnectionError(Exception):
    """Custom exception for Neovim connection errors."""

    pass


class NeovimClient:
    """
    A client for interacting with Neovim via the remote API.
    """

    def __init__(self):
        self.nvim = None
        self.logger = logging.getLogger(__name__)

    async def _connect(self):
        """Establishes a connection to the Neovim instance."""
        try:
            # Prefer NVIM_LISTEN_ADDRESS if available, otherwise fallback
            server_address = os.environ.get(
                "NVIM_LISTEN_ADDRESS"
            ) or os.environ.get("NVIM_SERVER")
            if server_address:
                self.nvim = await asyncio.to_thread(
                    pynvim.attach, "socket", path=server_address
                )
            else:
                # Fallback for manual setup, e.g., nvim --listen /tmp/nvim
                self.nvim = await asyncio.to_thread(
                    pynvim.attach, "socket", path="/tmp/nvim"
                )

            # Test connection to fail fast
            await asyncio.to_thread(self.nvim.api.get_current_buf)
            self.logger.info("Successfully connected to Neovim")
        except (ConnectionRefusedError, FileNotFoundError):
            self.nvim = None
            raise NeovimConnectionError(
                "Could not connect to Neovim. Is it running with a listen socket?"
            )
        except Exception as e:
            self.nvim = None
            raise NeovimConnectionError(
                f"An unexpected error occurred while connecting to Neovim: {e}"
            )

    async def _ensure_connected(self):
        """Ensures there is an active connection to Neovim, creating one if necessary."""
        if self.nvim:
            try:
                # Ping nvim to check if the connection is still alive
                await asyncio.to_thread(self.nvim.api.get_current_buf)
                return
            except (pynvim.api.nvim.NvimError, BrokenPipeError, OSError):
                self.logger.warning("Neovim connection lost. Reconnecting...")
                self.nvim = None

        await self._connect()

    async def get_context(self) -> Dict[str, Any]:
        """
        Gets the current file path, cursor position, and identifier under cursor.
        """
        try:
            await self._ensure_connected()
            # Get current file path
            file_path = await asyncio.to_thread(self.nvim.eval, "expand('%:p')")
            # Get word under cursor (simplified - could be enhanced)
            identifier = await asyncio.to_thread(
                self.nvim.eval, "expand('<cword>')"
            )
            # Get cursor position (1-based line, 0-based column)
            cursor_pos = await asyncio.to_thread(self.nvim.api.win_get_cursor, 0)
            return {
                "file_path": file_path,
                "identifier": identifier,
                "cursor_line": cursor_pos[0],
                "cursor_col": cursor_pos[1],
            }
        except NeovimConnectionError:
            raise  # Re-raise our custom connection error
        except Exception as e:
            # Wrap other potential errors in our custom exception for consistent handling
            raise NeovimConnectionError(
                f"Failed to get context from Neovim: {e}"
            ) from e

    async def get_buffer_content(self) -> str:
        """Gets the entire content of the current buffer."""
        try:
            await self._ensure_connected()
            buffer = await asyncio.to_thread(self.nvim.api.get_current_buf)
            lines = await asyncio.to_thread(
                self.nvim.api.buf_get_lines, buffer, 0, -1, True
            )
            return "\n".join(lines)
        except NeovimConnectionError:
            raise
        except Exception as e:
            raise NeovimConnectionError(
                f"Failed to get buffer content from Neovim: {e}"
            ) from e

    async def set_buffer_content(self, content: str) -> None:
        """Replaces the entire content of the current buffer."""
        try:
            await self._ensure_connected()
            buffer = await asyncio.to_thread(self.nvim.api.get_current_buf)
            lines = content.splitlines()
            await asyncio.to_thread(
                self.nvim.api.buf_set_lines, buffer, 0, -1, True, lines
            )
        except NeovimConnectionError:
            raise
        except Exception as e:
            raise NeovimConnectionError(
                f"Failed to set buffer content in Neovim: {e}"
            ) from e
