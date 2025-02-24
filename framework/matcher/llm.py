import logging
import pprint
from typing import Any, Dict, List, Optional

from .base import OrakleMatcherBase

logger = logging.getLogger(__name__)


class OrakleMatcherLLM(OrakleMatcherBase):
    """
    LLM-based skill matching system that uses natural language understanding
    to match user queries with available skills.
    """

    def __init__(self, llm=None):
        """
        Initialize the LLM-based matcher.

        Args:
            llm: LLM instance to use for matching (optional)
        """
        super().__init__()
        self.llm = llm
        self.skills_registry = {}
        self.usage_stats = {}  # Initialize usage statistics dictionary

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
        skills_text = "Available skills:\n\n"
        for skill_id, data in self.skills_registry.items():
            skills_text += f"- {skill_id}: {data['description']}\n"
        return skills_text

    def _create_matcher_prompt(self, query: str) -> str:
        """
        Create the prompt for the LLM to match skills.
        """
        return f"""Given the following list of available skills, determine which skill(s) best match the user's request.
If multiple skills could be relevant, list them in order of relevance.
If you're unsure, you can suggest multiple potentially relevant skills.

{self._format_skills_for_llm()}

User request: {query}

Respond in this JSON format:
{{
    "matches": [
        {{
            "skill_id": "the_skill_id",
            "confidence": 0.9,  # between 0 and 1
            "reasoning": "Brief explanation of why this skill matches"
        }}
    ]
}}

Your response:"""

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
            response = self.llm.process_text(
                prompt,
                system_message=(
                    "You are a skill matching assistant. Your task is to match"
                    " user requests to the most appropriate available skills."
                ),
            )

            # Parse LLM response (assuming it returns valid JSON)
            import json

            result = json.loads(response)

            # Filter and sort matches
            matches = result.get("matches", [])
            matches = [m for m in matches if m["confidence"] >= threshold]
            matches.sort(key=lambda x: x["confidence"], reverse=True)

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
                    valid_match["description"] = self.skills_registry[skill_id]["metadata"].get("runinfo", self.skills_registry[skill_id]["description"])

                    valid_matches.append(valid_match)
                else:
                    logger.warning(
                        f"LLM returned invalid skill_id: {skill_id}"
                    )

            logger.info("-----")
            logger.info(pprint.pformat(valid_matches))

            return valid_matches[:top_k]

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error matching skills: {str(e)}")
            return []
