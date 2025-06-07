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
Main orchestrator for running evaluations across multiple LLMs and test suites.
"""

import argparse
import importlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ainara.framework.config import config as ainara_config_manager
from ainara.framework.llm import create_llm_backend
from .evaluator import OrakleEvaluator
from .metrics import calculate_aggregate_metrics
from .report_generator import generate_report
from .config.eval_config import EvaluationConfig

logger = logging.getLogger(__name__)


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging configuration for the evaluation run."""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )


def load_tests(test_names: List[str]) -> Dict:
    """
    Load test suites by name.

    Args:
        test_names: List of test suite module names to load

    Returns:
        Dictionary mapping suite names to loaded test suite objects
    """
    suites = {}
    for test_name in test_names:
        try:
            # Import the module
            module_path = f"scripts.evaluation.tests.{test_name}"
            logger.info(f"module: {module_path}")
            module = importlib.import_module(module_path)

            # Get the test suite class (assuming it follows naming convention)
            class_name = "".join(word.capitalize() for word in test_name.split("_")) + "TestSuite"
            suite_class = getattr(module, class_name)

            # Instantiate the test suite
            suite_instance = suite_class()
            suites[test_name] = suite_instance
            logger.info(f"Loaded test suite: {test_name} with {len(suite_instance.test_cases)} test cases")
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to load test suite {test_name}: {str(e)}")

    return suites


def get_llm_configs_from_ainara_config() -> List[Dict[str, Any]]:
    """Loads LLM configurations from Ainara's global config manager."""
    formatted_llm_configs: List[Dict[str, Any]] = []
    ainara_llm_config = ainara_config_manager.get("llm")

    if not ainara_llm_config or "providers" not in ainara_llm_config:
        logger.warning("No 'llm.providers' found in Ainara configuration.")
        return []

    providers_list = ainara_llm_config.get("providers", [])
    if not isinstance(providers_list, list):
        logger.warning("'llm.providers' is not a list in Ainara configuration.")
        return []

    default_provider_type = ainara_llm_config.get("selected_backend", "litellm")

    for i, p_config in enumerate(providers_list):
        if not isinstance(p_config, dict):
            logger.warning(f"Skipping non-dictionary provider config at index {i}: {p_config}")
            continue

        model_identifier = p_config.get("model")
        if not model_identifier:
            logger.warning(f"Provider config at index {i} is missing 'model' key: {p_config}")
            continue

        llm_name = p_config.get("name", model_identifier)

        final_config: Dict[str, Any] = {
            "name": llm_name,
            "provider": p_config.get("provider", default_provider_type),
            **p_config, # Include all other keys from the provider config
        }
        formatted_llm_configs.append(final_config)

    if not formatted_llm_configs:
        logger.warning("No valid LLM provider configurations were extracted from Ainara config.")
    return formatted_llm_configs

