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
Core evaluation logic for testing Orakle middleware with different LLMs.
"""

import json
import logging
import time
from typing import Dict, Optional

from ainara.framework.llm.base import LLMBackend
from ainara.framework.matcher.transformers import OrakleMatcherTransformers
from ainara.framework.template_manager import TemplateManager
from .config.eval_config import EvaluationConfig
from .metrics import (calculate_interpretation_score,
                      calculate_parameter_score)
from .tests.base import TestCase, TestSuite

logger = logging.getLogger(__name__)


class OrakleEvaluator:
    """
    Evaluator for testing Orakle middleware with different LLMs.

    This class simulates the core Orakle middleware functionality for evaluation purposes,
    focusing on skill selection, parameter extraction, and result interpretation.
    """

    def __init__(
        self,
        llm_backend: LLMBackend,
        config: Optional[EvaluationConfig] = None,
        matcher_threshold: float = 0.15,
        matcher_top_k: int = 5,
    ):
        """
        Initialize the OrakleEvaluator.

        Args:
            llm_backend: LLM backend to use for evaluation
            config: Optional evaluation configuration
            matcher_threshold: Threshold for the matcher
            matcher_top_k: Number of top matches to consider
        """
        self.llm = llm_backend
        self.config = config or EvaluationConfig()
        self.matcher_threshold = matcher_threshold
        self.matcher_top_k = matcher_top_k

        # Initialize template manager
        self.template_manager = TemplateManager()

        # Initialize matcher if needed for some tests
        self.matcher = None  # Lazy initialization

        # System message for LLM context
        self.system_message = (
            "You are a helpful AI assistant that processes user requests."
        )

    def _init_matcher_if_needed(self):
        """Initialize the matcher if it hasn't been initialized yet."""
        if self.matcher is None:
            matcher_model = self.config.matcher_model
            self.matcher = OrakleMatcherTransformers(model_name=matcher_model)
            logger.info(f"Initialized matcher with model: {matcher_model}")

    def evaluate_test_case(self, test_case: TestCase) -> Dict:
        """
        Evaluate a single test case.

        Args:
            test_case: The test case to evaluate

        Returns:
            Dictionary containing evaluation results for this test case
        """
        logger.info(f"Evaluating test case: {test_case.test_id}")

        results = {
            "test_id": test_case.test_id,
            "description": test_case.description,
            "input_query": test_case.input_query,
            "expected_skill_id": test_case.expected_skill_id,
            "expected_parameters": test_case.expected_parameters,
            "metrics": {},
            "details": {},
        }

        # Step 1: Skill Matching (if needed)
        if test_case.candidate_skills_info is None and test_case.run_matcher:
            self._init_matcher_if_needed()
            matching_start = time.time()

            # Register skills with the matcher
            for skill in test_case.available_skills:
                self.matcher.register_skill(
                    skill["name"],
                    skill["description"],
                    metadata=skill.get("metadata", {}),
                )

            # Run matching
            matches = self.matcher.match(
                test_case.input_query,
                threshold=self.matcher_threshold,
                top_k=self.matcher_top_k,
            )

            matching_duration = time.time() - matching_start

            # Check if expected skill is in matches
            expected_skill_in_matches = any(
                match["skill_id"] == test_case.expected_skill_id
                for match in matches
            )

            # Format candidate skills for LLM
            candidate_skills = test_case.format_candidate_skills(matches)

            results["details"]["matching"] = {
                "duration": matching_duration,
                "expected_skill_in_matches": expected_skill_in_matches,
                "matches": matches,
            }

            results["metrics"]["matching"] = {
                "duration": matching_duration,
                "expected_skill_in_matches": int(expected_skill_in_matches),
            }
        else:
            # Use provided candidate skills
            candidate_skills = test_case.candidate_skills_info

        # Step 2: LLM Selection & Parameter Extraction
        selection_start = time.time()

        # Prepare prompt for skill selection and parameter extraction
        prompt = self.template_manager.render(
            "framework.chat_manager.orakle_select_and_params",
            {
                "query": test_case.input_query,
                "candidate_skills": candidate_skills,
            },
        )

        # Get LLM response
        chat_result = self.llm.chat(
            chat_history=self.llm.prepare_chat(
                system_message=self.system_message, new_message=prompt
            ),
            stream=False,
        )

        # Handle both tuple and string returns
        if isinstance(chat_result, tuple):
            selection_response = chat_result[0]
        else:
            selection_response = chat_result

        selection_duration = time.time() - selection_start

        # Parse LLM response
        try:
            selection_data = json.loads(selection_response)
            selected_skill_id = selection_data.get("skill_id")
            extracted_parameters = selection_data.get("parameters", {})

            # Calculate skill selection accuracy
            skill_selection_correct = (
                selected_skill_id == test_case.expected_skill_id
            )

            # Calculate parameter extraction score
            param_score, param_details = calculate_parameter_score(
                extracted_parameters, test_case.expected_parameters
            )

            results["details"]["selection"] = {
                "duration": selection_duration,
                "prompt": prompt,
                "response": selection_response,
                "selected_skill_id": selected_skill_id,
                "extracted_parameters": extracted_parameters,
                "skill_selection_correct": skill_selection_correct,
                "parameter_details": param_details,
            }

            results["metrics"]["selection"] = {
                "duration": selection_duration,
                "skill_selection_correct": int(skill_selection_correct),
                "parameter_score": param_score,
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM selection response: {str(e)}")
            results["details"]["selection"] = {
                "duration": selection_duration,
                "prompt": prompt,
                "response": selection_response,
                "error": str(e),
            }

            results["metrics"]["selection"] = {
                "duration": selection_duration,
                "skill_selection_correct": 0,
                "parameter_score": 0,
            }

            # Skip interpretation step if selection failed
            results["metrics"]["interpretation"] = {
                "duration": 0,
                "keyword_match_rate": 0,
            }

            return results

        # Step 3: Result Interpretation
        interpretation_start = time.time()

        # Format mock result
        try:
            if isinstance(test_case.mock_skill_execution_result, str):
                # Check if it's a JSON string
                try:
                    json.loads(test_case.mock_skill_execution_result)
                    formatted_result = f"```json\n{test_case.mock_skill_execution_result}\n```"
                except json.JSONDecodeError:
                    formatted_result = f"```text\n{test_case.mock_skill_execution_result}\n```"
            else:
                # Convert dict to JSON string
                result_json = json.dumps(
                    test_case.mock_skill_execution_result, indent=2
                )
                formatted_result = f"```json\n{result_json}\n```"

            # Prepare interpretation prompt
            interpretation_prompt = self.template_manager.render(
                "framework.chat_manager.command_interpretation",
                {
                    "formatted_results": formatted_result,
                    "query": test_case.input_query,
                },
            )

            # Get interpretation
            chat_result = self.llm.chat(
                chat_history=self.llm.prepare_chat(
                    system_message=self.system_message,
                    new_message=interpretation_prompt,
                ),
                stream=False,
            )

            # Handle both tuple and string returns
            if isinstance(chat_result, tuple):
                interpretation = chat_result[0]
            else:
                interpretation = chat_result

            interpretation_duration = time.time() - interpretation_start

            # Calculate interpretation score
            interp_score, interp_details = calculate_interpretation_score(
                interpretation, test_case.expected_interpretation_keywords
            )

            results["details"]["interpretation"] = {
                "duration": interpretation_duration,
                "prompt": interpretation_prompt,
                "response": interpretation,
                "keyword_details": interp_details,
            }

            results["metrics"]["interpretation"] = {
                "duration": interpretation_duration,
                "keyword_match_rate": interp_score,
            }

        except Exception as e:
            logger.error(f"Error in interpretation step: {str(e)}")
            results["details"]["interpretation"] = {
                "duration": time.time() - interpretation_start,
                "error": str(e),
            }

            results["metrics"]["interpretation"] = {
                "duration": time.time() - interpretation_start,
                "keyword_match_rate": 0,
            }

        # Calculate overall success
        try:
            # A test is successful if:
            # 1. Correct skill was selected
            # 2. Parameter score is above threshold
            # 3. Interpretation score is above threshold
            skill_correct = (
                results["metrics"]["selection"]["skill_selection_correct"] == 1
            )
            param_score_ok = (
                results["metrics"]["selection"]["parameter_score"]
                >= self.config.parameter_score_threshold
            )
            interp_score_ok = (
                results["metrics"]["interpretation"]["keyword_match_rate"]
                >= self.config.interpretation_score_threshold
            )

            overall_success = (
                skill_correct and param_score_ok and interp_score_ok
            )

            results["metrics"]["overall_success"] = int(overall_success)

        except KeyError:
            results["metrics"]["overall_success"] = 0

        logger.info(
            f"Completed test case: {test_case.test_id}, Success:"
            f" {results['metrics'].get('overall_success', 0)}"
        )
        return results

    def evaluate_suite(self, test_suite: TestSuite) -> Dict:
        """
        Evaluate all test cases in a test suite.

        Args:
            test_suite: The test suite to evaluate

        Returns:
            Dictionary containing evaluation results for this test suite
        """
        logger.info(
            f"Evaluating test suite: {test_suite.name} with"
            f" {len(test_suite.test_cases)} test cases"
        )

        suite_results = {
            "name": test_suite.name,
            "description": test_suite.description,
            "test_case_results": [],
            "metrics": {
                "total_tests": len(test_suite.test_cases),
                "successful_tests": 0,
                "skill_selection_accuracy": 0,
                "avg_parameter_score": 0,
                "avg_interpretation_score": 0,
                "avg_duration": 0,
            },
        }

        total_duration = 0
        successful_tests = 0
        skill_selection_correct = 0
        total_param_score = 0
        total_interp_score = 0

        # Evaluate each test case
        for test_case in test_suite.test_cases:
            result = self.evaluate_test_case(test_case)
            suite_results["test_case_results"].append(result)

            # Update metrics
            if result["metrics"].get("overall_success", 0) == 1:
                successful_tests += 1

            if (
                result["metrics"]
                .get("selection", {})
                .get("skill_selection_correct", 0)
                == 1
            ):
                skill_selection_correct += 1

            total_param_score += (
                result["metrics"]
                .get("selection", {})
                .get("parameter_score", 0)
            )
            total_interp_score += (
                result["metrics"]
                .get("interpretation", {})
                .get("keyword_match_rate", 0)
            )

            # Calculate total duration across all steps
            test_duration = (
                result["metrics"].get("matching", {}).get("duration", 0)
                + result["metrics"].get("selection", {}).get("duration", 0)
                + result["metrics"]
                .get("interpretation", {})
                .get("duration", 0)
            )
            total_duration += test_duration

        # Calculate aggregate metrics
        num_tests = len(test_suite.test_cases)
        if num_tests > 0:
            suite_results["metrics"]["successful_tests"] = successful_tests
            suite_results["metrics"]["success_rate"] = (
                successful_tests / num_tests
            )
            suite_results["metrics"]["skill_selection_accuracy"] = (
                skill_selection_correct / num_tests
            )
            suite_results["metrics"]["avg_parameter_score"] = (
                total_param_score / num_tests
            )
            suite_results["metrics"]["avg_interpretation_score"] = (
                total_interp_score / num_tests
            )
            suite_results["metrics"]["avg_duration"] = (
                total_duration / num_tests
            )

        logger.info(
            f"Suite {test_suite.name} evaluation complete. Success rate:"
            f" {suite_results['metrics']['success_rate']:.2f}"
        )
        return suite_results

    def evaluate_all_suites(self, tests: Dict[str, TestSuite]) -> Dict:
        """
        Evaluate all provided test suites.

        Args:
            tests: Dictionary mapping suite names to TestSuite objects

        Returns:
            Dictionary containing evaluation results for all test suites
        """
        all_results = {
            "suites": {},
            "aggregate_metrics": {
                "total_tests": 0,
                "successful_tests": 0,
                "success_rate": 0,
                "skill_selection_accuracy": 0,
                "avg_parameter_score": 0,
                "avg_interpretation_score": 0,
                "avg_duration": 0,
            },
        }

        total_tests = 0
        successful_tests = 0
        skill_selection_correct = 0
        total_param_score = 0
        total_interp_score = 0
        total_duration = 0

        # Evaluate each test suite
        for suite_name, suite in tests.items():
            suite_result = self.evaluate_suite(suite)
            all_results["suites"][suite_name] = suite_result

            # Update aggregate metrics
            suite_tests = suite_result["metrics"]["total_tests"]
            total_tests += suite_tests
            successful_tests += suite_result["metrics"]["successful_tests"]

            # Weight metrics by number of tests in the suite
            skill_selection_correct += (
                suite_result["metrics"]["skill_selection_accuracy"]
                * suite_tests
            )
            total_param_score += (
                suite_result["metrics"]["avg_parameter_score"] * suite_tests
            )
            total_interp_score += (
                suite_result["metrics"]["avg_interpretation_score"]
                * suite_tests
            )
            total_duration += (
                suite_result["metrics"]["avg_duration"] * suite_tests
            )

        # Calculate overall metrics
        if total_tests > 0:
            all_results["aggregate_metrics"]["total_tests"] = total_tests
            all_results["aggregate_metrics"][
                "successful_tests"
            ] = successful_tests
            all_results["aggregate_metrics"]["success_rate"] = (
                successful_tests / total_tests
            )
            all_results["aggregate_metrics"]["skill_selection_accuracy"] = (
                skill_selection_correct / total_tests
            )
            all_results["aggregate_metrics"]["avg_parameter_score"] = (
                total_param_score / total_tests
            )
            all_results["aggregate_metrics"]["avg_interpretation_score"] = (
                total_interp_score / total_tests
            )
            all_results["aggregate_metrics"]["avg_duration"] = (
                total_duration / total_tests
            )

        logger.info(
            "All suites evaluated. Overall success rate:"
            f" {all_results['aggregate_metrics']['success_rate']:.2f}"
        )
        return all_results
