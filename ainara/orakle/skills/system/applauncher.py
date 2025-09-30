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
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.util import cos_sim

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

from ainara.framework.config import config
from ainara.framework.llm import create_llm_backend
from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)


class SystemApplauncher(Skill):
    """Launch installed applications or open files using natural language queries"""

    matcher_info = (
        "Use this skill when the user wants to open or launch applications or"
        " files on their system. This skill can handle requests to start"
        " programs by name (e.g., 'launch Google Chrome') or open specific"
        " files with their default applications (e.g., 'open"
        " /path/to/myfile.pdf'). It supports abstract requests like 'open the"
        " browser' by suggesting matches from installed apps. Provide full"
        " file paths for opening files. Do not use this for web searches or"
        " non-local actions.\n\nExamples include: 'launch Google Chrome',"
        " 'open the IDE', 'start my text editor', 'open"
        " /home/user/document.pdf', 'run the calculator app'.\n\nKeywords:"
        " open, launch, run, start, app, application, program, software, file,"
        " document, browser, editor, IDE, calculator, viewer."
    )

    def __init__(self):
        super().__init__()
        # Cache existing apps
        self.discovered_apps = self._discover_apps()
        self.embedding_model = None

        # Query parsing prompt for intent detection
        self.parse_prompt = """You are an app launcher query parser.
Convert natural language queries into structured parameters.
Detect if the intent is to launch an app or open a file.
Output only valid JSON with these possible fields:
{
    "intent": "launch_app" | "open_file",
    "app_name": "name of app (e.g., Google Chrome)",
    "file_path": "full absolute path to file (e.g., /home/user/file.pdf)",
    "abstract": true|false  // if the app request is vague like 'the browser'
}

Examples:
Query: "launch Google Chrome"
{"intent": "launch_app", "app_name": "Google Chrome", "abstract": false}

Query: "open the browser"
{"intent": "launch_app", "app_name": "browser", "abstract": true}

Query: "open /path/to/myfile.pdf"
{"intent": "open_file", "file_path": "/path/to/myfile.pdf"}"""

        # Candidates analysis prompt
        self.analysis_prompt = """
You are an app launcher assistant.
Analyze this pre-filtered list of discovered apps (ranked by semantic similarity to the query) in the context of the user's query and:
1. If there's one clear match, select it for launch. If the user query matches exactly, or almost exactly one candidate select it as well for launch.
2. If multiple matches, suggest the best ones.
3. If none, suggest alternatives.

Output JSON in this format:
{
    "status": "single|multiple|none",
    "analysis": "Brief analysis",
    "suggestions": ["list of suggestions"],
    "best_matches": [
        {
            "name": "app_name",
            "path": "executable_path",
            "relevance": "Why this matches"
        }
    ]
}"""

    def _discover_apps(self) -> List[Dict[str, str]]:
        """Discover installed apps in an OS-specific way"""
        system = platform.system()
        apps = []

        if system == "Windows":
            # Basic scan of common directories (expand as needed)
            program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
            for root, _, files in os.walk(program_files):
                for file in files:
                    if file.lower().endswith((".exe", ".bat")):  # Include common executables
                        apps.append(
                            {
                                "name": file[:-4],
                                "path": os.path.join(root, file),
                            }
                        )
        elif system == "Darwin":  # macOS
            apps_dir = "/Applications"
            for item in os.listdir(apps_dir):
                if item.lower().endswith(".app"):
                    apps.append(
                        {
                            "name": item[:-4],
                            "path": os.path.join(apps_dir, item),
                        }
                    )
        elif system == "Linux":
            apps_dirs = [
                "/usr/share/applications",
                os.path.expanduser("~/.local/share/applications"),
            ]
            for apps_dir in apps_dirs:
                if not os.path.exists(apps_dir):
                    continue
                for root, _, files in os.walk(apps_dir):
                    for file in files:
                        if file.lower().endswith(".desktop"):
                            full_path = os.path.join(root, file)
                            name = re.sub(r'\.desktop$', '', file, flags=re.IGNORECASE)
                            apps.append(
                                {"name": name, "path": full_path}
                            )
        else:
            logger.warning(f"Unsupported OS: {system}")

        # Normalize names for case-insensitive matching
        for app in apps:
            app["name"] = app["name"].lower()

        return apps

    async def parse_query(self, query: str) -> Dict[str, Any]:
        """Use LLM to parse natural language query"""
        try:
            self.llm = create_llm_backend(config.get("llm", {}))
            llm_response = await self.llm.achat(
                [
                    {"role": "system", "content": self.parse_prompt},
                    {"role": "user", "content": query},
                ],
                stream=False,
            )
            if not isinstance(llm_response, str):
                raise ValueError("Invalid LLM response")
            return json.loads(llm_response)
        except Exception as e:
            logger.error(f"Query parsing error: {e}")
            return {
                "intent": "launch_app",
                "app_name": query,
                "abstract": True,
            }

    async def analyze_candidates(
        self, query: str, candidates: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Use embeddings to pre-filter candidates, then LLM to analyze and select"""
        if not candidates:
            return {
                "status": "none",
                "analysis": "No apps discovered on this system",
                "suggestions": ["Install the app or check system paths"],
                "best_matches": [],
            }

        filtered_candidates = candidates
        if self.embedding_model:
            try:
                top_k = 6  # Limit to top 10 semantically similar candidates
                logger.info(f"Pre-filtering {len(candidates)} candidates to top {top_k} using embeddings")

                # Encode query and all candidate names
                query_embedding = self.embedding_model.encode(query, convert_to_tensor=True)
                candidate_names = [app["name"] for app in candidates]
                candidate_embeddings = self.embedding_model.encode(candidate_names, convert_to_tensor=True)

                # Compute cosine similarities
                similarities = cos_sim(query_embedding, candidate_embeddings)[0]

                # Get top_k indices sorted by similarity (descending)
                top_indices = similarities.argsort(descending=True)[:top_k].tolist()

                # Filter candidates
                filtered_candidates = [candidates[i] for i in top_indices]
                logger.info(f"Filtered to {len(filtered_candidates)} top candidates")
            except Exception as e:
                logger.error(f"Embedding filtering failed: {e}. Falling back to all candidates.")

        context = {"original_query": query, "candidates": filtered_candidates}
        try:
            llm_response = await self.llm.achat(
                [
                    {"role": "system", "content": self.analysis_prompt},
                    {"role": "user", "content": json.dumps(context)},
                ],
                stream=False,
            )
            if not isinstance(llm_response, str):
                raise ValueError("Invalid LLM response")
            return json.loads(llm_response)
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return {
                "status": "none",
                "analysis": "Failed to analyze candidates",
                "suggestions": ["Try a more specific app name"],
                "best_matches": [],
            }

    def _launch_app(
        self, app_name: str, app_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Launch an app in an OS-specific way"""
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(app_path or app_name)
            elif system == "Darwin":
                subprocess.Popen(["open", "-a", app_name])
            elif system == "Linux" and app_path and app_path.endswith(".desktop"):
                subprocess.Popen(["xdg-open", app_path])  # Use .desktop paradigm
            else:
                return {"success": False, "error": f"Unsupported OS: {system}"}
            return {
                "success": True,
                "message": f"Launched {app_name}",
                "launched": {"name": app_name, "path": app_path},
            }
        except Exception as e:
            return {
                "success": False,
                "error": "Launch failed",
                "details": str(e),
            }

    def _open_file(self, file_path: str) -> Dict[str, Any]:
        """Open a file with the default app in an OS-specific way"""
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": "File not found",
                "details": file_path,
            }
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":
                subprocess.Popen(["open", file_path])
            elif system == "Linux":
                subprocess.Popen(["xdg-open", file_path])
            else:
                return {"success": False, "error": f"Unsupported OS: {system}"}
            return {
                "success": True,
                "message": f"Opened {file_path}",
                "file_path": file_path,
            }
        except Exception as e:
            return {
                "success": False,
                "error": "Open failed",
                "details": str(e),
            }

    async def run(
        self,
        query: Annotated[
            str, "Natural language request to launch app or open file"
        ],
    ) -> Dict[str, Any]:
        """Launch an app or open a file based on the query

        Examples:
            "launch Google Chrome" → {"success": True, "message": "Launched Google Chrome", ...}
            "open /path/to/file.pdf" → {"success": True, "message": "Opened /path/to/file.pdf", ...}
            "open the browser" → {"success": False, "status": "multiple", "candidates": [...], ...}
        """

        # Lazy initialization of SentenceTransformer
        if not self.embedding_model and SENTENCE_TRANSFORMERS_AVAILABLE:
            embedding_model_name = config.get(
                "memory.vector_storage.embedding_model"
            )
            try:
                self.embedding_model = SentenceTransformer(
                    embedding_model_name,
                    cache_folder=config.get("cache.directory")
                )
                logger.info(f"Loaded embedding model for app analysis: {embedding_model_name}")
            except Exception as e:
                logger.error(f"Failed to load embedding model: {e}")
        else:
            logger.warning(
                "sentence_transformers not available. App candidate filtering will use all discovered apps."
            )

        params = await self.parse_query(query)
        intent = params.get("intent")

        # logger.info("applauncher 1")
        # logger.info(f"params: {params}")

        if intent == "open_file":
            # logger.info("applauncher 2")
            file_path = params.get("file_path")
            if not file_path:
                return {"success": False, "error": "No file path provided"}
            return self._open_file(file_path)

        elif intent == "launch_app":
            # logger.info("applauncher 3")
            app_name = params.get("app_name")
            if not app_name:
                return {"success": False, "error": "No app name provided"}

            # Direct launch if not abstract
            result = self._launch_app(app_name)
            # If direct launch failed, fall back to discovery
            if result.get("success", False):
                return result

            # logger.info("applauncher 4")

            # logger.info(f"discovered: {discovered}")

            analysis = await self.analyze_candidates(query, self.discovered_apps)

            # logger.info(f"analysis: {analysis}")

            if analysis["status"] == "single" and analysis["best_matches"]:
                match = analysis["best_matches"][0]
                return self._launch_app(match["name"], match["path"])
            elif analysis["status"] in ["multiple", "none"]:
                return {
                    "success": False,
                    "status": analysis["status"],
                    "message": analysis["analysis"],
                    "candidates": analysis["best_matches"],
                    "suggestions": analysis["suggestions"],
                }
            else:
                return {"success": False, "error": "Analysis failed"}

        return {"success": False, "error": "Invalid intent"}
