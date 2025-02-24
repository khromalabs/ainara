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

import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ainara.framework.config import config

from .base import SearchBackend, SearchResult


class BackendsCustom(SearchBackend):
    """Basic file system search backend"""

    def __init__(self):
        self.watch_paths = []

    def initialize(self) -> bool:
        try:
            paths = config.get("skills.smart_finder.watch_paths", [])
            if not paths:
                # Default to common user directories
                home = Path.home()
                paths = [
                    home / "Documents",
                    home / "Downloads",
                    home / "Desktop",
                ]

            self.watch_paths = [Path(p).expanduser() for p in paths]
            return True

        except Exception as e:
            logging.error(f"Failed to initialize custom backend: {e}")
            return False

    def is_available(self) -> bool:
        return True  # Basic file system is always available

    async def search(
        self, params: Dict[str, Any], limit: int = 5
    ) -> List[SearchResult]:
        try:
            results = []

            # Get file type patterns
            file_types = params.get("file_types", [])
            patterns = self._get_patterns(file_types)

            # Search in watch paths
            for path in self.watch_paths:
                if not path.exists():
                    continue

                for pattern in patterns or ["*"]:
                    for file_path in path.rglob(pattern):
                        if not file_path.is_file():
                            continue

                        # Check if file matches criteria
                        if self._matches_criteria(file_path, params):
                            stats = file_path.stat()
                            results.append(
                                SearchResult(
                                    path=file_path,
                                    name=file_path.name,
                                    type=mimetypes.guess_type(file_path)[0]
                                    or "application/octet-stream",
                                    size=stats.st_size,
                                    created=datetime.fromtimestamp(
                                        stats.st_ctime
                                    ),
                                    modified=datetime.fromtimestamp(
                                        stats.st_mtime
                                    ),
                                    # Basic backend doesn't provide content
                                    # snippets
                                    snippet=None,
                                    metadata=None,
                                    score=1.0,
                                )
                            )

                        if len(results) >= limit:
                            break

                    if len(results) >= limit:
                        break

            return sorted(results, key=lambda r: r.modified, reverse=True)[
                :limit
            ]

        except Exception as e:
            logging.error(f"Custom search error: {e}")
            return []

    def _get_patterns(self, file_types: List[str]) -> List[str]:
        """Convert file types to glob patterns"""
        patterns = []
        for ft in file_types:
            if ft == "document":
                patterns.extend(["*.pdf", "*.doc", "*.docx", "*.txt"])
            elif ft == "spreadsheet":
                patterns.extend(["*.xls", "*.xlsx", "*.csv"])
            elif ft == "presentation":
                patterns.extend(["*.ppt", "*.pptx"])
            elif ft == "image":
                patterns.extend(["*.jpg", "*.jpeg", "*.png", "*.gif"])
            elif ft == "video":
                patterns.extend(["*.mp4", "*.avi", "*.mov"])
            elif ft == "audio":
                patterns.extend(["*.mp3", "*.wav", "*.ogg"])
        return patterns

    def _matches_criteria(
        self, file_path: Path, params: Dict[str, Any]
    ) -> bool:
        """Check if file matches search criteria"""
        try:
            stats = file_path.stat()

            # Check time frame
            if time_frame := params.get("time_frame"):
                modified = datetime.fromtimestamp(stats.st_mtime)
                if not self._matches_timeframe(modified, time_frame):
                    return False

            # Check size constraints
            if size := params.get("size"):
                file_size = stats.st_size
                if min_size := size.get("min"):
                    if file_size < self._parse_size(min_size):
                        return False
                if max_size := size.get("max"):
                    if file_size > self._parse_size(max_size):
                        return False

            # Check content keywords (basic filename match)
            if content := params.get("content"):
                name_lower = file_path.name.lower()
                if not any(k.lower() in name_lower for k in content):
                    return False

            return True

        except Exception as e:
            logging.error(f"Error checking file {file_path}: {e}")
            return False

    def _matches_timeframe(
        self, modified: datetime, time_frame: Dict[str, Any]
    ) -> bool:
        """Check if file modification time matches time frame"""
        now = datetime.now()

        if time_frame["type"] == "relative":
            if time_frame["value"] == "today":
                return modified.date() == now.date()
            elif time_frame["value"] == "yesterday":
                return (now.date() - modified.date()).days == 1
            elif time_frame["value"] == "this_week":
                return (now - modified).days <= 7
            elif time_frame["value"] == "last_week":
                return 7 < (now - modified).days <= 14

        return True

    def _parse_size(self, size_str: str) -> int:
        """Convert size string to bytes"""
        units = {
            "B": 1,
            "KB": 1024,
            "MB": 1024 * 1024,
            "GB": 1024 * 1024 * 1024,
        }

        size = float(size_str[:-2])
        unit = size_str[-2:].upper()

        return int(size * units[unit])
