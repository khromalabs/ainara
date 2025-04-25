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

"""Skill for interacting with the system clipboard"""

import logging
from typing import Annotated, Any, Dict, Literal, Optional

import pyperclip

from ainara.framework.skill import Skill


class SystemClipboard(Skill):
    """Read and write the system clipboard"""

    matcher_info = (
        "Use this skill when the user wants to interact with the system"
        " clipboard, including reading, writing, or clearing clipboard"
        " contents. This skill can handle operations related to copying text"
        " or data to and from the clipboard. Examples include: 'read clipboard"
        " content', 'copy this text to clipboard', 'clear my clipboard', 'what"
        " is in my clipboard'. \n\nKeywords: clipboard, copy, paste, read,"
        " write, clear, content, text, data."
    )

    def __init__(self):
        super().__init__()
        self._check_clipboard_available()

    def _check_clipboard_available(self) -> None:
        """Verify clipboard access is available"""
        try:
            pyperclip.paste()
        except pyperclip.PyperclipException as e:
            raise RuntimeError(f"Clipboard access failed: {str(e)}")

    async def read_clipboard(self) -> Dict[str, Any]:
        """
        Read current contents of system clipboard

        Returns:
            Dict containing:
                success (bool): Whether operation succeeded
                contents (str): Clipboard contents if successful
                error (str): Error message if failed
        """
        try:
            contents = pyperclip.paste()
            return {"success": True, "contents": contents}
        except Exception as e:
            logging.error(f"Failed to read clipboard: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to read clipboard: {str(e)}",
            }

    async def write_clipboard(self, text: str) -> Dict[str, Any]:
        """
        Write text to system clipboard

        Args:
            text: Content to write to clipboard

        Returns:
            Dict containing:
                success (bool): Whether operation succeeded
                error (str): Error message if failed
        """
        if not isinstance(text, str):
            return {
                "success": False,
                "error": "Clipboard content must be string",
            }

        try:
            pyperclip.copy(text)
            return {"success": True}
        except Exception as e:
            logging.error(f"Failed to write to clipboard: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to write to clipboard: {str(e)}",
            }

    async def clear_clipboard(self) -> Dict[str, Any]:
        """
        Clear clipboard contents

        Returns:
            Dict containing:
                success (bool): Whether operation succeeded
                error (str): Error message if failed
        """
        return await self.write_clipboard("")

    async def run(
        self,
        action: Annotated[
            Literal["read", "write", "clear"],
            "Operation to perform (read, write, or clear)",
        ],
        text: Annotated[
            Optional[str], "Text to write (required for 'write' action)"
        ] = None,
    ) -> Dict[str, Any]:
        """Reads and writes to the system clipboard"""
        action = action.lower()

        if action not in ("read", "write", "clear"):
            return {
                "success": False,
                "error": (
                    f"Invalid action '{action}'. Must be 'read', 'write' or"
                    " 'clear'"
                ),
            }

        if action == "read":
            return await self.read_clipboard()
        elif action == "write":
            if text is None:
                return {
                    "success": False,
                    "error": "Text parameter required for write action",
                }
            return await self.write_clipboard(text)
        else:  # clear
            return await self.clear_clipboard()
