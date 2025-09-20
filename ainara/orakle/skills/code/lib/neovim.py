import asyncio
import logging
import os
from typing import Any, Dict, Optional

try:
    import pynvim
    from pynvim import NvimError
except ImportError:
    pynvim = None
    NvimError = Exception


class NeovimClient:
    """
    A client for interacting with Neovim via the remote API.
    """

    def __init__(self):
        self.nvim = None
        self.logger = logging.getLogger(__name__)
        if pynvim:
            try:
                # Prefer NVIM_LISTEN_ADDRESS if available, otherwise fallback
                server_address = os.environ.get(
                    "NVIM_LISTEN_ADDRESS"
                ) or os.environ.get("NVIM_SERVER")
                if server_address:
                    self.nvim = pynvim.attach("socket", path=server_address)
                else:
                    # Fallback for manual setup, e.g., nvim --listen /tmp/nvim
                    self.nvim = pynvim.attach("socket", path="/tmp/nvim")
                self.logger.info("Succesfully connected to Neovim")
            except (ConnectionRefusedError, FileNotFoundError):
                self.logger.warning(
                    "Could not connect to Neovim. Is it running with a"
                    " listen socket?"
                )
            except Exception as e:
                self.logger.error(
                    "An unexpected error occurred while connecting to Neovim:"
                    f" {e}"
                )

    async def get_context(self) -> Optional[Dict[str, Any]]:
        """
        Gets the current file path, cursor position, and identifier under cursor.
        """
        if not self.nvim:
            return None
        try:
            # Get current file path
            file_path = await asyncio.to_thread(self.nvim.eval, "expand('%:p')")
            # Get word under cursor (simplified - could be enhanced)
            identifier = await asyncio.to_thread(self.nvim.eval, "expand('<cword>')")
            # Get cursor position (1-based line, 0-based column)
            cursor_pos = await asyncio.to_thread(self.nvim.api.win_get_cursor, 0)
            return {
                "file_path": file_path,
                "identifier": identifier,
                "cursor_line": cursor_pos[0],
                "cursor_col": cursor_pos[1],
            }
        except (NvimError, ConnectionRefusedError, BrokenPipeError):
            # Handle cases where nvim might have closed or there's an API error
            return None

    async def get_buffer_content(self) -> Optional[str]:
        """Gets the entire content of the current buffer."""
        if not self.nvim:
            return None
        try:
            buffer = await asyncio.to_thread(self.nvim.api.get_current_buf)
            lines = await asyncio.to_thread(
                self.nvim.api.buf_get_lines, buffer, 0, -1, True
            )
            return "\n".join(lines)
        except (NvimError, ConnectionRefusedError, BrokenPipeError):
            return None

    async def set_buffer_content(self, content: str) -> bool:
        """Replaces the entire content of the current buffer."""
        if not self.nvim:
            return False
        try:
            buffer = await asyncio.to_thread(self.nvim.api.get_current_buf)
            lines = content.splitlines()
            await asyncio.to_thread(
                self.nvim.api.buf_set_lines, buffer, 0, -1, True, lines
            )
            return True
        except (NvimError, ConnectionRefusedError, BrokenPipeError):
            return False
