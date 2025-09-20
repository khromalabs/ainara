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


import json
import logging
import platform
import subprocess
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from ainara.framework.config import config
from ainara.framework.llm import create_llm_backend
from ainara.framework.logging_setup import logging_manager
from ainara.framework.skill import Skill

from .finder_backends.base import SearchBackend, SearchResult
from .finder_backends.custom import BackendsCustom
from .finder_backends.recoll import RecollBackend

logger = logging_manager.logger


class SystemFinder(Skill):
    """Intelligent file search with LLM-assisted disambiguation and location reveal"""

    matcher_info = (
        "Use this skill when the user wants to find or search for files,"
        " documents, or folders on their system. This skill can handle queries"
        " related to locating files by name, type, content, date, size, or"
        " location.\n\nExamples include: 'find PDF files from last week',"
        " 'search for marketing presentation', 'locate budget spreadsheet in"
        " Downloads', 'show me photos from yesterday'. Don't open the file"
        " automatically unless the user requests that.Keywords: find, search,"
        " locate, file, document, folder, PDF, image, presentation,"
        " spreadsheet, recent, old, large, small, Downloads, Desktop."
    )

    def __init__(self):
        super().__init__()
        self.backend = self._initialize_backend()

        # Query parsing prompt with action detection
        self.parse_prompt = """You are a file search query parser.
Convert natural language queries into structured search parameters.
Output only valid JSON with these possible fields:
{
    "file_types": ["document", "image", etc],
    "time_frame": {"type": "relative|exact", "value": "..."},
    "authors": ["name1", "name2"],
    "size": {"min": "100MB", "max": "1GB"},
    "locations": ["downloads", "desktop"],
    "content": ["keyword1", "keyword2"],
    "sort": "date_desc|date_asc|size_desc|size_asc|relevance",
    "max_results": 5
}

Examples:
Query: "find pdf files from 2025"
{
    "file_types": ["pdf"],
    "time_frame": {"type": "exact", "value": "2025"}
}

Query: "find the latest marketing presentation"
{
    "file_types": ["presentation"],
    "sort": "date_desc",
    "max_results": 1,
    "content": ["marketing"]
}

Query: "find me the budget spreadsheet from last month"
{
    "file_types": ["spreadsheet"],
    "time_frame": {"type": "relative", "value": "last_month"},
    "content": ["budget"]
}"""

        # Results analysis prompt
        self.analysis_prompt = """
You are a file search assistant helping users finding files.
Files can be in several formats, like PDF, Office related formats
(docx, xslx...), text formats, even Markdown.
Analyze the search results in the context of the user's query and:
1. If there's only one result that clearly matches, confirm it or open it.
   Only mention that the search was succesful, don't do any further comments.
2. If there are multiple potential matches or too many results:
    - Ask the user to do a more explicit search
    - Suggest ways to narrow down the search
    - Point out the most likely matches based on the query
4. If there are no results:
   - Suggest alternative search terms
   - Identify possible reasons for no matches

Output JSON in this format:
{
    "status": "single|multiple|too_many|none",
    "analysis": "Your analysis of the situation",
    "suggestions": ["list", "of", "suggestions"],
    "best_matches": [
        {
            "path": "file_path",
            "relevance": "Why this file might be what they want"
        }
    ]
}"""

    def _initialize_backend(self) -> SearchBackend:
        """Initialize best available search backend"""
        backend_override = config.get("skills.smart_finder.backend")
        if backend_override:
            return self._create_backend(backend_override)

        # Try Recoll first
        backend = RecollBackend()
        if backend.is_available():
            if backend.initialize():
                logging.info("Using Recoll search backend")
                return backend

        # Fall back to basic implementation
        logging.info("Using basic search backend")
        backend = BackendsCustom()
        backend.initialize()
        return backend

    async def parse_query(self, query: str) -> Dict[str, Any]:
        """Use LLM to parse natural language query"""
        try:
            llm_response = await self.llm.achat(
                # text=query, system_message=self.parse_prompt
                [
                    {"role": "system", "content": self.parse_prompt},
                    {"role": "user", "content": query},
                ],
                stream=False,
            )
            logging.info(f"Raw LLM response for query parsing: {llm_response}")

            if not llm_response or not isinstance(llm_response, str):
                raise ValueError(f"Invalid LLM response: {llm_response}")

            try:
                parsed = json.loads(llm_response)
                if not isinstance(parsed, dict):
                    raise ValueError("Response is not a JSON object")
                return parsed
            except json.JSONDecodeError as je:
                logging.error(
                    f"JSON parse error: {je}. Response was: {llm_response}"
                )
                return {"content": [query]}

        except Exception as e:
            logging.error(f"Query parsing error: {e}")
            # Fall back to basic keyword search
            return {"content": [query]}

    async def analyze_results(
        self, query: str, results: List[SearchResult]
    ) -> Dict[str, Any]:
        """Use LLM to analyze search results and provide guidance"""

        # Prepare context for LLM
        context = {
            "original_query": query,
            "results_count": len(results),
            "results": [
                {
                    "path": str(r.path),
                    "name": r.name,
                    "type": r.type,
                    "size": r.size,
                    "modified": r.modified.isoformat(),
                    "snippet": r.snippet,
                }
                for r in results[:5]  # Include details of top 5 results
            ],
        }

        try:
            # Get LLM analysis
            llm_response = await self.llm.achat(
                [
                    {"role": "system", "content": self.analysis_prompt},
                    {"role": "user", "content": json.dumps(context)},
                ],
                stream=False,
            )
            logging.debug(f"Raw LLM response for analysis: {llm_response}")

            if not llm_response or not isinstance(llm_response, str):
                raise ValueError(f"Invalid LLM response: {llm_response}")

            try:
                parsed = json.loads(llm_response)
                if not isinstance(parsed, dict):
                    raise ValueError("Response is not a JSON object")
                return parsed
            except json.JSONDecodeError as je:
                logging.error(
                    f"JSON parse error: {je}. Response was: {llm_response}"
                )
                return {
                    "status": "error",
                    "analysis": "Failed to analyze results",
                    "suggestions": ["Try refining your search terms"],
                    "best_matches": [],
                }

        except Exception as e:
            logging.error(f"Analysis error: {e}")
            return {
                "status": "error",
                "analysis": "Failed to analyze results",
                "suggestions": ["Try refining your search terms"],
                "best_matches": [],
            }

    async def show_in_explorer(self, file_path: str) -> Dict[str, Any]:
        """Show file location in system file explorer"""
        try:
            file_path_check = file_path
            if file_path_check.startswith("file:"):
                file_path_check = file_path[len("file:"):]

            path_check = Path(file_path_check)
            if not path_check.exists():
                return {
                    "status": "error",
                    "message": f"File not found: {file_path_check}",
                }

            # Use appropriate command based on OS
            if platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", "-R", file_path])
            elif platform.system() == "Windows":
                subprocess.Popen(["explorer", "/select,", file_path])
            else:  # Linux/Unix
                # Most file managers support showing containing folder
                folder_path = str(Path(file_path).parent)
                subprocess.Popen(["xdg-open", folder_path])

            return {
                "status": "success",
                "message": f"Showed location of file: {file_path}",
                "path": file_path,
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to show file location: {str(e)}",
            }

    async def run(
        self,
        query: Annotated[str, "Natural language description of files to find"],
        limit: Annotated[int, "Maximum number of results to return"] = 10,
        show_location: Annotated[
            Optional[bool], "Whether to show file location in file explorer"
        ] = False,
    ) -> Dict[str, Any]:
        """Find files using natural language description and show their location

        Examples:
            "powerpoint about marketing from last week"
            "large PDF files in Downloads folder"
            "John's documents containing budget"
            "photos from yesterday larger than 5MB"
        """
        try:
            # (re-)create llm instance
            self.llm = create_llm_backend(config.get("llm", {}))

            # Parse query using LLM
            params = await self.parse_query(query)

            # Execute search
            results = await self.backend.search(params, limit=limit)

            if results:
                # Show location of best match if requested
                result = results[0]
                show_result = {"status": "success", "message": "File found"}
                if show_location:
                    show_result = await self.show_in_explorer(str(result.path))

                return {
                    "status": show_result["status"],
                    "query": query,
                    "interpreted_as": params,
                    "shown_file": str(result.path),
                    "message": show_result["message"],
                    "matches": [
                        {
                            "path": str(r.path),
                            "name": r.name,
                            "type": r.type,
                            "size": r.size,
                            "created": r.created.isoformat(),
                            "modified": r.modified.isoformat(),
                            "snippet": r.snippet,
                            "metadata": r.metadata,
                            "score": r.score,
                        }
                        for r in results
                    ],
                }

            # When no files found
            analysis = await self.analyze_results(query, results)

            return {
                "status": "success",
                "query": query,
                "interpreted_as": params,
                "analysis": analysis,
                "backend": self.backend.__class__.__name__,
                "matches": [
                    {
                        "path": str(r.path),
                        "name": r.name,
                        "type": r.type,
                        "size": r.size,
                        "created": r.created.isoformat(),
                        "modified": r.modified.isoformat(),
                        "snippet": r.snippet,
                        "metadata": r.metadata,
                        "score": r.score,
                    }
                    for r in results
                ],
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}
