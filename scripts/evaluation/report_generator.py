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
Generate reports from evaluation results.
"""

import csv
# import json
import os
from datetime import datetime
from typing import Dict


def generate_report(results: Dict, output_dir: str) -> str:
    """
    Generate a comprehensive report from evaluation results.

    Args:
        results: Evaluation results dictionary
        output_dir: Directory to save the report

    Returns:
        Path to the generated report file
    """
    # Create timestamp for report files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Generate CSV report
    csv_path = os.path.join(output_dir, f"evaluation_report_{timestamp}.csv")
    _generate_csv_report(results, csv_path)

    # Generate markdown report
    md_path = os.path.join(output_dir, f"evaluation_report_{timestamp}.md")
    _generate_markdown_report(results, md_path)

    # Return path to markdown report as the main report
    return md_path


def _generate_csv_report(results: Dict, output_path: str) -> None:
    """
    Generate a CSV report from evaluation results.

    Args:
        results: Evaluation results dictionary
        output_path: Path to save the CSV file
    """
    with open(output_path, 'w', newline='') as csvfile:
        # Create CSV writer
        writer = csv.writer(csvfile)

        # Write header
        writer.writerow([
            "LLM", "Test Suite", "Test Case",
            "Skill Selection Correct", "Parameter Score", "Interpretation Score",
            "Overall Success", "Total Duration (s)"
        ])

        # Write data for each LLM and test case
        for llm_name, llm_results in results.get("llm_results", {}).items():
            if "error" in llm_results:
                # Skip LLMs with errors
                continue

            for suite_name, suite_results in llm_results.get("suites", {}).items():
                for test_result in suite_results.get("test_case_results", []):
                    # Extract metrics
                    skill_correct = test_result.get("metrics", {}).get("selection", {}).get("skill_selection_correct", 0)
                    param_score = test_result.get("metrics", {}).get("selection", {}).get("parameter_score", 0)
                    interp_score = test_result.get("metrics", {}).get("interpretation", {}).get("keyword_match_rate", 0)
                    overall_success = test_result.get("metrics", {}).get("overall_success", 0)

                    # Calculate total duration
                    total_duration = (
                        test_result.get("metrics", {}).get("matching", {}).get("duration", 0) +
                        test_result.get("metrics", {}).get("selection", {}).get("duration", 0) +
                        test_result.get("metrics", {}).get("interpretation", {}).get("duration", 0)
                    )

                    # Write row
                    writer.writerow([
                        llm_name,
                        suite_name,
                        test_result.get("test_id", "unknown"),
                        skill_correct,
                        f"{param_score:.2f}",
                        f"{interp_score:.2f}",
                        overall_success,
                        f"{total_duration:.2f}"
                    ])

        # Write aggregate metrics
        writer.writerow([])
        writer.writerow(["LLM", "Success Rate", "Skill Selection", "Parameter Score", "Interpretation Score", "Avg Duration (s)"])

        for llm_name, metrics in results.get("aggregate_metrics", {}).get("llm_comparison", {}).items():
            writer.writerow([
                llm_name,
                f"{metrics.get('success_rate', 0):.2f}",
                f"{metrics.get('skill_selection_accuracy', 0):.2f}",
                f"{metrics.get('avg_parameter_score', 0):.2f}",
                f"{metrics.get('avg_interpretation_score', 0):.2f}",
                f"{metrics.get('avg_duration', 0):.2f}"
            ])


def _generate_markdown_report(results: Dict, output_path: str) -> None:
    """
    Generate a markdown report from evaluation results.

    Args:
        results: Evaluation results dictionary
        output_path: Path to save the markdown file
    """
    with open(output_path, 'w') as mdfile:
        # Write header
        mdfile.write("# Ainara Orakle LLM Evaluation Report\n\n")

        # Write metadata
        metadata = results.get("metadata", {})
        mdfile.write(f"**Generated:** {metadata.get('timestamp', datetime.now().isoformat())}\n")
        mdfile.write(f"**Duration:** {metadata.get('duration', 0):.2f} seconds\n\n")

        # Write summary
        aggregate = results.get("aggregate_metrics", {})
        mdfile.write("## Summary\n\n")

        if aggregate.get("best_overall"):
            mdfile.write(f"- **Best Overall LLM:** {aggregate.get('best_overall')}\n")
            mdfile.write(f"- **Best Skill Selection:** {aggregate.get('best_skill_selection')}\n")
            mdfile.write(f"- **Best Parameter Extraction:** {aggregate.get('best_parameter_extraction')}\n")
            mdfile.write(f"- **Best Result Interpretation:** {aggregate.get('best_interpretation')}\n")
            mdfile.write(f"- **Fastest LLM:** {aggregate.get('fastest')}\n\n")
        else:
            mdfile.write("No aggregate metrics available.\n\n")

        # Write comparison table
        mdfile.write("## LLM Comparison\n\n")
        mdfile.write("| LLM | Success Rate | Skill Selection | Parameter Score | Interpretation Score | Avg Duration (s) |\n")
        mdfile.write("|-----|-------------|----------------|-----------------|----------------------|------------------|\n")

        for llm_name, metrics in aggregate.get("llm_comparison", {}).items():
            mdfile.write(
                f"| {llm_name} | "
                f"{metrics.get('success_rate', 0):.2f} | "
                f"{metrics.get('skill_selection_accuracy', 0):.2f} | "
                f"{metrics.get('avg_parameter_score', 0):.2f} | "
                f"{metrics.get('avg_interpretation_score', 0):.2f} | "
                f"{metrics.get('avg_duration', 0):.2f} |\n"
            )

        mdfile.write("\n")

        # Write detailed results for each LLM
        mdfile.write("## Detailed Results\n\n")

        for llm_name, llm_results in results.get("llm_results", {}).items():
            mdfile.write(f"### {llm_name}\n\n")

            if "error" in llm_results:
                mdfile.write(f"**Error:** {llm_results['error']}\n\n")
                continue

            # Write suite results
            for suite_name, suite_results in llm_results.get("suites", {}).items():
                mdfile.write(f"#### Test Suite: {suite_name}\n\n")
                mdfile.write(f"*{suite_results.get('description', '')}*\n\n")

                # Write suite metrics
                metrics = suite_results.get("metrics", {})
                mdfile.write(f"- **Success Rate:** {metrics.get('success_rate', 0):.2f}\n")
                mdfile.write(f"- **Tests:** {metrics.get('successful_tests', 0)}/{metrics.get('total_tests', 0)}\n")
                mdfile.write(f"- **Skill Selection Accuracy:** {metrics.get('skill_selection_accuracy', 0):.2f}\n")
                mdfile.write(f"- **Avg Parameter Score:** {metrics.get('avg_parameter_score', 0):.2f}\n")
                mdfile.write(f"- **Avg Interpretation Score:** {metrics.get('avg_interpretation_score', 0):.2f}\n")
                mdfile.write(f"- **Avg Duration:** {metrics.get('avg_duration', 0):.2f} seconds\n\n")

                # Write test case table
                mdfile.write("| Test Case | Success | Skill Selection | Parameter Score | Interpretation Score |\n")
                mdfile.write("|-----------|---------|----------------|-----------------|----------------------|\n")

                for test_result in suite_results.get("test_case_results", []):
                    test_id = test_result.get("test_id", "unknown")
                    success = "✅" if test_result.get("metrics", {}).get("overall_success", 0) == 1 else "❌"
                    skill_correct = "✅" if test_result.get("metrics", {}).get("selection", {}).get("skill_selection_correct", 0) == 1 else "❌"
                    param_score = test_result.get("metrics", {}).get("selection", {}).get("parameter_score", 0)
                    interp_score = test_result.get("metrics", {}).get("interpretation", {}).get("keyword_match_rate", 0)

                    mdfile.write(
                        f"| {test_id} | {success} | {skill_correct} | "
                        f"{param_score:.2f} | {interp_score:.2f} |\n"
                    )

                mdfile.write("\n")

        # Write conclusion
        mdfile.write("## Conclusion\n\n")

        if aggregate.get("best_overall"):
            best_llm = aggregate.get("best_overall")
            best_metrics = aggregate.get("llm_comparison", {}).get(best_llm, {})

            mdfile.write(
                f"Based on the evaluation results, **{best_llm}** performed best overall "
                f"with a success rate of {best_metrics.get('success_rate', 0):.2f}. "
                f"It achieved a skill selection accuracy of {best_metrics.get('skill_selection_accuracy', 0):.2f}, "
                f"parameter extraction score of {best_metrics.get('avg_parameter_score', 0):.2f}, and "
                f"interpretation score of {best_metrics.get('avg_interpretation_score', 0):.2f}.\n\n"
            )

            # Add recommendations
            mdfile.write("### Recommendations\n\n")

            if aggregate.get("fastest") != best_llm:
                fastest = aggregate.get("fastest")
                fastest_metrics = aggregate.get("llm_comparison", {}).get(fastest, {})

                mdfile.write(
                    f"- For performance-critical applications, consider using **{fastest}** "
                    f"which was {best_metrics.get('avg_duration', 0) / fastest_metrics.get('avg_duration', 1):.1f}x "
                    f"faster than {best_llm} while still achieving a success rate of "
                    f"{fastest_metrics.get('success_rate', 0):.2f}.\n"
                )
