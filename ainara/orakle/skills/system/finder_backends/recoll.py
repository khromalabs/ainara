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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .base import SearchBackend, SearchResult


class RecollBackend(SearchBackend):
    """Recoll-based search backend"""

    def __init__(self):
        self.db = None
        self.indexer = None

    def initialize(self) -> bool:
        try:
            logging.debug("Attempting to import recoll._recoll...")
            import recoll._recoll as recoll
            logging.debug("Successfully imported recoll._recoll")

            logging.debug("Attempting to connect to Recoll DB...")
            self.db = recoll.connect()
            logging.debug("Successfully connected to Recoll DB")
            return True
        except Exception as e:
            logging.error(f"Failed to initialize Recoll: {e}")
            logging.debug(f"Recoll initialization error details:", exc_info=True)
            return False

    def is_available(self) -> bool:
        try:
            import recoll._recoll as recoll

            self.db = recoll.connect()
            return True
        except ImportError:
            return False

    async def search(
        self, params: Dict[str, Any], limit: int = 5
    ) -> List[SearchResult]:
        if not self.db:
            logging.error("Recoll DB not initialized")
            return []

        try:
            logging.debug(f"Search params received: {params}")
            # Build Recoll query from params
            query_parts = []

            # Add file type filters
            if file_types := params.get("file_types"):
                type_queries = [self._get_mime_type(ft) for ft in file_types]
                mime_query = " OR ".join(f"mime:{q}" for q in type_queries)
                query_parts.append(mime_query)

            # Add time frame
            if time_frame := params.get("time_frame"):
                date_query = self._build_date_query(time_frame)
                if date_query:
                    query_parts.append(date_query)

            # Add content keywords
            if content := params.get("content"):
                content_string = " OR ".join(content)
                if content_string:
                    query_parts.append(content_string)

            # Combine all parts with AND
            query_string = " AND ".join(f"{part}" for part in query_parts if part)
            
            logging.debug(f"Query construction:")
            logging.debug(f"  File types: {file_types}")
            logging.debug(f"  Time frame: {time_frame}")
            logging.debug(f"  Content: {content}")
            logging.debug(f"  Query parts: {query_parts}")
            logging.debug(f"  Final query: {query_string}")

            # Execute search
            query = self.db.query()
            logging.debug("Created query object")
            query.execute(query_string)
            logging.debug(f"Query executed, found {query.rowcount} results")

            results = []
            result_count = min(limit, query.rowcount)
            logging.debug(f"Fetching up to {result_count} results")
            for i in range(result_count):
                doc = query.fetchone()
                logging.debug(f"Result {i+1}: {doc.url}")
                logging.debug(f"Document attributes:")
                logging.debug(f"  URL: {doc.url}")
                logging.debug(f"  Filename: {doc.filename}")
                logging.debug(f"  Type: {doc.mtype}")
                logging.debug(f"  Size: {type(doc.dbytes)} - {doc.dbytes}")
                logging.debug(f"  Created: {type(doc.fmtime)} - {doc.fmtime}")
                logging.debug(f"  Modified: {type(doc.dmtime)} - {doc.dmtime}")
                logging.debug(f"  Rating: {type(doc.relevancyrating)} - {doc.relevancyrating}")
                
                try:
                    results.append(
                        SearchResult(
                            path=str(Path(doc.url)),
                            name=doc.filename,
                            type=doc.mtype,
                            size=int(doc.dbytes) if doc.dbytes and isinstance(doc.dbytes, str) else (doc.dbytes or 0),
                            created=datetime.fromtimestamp(int(doc.fmtime) if doc.fmtime and isinstance(doc.fmtime, str) else (doc.fmtime or 0)),
                            modified=datetime.fromtimestamp(int(doc.dmtime) if doc.dmtime and isinstance(doc.dmtime, str) else (doc.dmtime or 0)),
                            snippet=doc.snippet,
                            metadata={
                                "author": doc.author,
                                "title": doc.title,
                                "abstract": doc.abstract,
                            },
                            score=float(doc.relevancyrating.rstrip('%'))/100.0 if isinstance(doc.relevancyrating, str) and '%' in doc.relevancyrating 
                                  else (float(doc.relevancyrating) if doc.relevancyrating else 0.0),
                        )
                    )
                except Exception as e:
                    logging.error(f"Error creating SearchResult: {e}")
                    logging.debug("Error details:", exc_info=True)
            return results

        except Exception as e:
            logging.error(f"Recoll search error: {e}")
            return []

    def _get_mime_type(self, file_type: str) -> str:
        """Convert generic file type to MIME type"""
        mime_types = {
            "document": (
                "application/pdf OR application/msword OR"
                " application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "spreadsheet": (
                "application/vnd.ms-excel OR"
                " application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            "presentation": (
                "application/vnd.ms-powerpoint OR"
                " application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
            "image": "image/*",
            "video": "video/*",
            "audio": "audio/*",
            "pdf": "application/pdf",
        }
        return mime_types.get(file_type, file_type)

    def _build_date_query(self, time_frame: Dict[str, Any]) -> str:
        """Build date range query"""
        if time_frame["type"] == "relative":
            # Handle relative dates (today, yesterday, last week, etc.)
            ranges = {
                "today": "date:today",
                "yesterday": "date:yesterday",
                "this_week": "date:thisweek",
                "last_week": "date:lastweek",
                "this_month": "date:thismonth",
                "last_month": "date:lastmonth",
            }
            return ranges.get(time_frame["value"], "")
        else:
            # Handle exact date range
            value = str(time_frame["value"])
            
            # If it's just a year
            if value.isdigit() and len(value) == 4:
                # Use broader date range to catch more potential matches
                year = int(value)
                # Include previous and next year in search
                start_year = year - 1
                end_year = year + 1
                return f"date:{start_year}-06-01/{end_year}-06-30"
            
            # For other date formats
            return f"date:{value}"