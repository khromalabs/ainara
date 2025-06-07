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
Metrics and scoring functions for evaluating LLM performance in Orakle.
"""

from typing import Dict, List, Tuple


def calculate_parameter_score(
    extracted_params: Dict, expected_params: Dict
) -> Tuple[float, Dict]:
    """
    Calculate a score for parameter extraction accuracy.

    Args:
        extracted_params: Parameters extracted by the LLM
        expected_params: Expected parameters from the test case

    Returns:
        Tuple of (score, details) where score is between 0.0 and 1.0,
        and details contains information about each parameter comparison
    """
    if not expected_params:
        # If no parameters were expected, check if any were extracted
        if not extracted_params:
            return 1.0, {"message": "No parameters expected or extracted"}
        else:
            return 0.0, {
                "message": "Parameters extracted when none expected",
                "extracted": extracted_params,
            }

    # Initialize counters for F1 score calculation
    true_positives = 0
    false_positives = 0
    false_negatives = 0

    # Track details for each parameter
    param_details = {}

    # Check each expected parameter
    for param_name, expected_value in expected_params.items():
        if param_name in extracted_params:
            extracted_value = extracted_params[param_name]

            # Compare values
            if _compare_parameter_values(extracted_value, expected_value):
                true_positives += 1
                param_details[param_name] = {
                    "status": "correct",
                    "expected": expected_value,
                    "extracted": extracted_value,
                }
            else:
                false_positives += 1
                param_details[param_name] = {
                    "status": "incorrect_value",
                    "expected": expected_value,
                    "extracted": extracted_value,
                }
        else:
            false_negatives += 1
            param_details[param_name] = {
                "status": "missing",
                "expected": expected_value,
            }

    # Check for extra parameters that weren't expected
    for param_name in extracted_params:
        if param_name not in expected_params:
            false_positives += 1
            param_details[param_name] = {
                "status": "unexpected",
                "extracted": extracted_params[param_name],
            }

    # Calculate F1 score
    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0
    )
    f1_score = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0
    )

    details = {
        "parameter_details": param_details,
        "metrics": {
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
        },
    }

    return f1_score, details


def _compare_parameter_values(extracted_value, expected_value) -> bool:
    """
    Compare extracted and expected parameter values with appropriate flexibility.

    This function handles different types of values and provides some flexibility
    in matching (e.g., case-insensitive string comparison).

    Args:
        extracted_value: Value extracted by the LLM
        expected_value: Expected value from the test case

    Returns:
        True if values match, False otherwise
    """
    # Handle None values
    if expected_value is None:
        return extracted_value is None

    # Handle different types
    if isinstance(expected_value, str) and isinstance(extracted_value, str):
        # Case-insensitive string comparison
        return expected_value.lower() == extracted_value.lower()

    elif isinstance(expected_value, (int, float)) and isinstance(
        extracted_value, (int, float)
    ):
        # Numeric comparison with small tolerance
        if isinstance(expected_value, int) and isinstance(
            extracted_value, int
        ):
            return expected_value == extracted_value
        else:
            # Allow small floating point differences
            return abs(expected_value - extracted_value) < 1e-6

    elif isinstance(expected_value, bool) and isinstance(
        extracted_value, bool
    ):
        # Boolean comparison
        return expected_value == extracted_value

    elif isinstance(expected_value, list) and isinstance(
        extracted_value, list
    ):
        # List comparison - check if all expected items are in extracted list
        if len(expected_value) != len(extracted_value):
            return False

        # Sort lists if they contain simple types
        if all(
            isinstance(x, (str, int, float, bool))
            for x in expected_value + extracted_value
        ):
            try:
                sorted_expected = sorted(expected_value)
                sorted_extracted = sorted(extracted_value)
                return all(
                    _compare_parameter_values(a, b)
                    for a, b in zip(sorted_extracted, sorted_expected)
                )
            except TypeError:
                # Fall back to item-by-item comparison if sorting fails
                pass

        # Item-by-item comparison
        return all(
            any(
                _compare_parameter_values(ex_item, exp_item)
                for ex_item in extracted_value
            )
            for exp_item in expected_value
        )

    elif isinstance(expected_value, dict) and isinstance(
        extracted_value, dict
    ):
        # Dictionary comparison
        if set(expected_value.keys()) != set(extracted_value.keys()):
            return False

        return all(
            _compare_parameter_values(extracted_value[k], v)
            for k, v in expected_value.items()
        )

    # Fall back to direct equality comparison
    return expected_value == extracted_value


def calculate_interpretation_score(
    interpretation: str, expected_keywords: List[str]
) -> Tuple[float, Dict]:
    """
    Calculate a score for the LLM's interpretation based on keyword presence.

    Args:
        interpretation: The LLM's interpretation text
        expected_keywords: List of keywords expected in the interpretation

    Returns:
        Tuple of (score, details) where score is between 0.0 and 1.0,
        and details contains information about each keyword match
    """
    if not expected_keywords:
        return 1.0, {"message": "No keywords specified for evaluation"}

    # Convert interpretation to lowercase for case-insensitive matching
    lower_interpretation = interpretation.lower()

    # Track which keywords were found
    keyword_matches = {}
    matches_found = 0

    for keyword in expected_keywords:
        lower_keyword = keyword.lower()
        if lower_keyword in lower_interpretation:
            keyword_matches[keyword] = True
            matches_found += 1
        else:
            keyword_matches[keyword] = False

    # Calculate score as percentage of keywords found
    score = matches_found / len(expected_keywords)

    details = {
        "keyword_matches": keyword_matches,
        "matches_found": matches_found,
        "total_keywords": len(expected_keywords),
        "score": score,
    }

    return score, details


def calculate_aggregate_metrics(llm_results: Dict) -> Dict:
    """
    Calculate aggregate metrics across all LLMs.

    Args:
        llm_results: Dictionary mapping LLM names to their evaluation results

    Returns:
        Dictionary containing aggregate metrics
    """
    aggregate = {
        "llm_comparison": {},
        "best_overall": None,
        "best_skill_selection": None,
        "best_parameter_extraction": None,
        "best_interpretation": None,
        "fastest": None,
    }

    # Extract key metrics for each LLM
    for llm_name, results in llm_results.items():
        if "error" in results:
            # Skip LLMs that had errors
            continue

        # Get aggregate metrics for this LLM
        try:
            llm_metrics = results.get("aggregate_metrics", {})

            aggregate["llm_comparison"][llm_name] = {
                "success_rate": llm_metrics.get("success_rate", 0),
                "skill_selection_accuracy": llm_metrics.get(
                    "skill_selection_accuracy", 0
                ),
                "avg_parameter_score": llm_metrics.get(
                    "avg_parameter_score", 0
                ),
                "avg_interpretation_score": llm_metrics.get(
                    "avg_interpretation_score", 0
                ),
                "avg_duration": llm_metrics.get("avg_duration", 0),
            }
        except Exception:
            # Skip LLMs with incomplete metrics
            continue

    # Find best performers in each category
    if aggregate["llm_comparison"]:
        # Best overall (by success rate)
        aggregate["best_overall"] = max(
            aggregate["llm_comparison"].items(),
            key=lambda x: x[1]["success_rate"],
        )[0]

        # Best skill selection
        aggregate["best_skill_selection"] = max(
            aggregate["llm_comparison"].items(),
            key=lambda x: x[1]["skill_selection_accuracy"],
        )[0]

        # Best parameter extraction
        aggregate["best_parameter_extraction"] = max(
            aggregate["llm_comparison"].items(),
            key=lambda x: x[1]["avg_parameter_score"],
        )[0]

        # Best interpretation
        aggregate["best_interpretation"] = max(
            aggregate["llm_comparison"].items(),
            key=lambda x: x[1]["avg_interpretation_score"],
        )[0]

        # Fastest
        aggregate["fastest"] = min(
            aggregate["llm_comparison"].items(),
            key=lambda x: x[1]["avg_duration"],
        )[0]

    return aggregate
