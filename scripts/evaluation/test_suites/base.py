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

"""
Base classes for test cases and test suites.
"""

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class TestCase:
    """
    A test case for evaluating LLM performance in Orakle.

    Each test case represents a specific user query and the expected
    skill selection, parameter extraction, and interpretation.
    """

    test_id: str
    description: str
    input_query: str
    expected_skill_id: str
    expected_parameters: Dict[str, Any]
    mock_skill_execution_result: Union[str, Dict]
    expected_interpretation_keywords: List[str]

    # Optional fields
    candidate_skills_info: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Whether to run the matcher or use provided candidate skills
    run_matcher: bool = False

    # Available skills for matcher (only used if run_matcher is True)
    available_skills: List[Dict] = field(default_factory=list)

    def format_candidate_skills(self, matches: List[Dict]) -> str:
        """
        Format candidate skills for the LLM prompt.

        Args:
            matches: List of skill matches from the matcher

        Returns:
            Formatted string of candidate skills
        """
        formatted_skills = ""

        for i, match in enumerate(matches, 1):
            skill_id = match["skill_id"]
            score = match["score"]

            # Find full skill info
            skill_info = None
            for skill in self.available_skills:
                if skill["name"] == skill_id:
                    skill_info = skill
                    break

            if not skill_info:
                continue

            # Format skill description
            formatted_skills += (
                f"## Skill {i}: {skill_id} (match score: {score:.2f})\n\n"
            )
            formatted_skills += (
                "Description:"
                f" {skill_info.get('description', 'No description')}\n"
            )

            # Add parameters if available
            if "parameters" in skill_info:
                formatted_skills += "Parameters:\n"
                for param in skill_info["parameters"]:
                    param_name = param.get("name", "unknown")
                    param_type = param.get("type", "any")
                    param_desc = param.get("description", "No description")
                    param_required = (
                        "Required"
                        if param.get("required", False)
                        else "Optional"
                    )

                    formatted_skills += (
                        f"- {param_name} ({param_type}, {param_required}):"
                        f" {param_desc}\n"
                    )

            formatted_skills += "\n---\n\n"

        return formatted_skills


class TestSuite(ABC):
    """
    A collection of test cases for evaluating LLM performance.

    Test suites group related test cases and provide metadata about the suite.
    """

    def __init__(
        self, name: str, description: str, test_cases: List[TestCase]
    ):
        """
        Initialize a test suite.

        Args:
            name: Name of the test suite
            description: Description of what this suite tests
            test_cases: List of test cases in this suite
        """
        self.name = name
        self.description = description
        self.test_cases = test_cases
