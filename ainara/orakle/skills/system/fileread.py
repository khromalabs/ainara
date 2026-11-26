# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
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

from pathlib import Path
from typing import Annotated, Any, Dict, Optional, Union

from ainara.framework.skill import Skill


class SystemFileread(Skill):
    """Read the contents of one specific file, given its exact path.

    Returns a slice of the file: large files are capped per call and the
    response carries total_lines and next_offset so remaining parts can
    be requested with offset/limit. This is a single-file, single-call
    skill: it neither searches directory trees (use the file scanner
    skill) nor locates files by name or attributes (use the file finder
    skill). It is read-only: it never modifies files.
    """

    matcher_info = (
        "Read the contents of a specific file given its exact path, paged"
        " for large files: the response includes total_lines and"
        " next_offset so remaining slices can be requested with"
        " offset/limit. Operates on one known path only; it does not"
        " search or analyze directory trees and does not locate files by"
        " name. Examples include: 'read the content of notes.txt', 'read"
        " lines 400-500 of main.py', 'show me what is inside config.yaml',"
        " 'continue reading that file from line 600'. Keywords: read,"
        " file, content, contents, open, show, text, lines, page, offset,"
        " path, local, system."
    )

    embeddings_boost_factor = 2

    # Read result caps, mirroring the convention used by coding agents:
    # at most 2000 lines or 50KB per call, whichever is hit first.
    READ_MAX_LINES = 2000
    READ_MAX_BYTES = 50_000

    def __init__(self):
        super().__init__()

    async def run(
        self,
        path: Annotated[
            Union[str, Path], "Exact path to the file to read"
        ],
        offset: Annotated[
            Optional[int],
            "First line to return, 1-based. Combine with limit to page"
            " through a large file using next_offset",
        ] = None,
        limit: Annotated[
            Optional[int],
            "Maximum number of lines to return (capped at 2000 lines /"
            " 50KB per call)",
        ] = None,
    ) -> Dict[str, Any]:
        """Read a slice of a file's contents, capped and with paging metadata"""
        return await self._read_file(Path(path), offset=offset, limit=limit)

    async def _read_file(self, path: Path, **kwargs) -> Dict[str, Any]:
        """Read a slice of file contents, capped and with paging metadata"""
        if not path.is_file():
            return {"success": False, "error": "File does not exist"}

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            total_lines = len(lines)

            offset = max(1, int(kwargs.get("offset") or 1))
            limit = min(
                max(1, int(kwargs.get("limit") or self.READ_MAX_LINES)),
                self.READ_MAX_LINES,
            )

            out_lines: list = []
            size = 0
            byte_capped = False
            for line in lines[offset - 1:offset - 1 + limit]:
                encoded = line.encode("utf-8")
                if size + len(encoded) + 1 > self.READ_MAX_BYTES:
                    byte_capped = True
                    break
                out_lines.append(line)
                size += len(encoded) + 1

            lines_returned = len(out_lines)
            truncated = byte_capped or (offset - 1 + lines_returned) < total_lines
            result = {
                "success": True,
                "content": "\n".join(out_lines),
                "total_lines": total_lines,
                "offset": offset,
                "lines_returned": lines_returned,
                "truncated": truncated,
            }
            if truncated:
                result["next_offset"] = offset + lines_returned
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}
