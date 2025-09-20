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
import pprint
from typing import Any, Dict, List, Optional

from ..template_manager import TemplateManager
from .base import OrakleMatcherBase

logger = logging.getLogger(__name__)


class OrakleMatcherLLM(OrakleMatcherBase):
    """
    LLM-based skill matching system that uses natural language understanding
    to match user queries with available skills.
    """

    def __init__(self, llm=None, template_manager=None):
        """
        Initialize the LLM-based matcher.

        Args:
            llm: LLM instance to use for matching (optional)
            template_manager: TemplateManager instance for rendering prompts (optional)
        """
        super().__init__()
        self.llm = llm
        self.skills_registry = {}
        self.usage_stats = {}  # Initialize usage statistics dictionary

        # Initialize template manager if not provided
        self.template_manager = template_manager or TemplateManager()

    def register_skill(
        self, skill_id: str, description: str, metadata: Optional[Dict] = None
    ):
        """
        Register a new skill with its description.

        Args:
            skill_id: Unique identifier for the skill
            description: Natural language description of the skill
            metadata: Additional skill metadata
        """
        self.skills_registry[skill_id] = {
            "description": description,
            "metadata": metadata or {},
        }
        logger.debug(f"Registered skill: {skill_id}")

    def _format_skills_for_llm(self) -> str:
        """
        Format all registered skills into a string for the LLM prompt.
        """
        skills_text = "Available skills:\n"
        for skill_id, data in self.skills_registry.items():
            skills_text += (
                f"- {skill_id}: "
                f"{data.get('description', '')}"
                f"{' ' + data['metadata']['matcher_info'] if data['metadata']['matcher_info'] else ''}"
                "\n"
            )

        # logger.info("SKILLS_TEXT: " + pprint.pformat(skills_text))

        return skills_text

    def _create_matcher_prompt(self, query: str) -> str:
        """
        Create the prompt for the LLM to match skills using the template manager.
        """
        context = {
            "skills_list": self._format_skills_for_llm(),
            "query": query,
        }

        return self.template_manager.render("framework.matcher.skill_matching", context)

    def match(
        self, query: str, threshold: float = 0.1, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find the best matching skills for a given query using LLM.

        Args:
            query: The user's query text
            threshold: Minimum confidence threshold
            top_k: Maximum number of matches to return

        Returns:
            List of matching skills with confidence scores and reasoning
        """
        if not self.llm:
            raise RuntimeError("LLM backend not configured")

        prompt = self._create_matcher_prompt(query)

        try:
            # Get LLM response
            logger.info(f"Matcher query: {query}")
            logger.info(f"Matcher prompt: {prompt}")

            response = self.llm.chat(
                self.llm.prepare_chat(
                    system_message=(
                        "You are a skill matching assistant. Your task is to"
                        " match user requests to the most appropriate"
                        " available skills."
                    ),
                    new_message=prompt,
                )
            )

            logger.info(f"LLM matcher response: {response}")

            # Parse LLM response
            result = json.loads(response)
            logger.info(f"Parsed matcher result: {result}")

            # Filter and sort matches
            matches = result.get("matches", [])
            logger.info(f"Raw matches before filtering: {matches}")
            matches = [m for m in matches if m["confidence"] >= threshold]
            matches.sort(key=lambda x: x["confidence"], reverse=True)
            logger.info(f"Filtered matches (threshold={threshold}): {matches}")

            # Validate matches and update usage stats
            valid_matches = []
            for match in matches:
                skill_id = match.get("skill_id")
                if skill_id in self.skills_registry:
                    # Create a new match dict to avoid modifying the original
                    valid_match = match.copy()
                    # Update usage count
                    self.usage_stats[skill_id] = (
                        self.usage_stats.get(skill_id, 0) + 1
                    )
                    valid_match["usage_count"] = self.usage_stats[skill_id]
                    valid_match["description"] = self.skills_registry[
                        skill_id
                    ]["metadata"].get(
                        "run_info",
                        self.skills_registry[skill_id]["description"],
                    )

                    valid_matches.append(valid_match)
                else:
                    logger.warning(
                        f"LLM returned invalid skill_id: {skill_id}"
                    )

            logger.info("-----")
            logger.info(pprint.pformat(valid_matches))

            return valid_matches[:top_k]

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e} ... response: {response}")
            return []
        except Exception as e:
            logger.error(f"Error matching skills: {str(e)}")
            return []
