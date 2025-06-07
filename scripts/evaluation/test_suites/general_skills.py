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
Test suite for general skills evaluation.
"""

from ainara.evaluation.test_suites.base import TestCase, TestSuite


class GeneralSkillsTestSuite(TestSuite):
    """
    Test suite for evaluating basic skill selection and parameter extraction.

    This suite focuses on common, straightforward use cases that any LLM
    should be able to handle correctly.
    """

    def __init__(self):
        """Initialize the general skills test suite with test cases."""
        name = "general_skills"
        description = (
            "Basic skill selection and parameter extraction for common use"
            " cases"
        )

        # Define test cases
        test_cases = [
            # Calculator test case
            TestCase(
                test_id="calculator_simple",
                description="Simple calculator expression",
                input_query="Calculate 25 * 13 + 7",
                expected_skill_id="tools.calculator",
                expected_parameters={"expression": "25 * 13 + 7"},
                mock_skill_execution_result={
                    "result": 332,
                    "steps": ["25 * 13 = 325", "325 + 7 = 332"],
                },
                expected_interpretation_keywords=[
                    "332",
                    "result",
                    "calculation",
                    "25",
                    "13",
                    "7",
                ],
                candidate_skills_info="""
## Skill 1: tools.calculator (match score: 0.85)

Description: Evaluation of mathematical expressions
Parameters:
- expression (string, Required): The mathematical expression to evaluate

## Skill 2: system.clipboard (match score: 0.32)

Description: Read and write the system clipboard
Parameters:
- text (string, Required): Text to write to clipboard

## Skill 3: search.web (match score: 0.28)

Description: Search the web for information
Parameters:
- query (string, Required): The search query
- num_results (integer, Optional): Number of results to return. Default: 5

---
""",
            ),
            # Clipboard test case
            TestCase(
                test_id="clipboard_write",
                description="Write text to clipboard",
                input_query="Copy this text to my clipboard: Hello, world!",
                expected_skill_id="system.clipboard",
                expected_parameters={"text": "Hello, world!"},
                mock_skill_execution_result={
                    "success": True,
                    "message": "Text copied to clipboard",
                },
                expected_interpretation_keywords=[
                    "clipboard",
                    "copied",
                    "successfully",
                    "Hello, world",
                ],
                candidate_skills_info="""
## Skill 1: system.clipboard (match score: 0.92)

Description: Read and write the system clipboard
Parameters:
- text (string, Required): Text to write to clipboard
- clear (boolean, Optional): Whether to clear the clipboard instead. Default: false

## Skill 2: tools.calculator (match score: 0.15)

Description: Evaluation of mathematical expressions
Parameters:
- expression (string, Required): The mathematical expression to evaluate

## Skill 3: search.web (match score: 0.22)

Description: Search the web for information
Parameters:
- query (string, Required): The search query
- num_results (integer, Optional): Number of results to return. Default: 5

---
""",
            ),
            # Web search test case
            TestCase(
                test_id="web_search_basic",
                description="Basic web search",
                input_query=(
                    "Search the web for information about climate change"
                ),
                expected_skill_id="search.web",
                expected_parameters={
                    "query": "climate change",
                    "num_results": 5,
                },
                mock_skill_execution_result={
                    "results": [
                        {
                            "title": (
                                "Climate Change: Causes, Effects, and"
                                " Solutions"
                            ),
                            "url": "https://example.com/climate-change",
                            "snippet": (
                                "Climate change refers to long-term shifts in"
                                " temperatures and weather patterns..."
                            ),
                        },
                        {
                            "title": "NASA: Climate Change and Global Warming",
                            "url": "https://climate.nasa.gov/",
                            "snippet": (
                                "NASA's website for information on climate"
                                " science, highlighting evidence, causes,"
                                " effects..."
                            ),
                        },
                    ]
                },
                expected_interpretation_keywords=[
                    "climate change",
                    "search results",
                    "NASA",
                    "causes",
                    "effects",
                ],
                candidate_skills_info="""
## Skill 1: search.web (match score: 0.88)

Description: Search the web for information
Parameters:
- query (string, Required): The search query
- num_results (integer, Optional): Number of results to return. Default: 5

## Skill 2: system.clipboard (match score: 0.25)

Description: Read and write the system clipboard
Parameters:
- text (string, Required): Text to write to clipboard

## Skill 3: tools.calculator (match score: 0.12)

Description: Evaluation of mathematical expressions
Parameters:
- expression (string, Required): The mathematical expression to evaluate

---
""",
            ),
            # Weather test case
            TestCase(
                test_id="weather_lookup",
                description="Weather lookup for a location",
                input_query="What's the weather like in New York?",
                expected_skill_id="search.weather",
                expected_parameters={"location": "New York"},
                mock_skill_execution_result={
                    "location": "New York, NY",
                    "temperature": 72,
                    "condition": "Partly Cloudy",
                    "humidity": 65,
                    "wind": "10 mph NE",
                    "forecast": [
                        {
                            "day": "Today",
                            "high": 75,
                            "low": 62,
                            "condition": "Partly Cloudy",
                        },
                        {
                            "day": "Tomorrow",
                            "high": 78,
                            "low": 64,
                            "condition": "Sunny",
                        },
                    ],
                },
                expected_interpretation_keywords=[
                    "New York",
                    "temperature",
                    "72",
                    "partly cloudy",
                    "humidity",
                    "forecast",
                    "tomorrow",
                ],
                candidate_skills_info="""
## Skill 1: search.weather (match score: 0.95)

Description: Get weather information for a location
Parameters:
- location (string, Required): The location to get weather for
- units (string, Optional): Temperature units (celsius/fahrenheit). Default: fahrenheit

## Skill 2: search.web (match score: 0.65)

Description: Search the web for information
Parameters:
- query (string, Required): The search query
- num_results (integer, Optional): Number of results to return. Default: 5

## Skill 3: tools.calculator (match score: 0.10)

Description: Evaluation of mathematical expressions
Parameters:
- expression (string, Required): The mathematical expression to evaluate

---
""",
            ),
        ]

        super().__init__(name, description, test_cases)
