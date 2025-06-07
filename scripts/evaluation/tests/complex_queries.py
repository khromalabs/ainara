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
Test suite for complex query evaluation.
"""

from .base import TestCase, TestSuite


class ComplexQueriesTestSuite(TestSuite):
    """
    Test suite for evaluating complex and ambiguous queries.

    This suite focuses on more challenging scenarios where the LLM needs to
    disambiguate between similar skills or extract complex parameters.
    """

    def __init__(self):
        """Initialize the complex queries test suite with test cases."""
        name = "complex_queries"
        description = (
            "Complex and ambiguous queries that require careful skill"
            " selection and parameter extraction"
        )

        # Define test cases
        test_cases = [
            # Ambiguous query that could match multiple skills
            TestCase(
                test_id="ambiguous_search_vs_weather",
                description="Ambiguous query that could be search or weather",
                input_query=(
                    "I need information about the climate in Barcelona"
                ),
                expected_skill_id="search.weather",
                expected_parameters={"location": "Barcelona"},
                mock_skill_execution_result={
                    "location": "Barcelona, Spain",
                    "temperature": 22,
                    "condition": "Sunny",
                    "humidity": 60,
                    "wind": "5 mph SW",
                    "climate": {
                        "type": "Mediterranean",
                        "avg_annual_temp": 21.2,
                        "rainy_season": "Fall",
                    },
                },
                expected_interpretation_keywords=[
                    "Barcelona",
                    "climate",
                    "Mediterranean",
                    "temperature",
                    "sunny",
                ],
                candidate_skills_info="""
## Skill 1: search.weather (match score: 0.78)

Description: Get weather information for a location
Parameters:
- location (string, Required): The location to get weather for
- units (string, Optional): Temperature units (celsius/fahrenheit). Default: celsius
- include_climate (boolean, Optional): Include climate information. Default: true

## Skill 2: search.web (match score: 0.76)

Description: Search the web for information
Parameters:
- query (string, Required): The search query
- num_results (integer, Optional): Number of results to return. Default: 5

## Skill 3: search.travel (match score: 0.72)

Description: Get travel information about a destination
Parameters:
- destination (string, Required): The travel destination
- info_type (string, Optional): Type of information (attractions, hotels, transport). Default: general

---
""",
            ),
            # Complex parameter extraction
            TestCase(
                test_id="complex_parameters_extraction",
                description="Query with multiple parameters to extract",
                input_query=(
                    "Find flights from New York to London departing next"
                    " Friday and returning on Sunday, for 2 adults and 1 child"
                ),
                expected_skill_id="search.flights",
                expected_parameters={
                    "origin": "New York",
                    "destination": "London",
                    "departure_date": "next Friday",
                    "return_date": "Sunday",
                    "adults": 2,
                    "children": 1,
                },
                mock_skill_execution_result={
                    "flights": [
                        {
                            "airline": "British Airways",
                            "flight_number": "BA178",
                            "departure": "JFK 19:30",
                            "arrival": "LHR 07:45+1",
                            "price": 850,
                            "duration": "7h 15m",
                        },
                        {
                            "airline": "American Airlines",
                            "flight_number": "AA100",
                            "departure": "JFK 18:15",
                            "arrival": "LHR 06:30+1",
                            "price": 795,
                            "duration": "7h 15m",
                        },
                    ],
                    "total_price": "From $2,385 for all passengers",
                },
                expected_interpretation_keywords=[
                    "flights",
                    "New York",
                    "London",
                    "Friday",
                    "Sunday",
                    "British Airways",
                    "American Airlines",
                    "price",
                ],
                candidate_skills_info="""
## Skill 1: search.flights (match score: 0.92)

Description: Search for flight information
Parameters:
- origin (string, Required): Departure city or airport
- destination (string, Required): Arrival city or airport
- departure_date (string, Required): Date of departure
- return_date (string, Optional): Date of return for round trips
- adults (integer, Optional): Number of adult passengers. Default: 1
- children (integer, Optional): Number of child passengers. Default: 0
- class (string, Optional): Travel class (economy, business, first). Default: economy