def run_evaluation(
    config: Optional[EvaluationConfig] = None,
    llm_configs: Optional[List[Dict]] = None,
    tests: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
) -> Dict:
    """
    Run the evaluation process across specified LLMs and test suites.

    Args:
        config: Optional evaluation configuration object
        llm_configs: Optional list of LLM configurations to override config
        tests: Optional list of test suite names to override config
        output_dir: Optional directory for output files

    Returns:
        Dictionary containing evaluation results
    """
    start_time = time.time()

    # Use provided config or create default
    if config is None:
        config = EvaluationConfig()

    # Override config if parameters provided
    if llm_configs is not None:
        config.llm_configs = llm_configs
    if tests is not None:
        config.tests = tests
    if output_dir is not None:
        config.output_dir = output_dir

    if not config.llm_configs:
        logger.error("No LLM configurations specified for evaluation. Aborting.")
        return {"error": "No LLM configurations specified"}

    # Ensure output directory exists
    os.makedirs(config.output_dir, exist_ok=True)

    # Set up logging
    setup_logging(config.log_level)

    logger.info(f"Starting evaluation with {len(config.llm_configs)} LLM configurations")
    logger.info(f"Test suites to run: {config.tests}")

    # Load test suites
    suites = load_tests(config.tests)
    if not suites:
        logger.error("No test suites could be loaded. Aborting evaluation.")
        return {"error": "No test suites loaded"}

    # Initialize results structure
    results = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "duration": None,
            "config": config.to_dict(),
        },
        "llm_results": {},
        "aggregate_metrics": None,
    }

    # Run evaluation for each LLM configuration
    for llm_idx, llm_config in enumerate(config.llm_configs):
        llm_name = llm_config.get("name", f"llm_{llm_idx}")
        logger.info(f"Evaluating LLM: {llm_name} ({llm_idx+1}/{len(config.llm_configs)})")

        try:
            # Create LLM backend
            llm_backend = create_llm_backend(llm_config)

            # Initialize evaluator
            evaluator = OrakleEvaluator(llm_backend, config=config)

            # Run evaluation across all test suites
            llm_results = evaluator.evaluate_all_suites(suites)

            # Store results
            results["llm_results"][llm_name] = llm_results
            logger.info(f"Completed evaluation for {llm_name}")

        except Exception as e:
            logger.error(f"Error evaluating {llm_name}: {str(e)}", exc_info=True)
            results["llm_results"][llm_name] = {"error": str(e)}

    # Calculate aggregate metrics
    results["aggregate_metrics"] = calculate_aggregate_metrics(results["llm_results"])

    # Record total duration
    results["metadata"]["duration"] = time.time() - start_time

    # Generate report
    report_path = generate_report(results, config.output_dir)
    logger.info(f"Evaluation complete. Report saved to: {report_path}")

    # Save raw results
    results_path = os.path.join(config.output_dir, "evaluation_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    return results


def parse_args():
    """Parse command line arguments for the evaluation runner."""
    parser = argparse.ArgumentParser(description="Run Orakle LLM evaluation")

    parser.add_argument(
        "--config",
        type=str,
        help="Path to evaluation configuration JSON file"
    )

    parser.add_argument(
        "--llm",
        action="append",
        help="LLM configuration name(s) to test (can be specified multiple times)"
    )

    parser.add_argument(
        "--suite",
        action="append",
        help="Test suite name(s) to run (can be specified multiple times)"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        help="Directory for output files"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set the logging level"
    )

    return parser.parse_args()


def main():
    """Main entry point for running evaluations from command line."""
    args = parse_args()

    # Load Ainara's main configuration first
    ainara_config_manager.load_config() # Ensures it's loaded if not already

    # Load base evaluation config from file if specified
    eval_config_obj: EvaluationConfig
    if args.config:
        with open(args.config, "r") as f:
            config_dict = json.load(f)
            eval_config_obj = EvaluationConfig.from_dict(config_dict)
    else:
        eval_config_obj = EvaluationConfig() # Starts with empty llm_configs

    # Override with command line arguments
    # Determine LLM configurations
    if args.llm:
        all_ainara_llms = get_llm_configs_from_ainara_config()
        selected_llm_configs = []
        for llm_name in args.llm:
            found_config = next(
                (c for c in all_ainara_llms if c.get("name") == llm_name or c.get("model") == llm_name), None
            )
            if found_config:
                selected_llm_configs.append(found_config)
            else:
                # Fallback: if not in Ainara config, assume it's a direct model name for the default provider
                logger.warning(
                    f"LLM '{llm_name}' not found in Ainara config. Assuming direct model name "
                    f"for provider '{ainara_config_manager.get('llm.selected_backend', 'litellm')}'."
                )
                selected_llm_configs.append({
                    "name": llm_name,
                    "provider": ainara_config_manager.get("llm.selected_backend", "litellm"),
                    "model": llm_name,
                })
        eval_config_obj.llm_configs = selected_llm_configs
    elif not eval_config_obj.llm_configs: # Only if not set by eval config file and no --llm args
        # No specific LLMs requested via CLI or eval config file, use all from Ainara config
        eval_config_obj.llm_configs = get_llm_configs_from_ainara_config()

    if not eval_config_obj.llm_configs:
        logger.error("No LLM configurations to evaluate. Check Ainara config, evaluation config file, or --llm arguments. Aborting.")
        return

    if args.suite:
        eval_config_obj.tests = args.suite # Note: EvaluationConfig uses 'tests'
    if args.output_dir:
        eval_config_obj.output_dir = args.output_dir
    if args.log_level:
        eval_config_obj.log_level = args.log_level

    # Run evaluation
    run_evaluation(config=eval_config_obj)


if __name__ == "__main__":
    main()
