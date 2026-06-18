"""Skill for listing all available Ainara skills and their descriptions."""

import logging
from typing import Annotated, Any, Dict, Optional

import requests

from ainara.framework.skill import Skill


class ToolsSkillList(Skill):
    """List all skills and capabilities currently available in the Ainara system"""

    matcher_info = (
        "Use this skill when the user wants to know what skills, tools, or capabilities "
        "Ainara has, or asks for a list of what it can do. "
        "Keywords: list skills, what skills, what can you do, capabilities, "
        "available skills, what tools, show skills, skill list."
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def run(
        self,
        filter: Annotated[
            Optional[str],
            "Optional keyword to filter skills by name or description",
        ] = None,
    ) -> Dict[str, Any]:
        """Returns the list of all capabilities registered in the Orakle server.

        Args:
            filter: Optional keyword to filter results (e.g. 'search', 'file')

        Returns:
            Dict with success (bool) and a list of skill summaries
        """
        try:
            response = requests.get(
                "http://127.0.0.1:8100/capabilities", timeout=5
            )
            response.raise_for_status()
            capabilities = response.json()

            skills = []
            for name, info in sorted(capabilities.items()):
                desc = info.get("description", "").strip()
                if filter and filter.lower() not in name.lower() and filter.lower() not in desc.lower():
                    continue
                skills.append({"name": name, "description": desc})

            return {
                "success": True,
                "count": len(skills),
                "skills": skills,
            }
        except Exception as e:
            self.logger.error(f"{self.name} failed: {e}")
            return {"success": False, "error": str(e)}