## Skill 2: search.travel (match score: 0.85)

Description: Get travel information about a destination
Parameters:
- destination (string, Required): The travel destination
- info_type (string, Optional): Type of information (attractions, hotels, transport). Default: general

## Skill 3: search.web (match score: 0.65)

Description: Search the web for information
Parameters:
- query (string, Required): The search query
- num_results (integer, Optional): Number of results to return. Default: 5

---
""",
            ),
            # Implicit parameter extraction
            TestCase(
                test_id="implicit_parameters",
                description=(
                    "Query with implicit parameters that need to be inferred"
                ),
                input_query="Remind me to call mom tomorrow at 5pm",
                expected_skill_id="system.reminder",
                expected_parameters={
                    "task": "call mom",
                    "date": "tomorrow",
                    "time": "5pm",
                },
                mock_skill_execution_result={
                    "success": True,
                    "reminder_id": "rem_12345",
                    "message": "Reminder set: call mom tomorrow at 5:00 PM",
                },
                expected_interpretation_keywords=[
                    "reminder",
                    "set",
                    "call mom",
                    "tomorrow",
                    "5:00 PM",
                    "successfully",
                ],
                candidate_skills_info="""
## Skill 1: system.reminder (match score: 0.88)

Description: Set reminders for tasks
Parameters:
- task (string, Required): The task to be reminded about
- date (string, Required): The date for the reminder
- time (string, Required): The time for the reminder
- repeat (string, Optional): Repetition pattern (daily, weekly, monthly). Default: none

## Skill 2: system.calendar (match score: 0.75)

Description: Manage calendar events
Parameters:
- title (string, Required): Event title
- start_date (string, Required): Start date of the event
- start_time (string, Required): Start time of the event
- end_date (string, Optional): End date of the event
- end_time (string, Optional): End time of the event

## Skill 3: system.message (match score: 0.62)

Description: Send messages to contacts
Parameters:
- contact (string, Required): Contact name or number
- message (string, Required): Message content
- schedule (string, Optional): When to send the message. Default: now

---
""",
            ),
            # Query requiring disambiguation
            TestCase(
                test_id="disambiguation_needed",
                description=(
                    "Query that requires disambiguation between similar skills"
                ),
                input_query="I need to convert 100 USD to EUR",
                expected_skill_id="tools.currency_converter",
                expected_parameters={
                    "amount": 100,
                    "from_currency": "USD",
                    "to_currency": "EUR",
                },
                mock_skill_execution_result={
                    "from": "USD",
                    "to": "EUR",
                    "amount": 100,
                    "result": 91.85,
                    "rate": 0.9185,
                    "timestamp": "2023-06-15T12:00:00Z",
                },
                expected_interpretation_keywords=[
                    "converted",
                    "100 USD",
                    "91.85 EUR",
                    "exchange rate",
                    "0.9185",
                ],
                candidate_skills_info="""
## Skill 1: tools.currency_converter (match score: 0.89)

Description: Convert between different currencies
Parameters:
- amount (number, Required): The amount to convert
- from_currency (string, Required): Source currency code (e.g., USD)
- to_currency (string, Required): Target currency code (e.g., EUR)

## Skill 2: tools.unit_converter (match score: 0.87)

Description: Convert between different units of measurement
Parameters:
- value (number, Required): The value to convert
- from_unit (string, Required): Source unit
- to_unit (string, Required): Target unit
- type (string, Optional): Conversion type (length, weight, volume, etc.). Default: auto

## Skill 3: tools.calculator (match score: 0.65)

Description: Evaluation of mathematical expressions
Parameters:
- expression (string, Required): The mathematical expression to evaluate

---
""",
            ),
        ]

        super().__init__(name, description, test_cases)
