# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

import shutil
from pathlib import Path
from typing import Any, Dict, Union

from ainara.framework.skill import Skill


class SystemFile(Skill):
    """Skill for file system operations"""

    def __init__(self):
        super().__init__()

    async def run(
        self, operation: str, path: Union[str, Path], **kwargs
    ) -> Dict[str, Any]:
        """
        Perform file system operations

        Args:
            operation: The operation to perform
            ('read', 'write', 'delete', 'list', 'exists', 'find')
            path: Path to the file or directory
            **kwargs: Additional arguments specific to each operation
                     - content: str (for write operation)
                     - recursive: bool (for delete/list operations)
                     - pattern: str (for find operation)
                     - case_sensitive: bool (for find operation)

        Returns:
            Dict containing operation results
        """
        path = Path(path)

        operations = {
            "read": self._read_file,
            "write": self._write_file,
            "delete": self._delete_file,
            "list": self._list_directory,
            "exists": self._check_exists,
            "find": self._find_files,
        }

        if operation not in operations:
            raise ValueError(f"Unsupported operation: {operation}")

        return await operations[operation](path, **kwargs)

    async def _read_file(self, path: Path, **kwargs) -> Dict[str, Any]:
        """Read file contents"""
        if not path.is_file():
            return {"success": False, "error": "File does not exist"}

        try:
            content = path.read_text()
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _write_file(self, path: Path, **kwargs) -> Dict[str, Any]:
        """Write content to file"""
        content = kwargs.get("content")
        if content is None:
            return {"success": False, "error": "No content provided"}

        try:
            path.write_text(content)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _delete_file(self, path: Path, **kwargs) -> Dict[str, Any]:
        """Delete file or directory"""
        if not path.exists():
            return {"success": False, "error": "Path does not exist"}

        try:
            if path.is_file():
                path.unlink()
            else:
                recursive = kwargs.get("recursive", False)
                if recursive:
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _list_directory(self, path: Path, **kwargs) -> Dict[str, Any]:
        """List directory contents"""
        if not path.is_dir():
            return {"success": False, "error": "Path is not a directory"}

        try:
            recursive = kwargs.get("recursive", False)
            if recursive:
                files = list(path.rglob("*"))
            else:
                files = list(path.glob("*"))

            return {
                "success": True,
                "files": [str(f.relative_to(path)) for f in files],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _check_exists(self, path: Path, **kwargs) -> Dict[str, Any]:
        """Check if file or directory exists"""
        return {
            "success": True,
            "exists": path.exists(),
            "is_file": path.is_file() if path.exists() else None,
            "is_dir": path.is_dir() if path.exists() else None,
        }

    async def _find_files(self, path: Path, **kwargs) -> Dict[str, Any]:
        """Find files matching a pattern"""
        if not path.exists():
            return {"success": False, "error": "Path does not exist"}

        try:
            pattern = kwargs.get("pattern", "*")
            case_sensitive = kwargs.get("case_sensitive", True)

            if not case_sensitive:
                # For case-insensitive search, convert pattern to regex
                import re

                pattern = "".join(
                    f"[{c.lower()}{c.upper()}]" if c.isalpha() else c
                    for c in pattern
                )
                matches = []
                for f in path.rglob("*"):
                    if re.search(pattern, f.name):
                        matches.append(str(f.relative_to(path)))
            else:
                matches = [
                    str(f.relative_to(path)) for f in path.rglob(pattern)
                ]

            return {"success": True, "matches": matches, "count": len(matches)}
        except Exception as e:
            return {"success": False, "error": str(e)}
