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


import shutil
from pathlib import Path
from typing import Annotated, Any, Dict, Literal, Optional, Union

from ainara.framework.skill import Skill


class SystemFileop(Skill):
    """Perform file operations in the local system as file read, list or exists"""

    matcher_info = (
        "Use this skill when the user wants to perform file operations on the"
        " local system, such as reading file contents, listing directory"
        " contents, or checking if a file or directory exists. This skill can"
        " handle basic file system interactions but not complex searches or"
        " modifications. Examples include: 'read the content of notes.txt',"
        " 'list files in Documents folder', 'does config.json exist', 'show"
        " directory contents of Downloads'.\n\nKeywords: file, read, list,"
        " exists, check, directory, folder, content, system, local, path."
    )

    def __init__(self):
        super().__init__()

    async def run(
        self,
        operation: Annotated[
            Literal["read", "list", "exists"],
            "The operation to perform (read, list, exists)",
        ],
        path: Annotated[Union[str, Path], "Path to the file or directory"],
        content: Annotated[
            Optional[str], "Content to write to file (for write operation)"
        ] = None,
        recursive: Annotated[
            Optional[bool],
            "Whether to operate recursively (for delete/list operations)",
        ] = None,
        pattern: Annotated[
            Optional[str], "File pattern to match (for find operation)"
        ] = None,
        case_sensitive: Annotated[
            Optional[bool],
            "Whether pattern matching is case sensitive (for find operation)",
        ] = None,
    ) -> Dict[str, Any]:
        """Perform file system operations"""
        path = Path(path)

        operations = {
            "read": self._read_file,
            "list": self._list_directory,
            "exists": self._check_exists,
        }
        #            "write": self._write_file,
        #            "delete": self._delete_file,
        #            "find": self._find_files,

        if operation not in operations:
            raise ValueError(f"Unsupported operation: {operation}")

        # Create kwargs dictionary from explicit parameters
        kwargs = {}
        if content is not None:
            kwargs["content"] = content
        if recursive is not None:
            kwargs["recursive"] = recursive
        if pattern is not None:
            kwargs["pattern"] = pattern
        if case_sensitive is not None:
            kwargs["case_sensitive"] = case_sensitive

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
