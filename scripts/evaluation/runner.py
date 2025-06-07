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
from typing import Dict, List, Optional

# from ainara.framework.config import ConfigManager
from ainara.framework.llm import create_llm_backend
from ainara.scripts.evaluation.evaluator import OrakleEvaluator
from ainara.scripts.evaluation.metrics import calculate_aggregate_metrics
from ainara.scripts.evaluation.report_generator import generate_report
from ainara.scripts.evaluation.config.eval_config import (
    DEFAULT_LLM_CONFIGS,
    EvaluationConfig,
)

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


def load_test_suites(suite_names: List[str]) -> Dict:
    """
    Load test suites by name.

    Args:
        suite_names: List of test suite module names to load

    Returns:
        Dictionary mapping suite names to loaded test suite objects
    """
    suites = {}
    for suite_name in suite_names:
        try:
            # Import the module
            module_path = f"ainara.scripts.evaluation.test_suites.{suite_name}"
            module = importlib.import_module(module_path)

            # Get the test suite class (assuming it follows naming convention)
            class_name = "".join(word.capitalize() for word in suite_name.split("_")) + "TestSuite"
            suite_class = getattr(module, class_name)

            # Instantiate the test suite
            suite_instance = suite_class()
            suites[suite_name] = suite_instance
            logger.info(f"Loaded test suite: {suite_name} with {len(suite_instance.test_cases)} test cases")
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to load test suite {suite_name}: {str(e)}")

    return suites


def run_evaluation(
    config: Optional[EvaluationConfig] = None,
    llm_configs: Optional[List[Dict]] = None,
    test_suites: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
) -> Dict:
    """
    Run the evaluation process across specified LLMs and test suites.

    Args:
        config: Optional evaluation configuration object
        llm_configs: Optional list of LLM configurations to override config
        test_suites: Optional list of test suite names to override config
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
    if test_suites is not None:
        config.test_suites = test_suites
    if output_dir is not None:
        config.output_dir = output_dir

    # Ensure output directory exists
    os.makedirs(config.output_dir, exist_ok=True)

    # Set up logging
    setup_logging(config.log_level)

    logger.info(f"Starting evaluation with {len(config.llm_configs)} LLM configurations")
    logger.info(f"Test suites to run: {config.test_suites}")

    # Load test suites
    suites = load_test_suites(config.test_suites)
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

    # Load config from file if specified
    config = None
    if args.config:
        with open(args.config, "r") as f:
            config_dict = json.load(f)
            config = EvaluationConfig.from_dict(config_dict)
    else:
        config = EvaluationConfig()

    # Override with command line arguments
    if args.llm:
        # Convert LLM names to configs
        llm_configs = []
        for llm_name in args.llm:
            # Check if it's a predefined config
            if llm_name in DEFAULT_LLM_CONFIGS:
                llm_configs.append(DEFAULT_LLM_CONFIGS[llm_name])
            else:
                # Assume it's a model name for the default provider
                llm_configs.append({
                    "name": llm_name,
                    "provider": "litellm",
                    "model": llm_name,
                })
        config.llm_configs = llm_configs

    if args.suite:
        config.test_suites = args.suite

    if args.output_dir:
        config.output_dir = args.output_dir

    if args.log_level:
        config.log_level = args.log_level

    # Run evaluation
    run_evaluation(config)


if __name__ == "__main__":
    main()
