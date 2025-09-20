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


import logging
import fnmatch
import mimetypes
from datetime import datetime
import os
import stat
from pathlib import Path
from typing import Any, Dict, List

from ainara.framework.config import config
from ainara.framework.logging_setup import logging_manager

from .base import SearchBackend, SearchResult

logger = logging_manager.logger


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
                    home,
                    # home / "Documents",
                    # home / "Downloads",
                    # home / "Desktop",
                ]

            # logger.info(f"paths: {paths}")
            self.watch_paths = [Path(p).expanduser() for p in paths]
            # logger.info(f"self.watch_paths: {self.watch_paths}")
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

                for root, dirs, files in os.walk(path):
                    # Exclude hidden directories from traversal
                    dirs[:] = [
                        d for d in dirs if not self._is_hidden(Path(root) / d)
                    ]

                    for pattern in patterns or ["*"]:
                        for filename in fnmatch.filter(files, pattern):
                            file_path = Path(root) / filename
                            # Exclude hidden files
                            if self._is_hidden(file_path):
                                continue
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

                    if len(results) >= limit:
                        break

            return sorted(results, key=lambda r: r.modified, reverse=True)[
                :limit
            ]

        except Exception as e:
            logging.error(f"Custom search error: {e}")
            return []

    def _is_hidden(self, path: Path) -> bool:
        """Check if a file or directory is hidden in a cross-platform way."""
        # Unix-like systems and convention: check for leading dot
        if path.name.startswith("."):
            return True
        # Windows: check for the 'hidden' file attribute
        if os.name == "nt":
            try:
                attrs = path.stat().st_file_attributes
                if attrs & stat.FILE_ATTRIBUTE_HIDDEN:
                    return True
            except (OSError, AttributeError):
                # Handle cases where stat fails or attribute doesn't exist
                pass
        return False

    def _get_patterns(self, file_types: List[str]) -> List[str]:
        """Convert file types to glob patterns"""
        patterns = []
        for ft in file_types:
            if ft == "document" or ft == "report":
                patterns.extend(["*.pdf", "*.doc", "*.docx", "*.txt", "*.md"])
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

            # logger.info(f"params: {params}")

            # Check content keywords (filename and content)
            if content := params.get("content"):
                name_lower = file_path.name.lower()
                # logger.info(f"name_lower: {name_lower}")
                # logger.info(f"content: {content}")
                return all(
                    word.lower() in name_lower
                    for phrase in content
                    for word in phrase.split()
                )

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
