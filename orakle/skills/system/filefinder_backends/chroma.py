# orakle/skills/system/filefinder_backends/chroma.py
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
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from ainara.framework.documents.indexer import DocumentIndexManager
from ainara.framework.documents.search import DocumentSearch

from .base import SearchBackend, SearchResult

logger = logging.getLogger(__name__)


class ChromaBackend(SearchBackend):
    """Chroma-based semantic search backend using the document indexing system"""

    def __init__(self):
        self.index_manager = None
        self.search = None
        self.initialized = False

    def initialize(self) -> bool:
        """Initialize the Chroma search backend"""
        try:
            self.index_manager = DocumentIndexManager()
            self.search = DocumentSearch(self.index_manager)
            self.index_manager.start()
            self.initialized = True
            logger.info("Chroma search backend initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Chroma search backend: {e}", exc_info=True)
            self.index_manager = None
            self.search = None
            self.initialized = False
            return False

    def is_available(self) -> bool:
        """Check if Chroma backend is available"""
        try:
            # Try to import required modules to check availability
            import chromadb
            return True
        except ImportError:
            return False

    async def search(
        self,
        params: Dict[str, Any],
        limit: int = 5
    ) -> List[SearchResult]:
        """Perform semantic search using Chroma backend"""
        if not self.initialized or not self.search:
            logger.error("Chroma backend not initialized")
            return []

        try:
            # Extract search parameters
            query = " ".join(params.get("content", []))
            if not query:
                # If no content specified, use any available text
                query = params.get("query", "")

            # Map file_types to extensions if present
            file_types = None
            if "file_types" in params:
                file_types = []
                type_mapping = {
                    "document": ["pdf", "docx", "doc", "txt", "md", "rtf"],
                    "spreadsheet": ["xlsx", "xls", "csv"],
                    "presentation": ["pptx", "ppt"],
                    "image": ["jpg", "jpeg", "png", "gif", "bmp"],
                    "video": ["mp4", "avi", "mov", "wmv"],
                    "audio": ["mp3", "wav", "ogg", "flac"],
                    "code": ["py", "js", "java", "c", "cpp", "html", "css"]
                }

                for file_type in params["file_types"]:
                    if file_type.lower() in type_mapping:
                        file_types.extend(type_mapping[file_type.lower()])
                    else:
                        # If not a category, assume it's an extension
                        file_types.append(file_type.lower())

            # Extract directories if specified
            directories = None
            if "locations" in params:
                directories = params["locations"]

            # Extract time frame for recency filter
            recency = None
            if "time_frame" in params:
                time_frame = params["time_frame"]
                if time_frame["type"] == "relative":
                    value = time_frame["value"].lower()
                    if "today" in value:
                        recency = "today"
                    elif "week" in value:
                        recency = "this week"
                    elif "month" in value:
                        recency = "this month"
                    elif "year" in value:
                        recency = "this year"

            # Perform search using DocumentSearch
            results = await self.search.search(
                query=query,
                limit=limit,
                file_types=file_types,
                directories=directories,
                recency=recency
            )

            # Convert to SearchResult objects
            search_results = []
            for result in results.get("results", []):
                path = Path(result["path"])

                # Create SearchResult object
                search_result = SearchResult(
                    path=path,
                    name=path.name,
                    type=path.suffix.lstrip('.'),
                    size=result.get("size", 0),
                    created=datetime.fromtimestamp(result.get("created", 0)),
                    modified=datetime.fromtimestamp(result.get("modified", 0)),
                    snippet=result.get("snippet", ""),
                    metadata=result.get("metadata", {}),
                    score=result.get("score", 0.0)
                )
                search_results.append(search_result)

            return search_results

        except Exception as e:
            logger.error(f"Error searching with Chroma backend: {e}", exc_info=True)
            return []
