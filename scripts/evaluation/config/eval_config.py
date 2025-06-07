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
Configuration for the evaluation framework.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List


# Default tests suites to run
DEFAULT_TEST_SUITES = [
    "general_skills",
    "complex_queries",
]


@dataclass
class EvaluationConfig:
    """Configuration for evaluation runs."""

    # LLM configurations to test
    llm_configs: List[Dict] = field(default_factory=list)

    # Test suites to run
    tests: List[str] = field(default_factory=lambda: DEFAULT_TEST_SUITES)

    # Output directory for results
    output_dir: str = field(
        default_factory=lambda: os.path.join(
            os.path.expanduser("~"), ".ainara", "evaluation_results"
        )
    )

    # Matcher model to use
    matcher_model: str = "sentence-transformers/all-mpnet-base-v2"

    # Thresholds for success
    parameter_score_threshold: float = 0.7
    interpretation_score_threshold: float = 0.6

    # Logging level
    log_level: str = "INFO"

    def to_dict(self) -> Dict:
        """Convert config to dictionary."""
        return {
            "llm_configs": self.llm_configs,
            "tests": self.tests,
            "output_dir": self.output_dir,
            "matcher_model": self.matcher_model,
            "parameter_score_threshold": self.parameter_score_threshold,
            "interpretation_score_threshold": (
                self.interpretation_score_threshold
            ),
            "log_level": self.log_level,
        }

    @classmethod
    def from_dict(cls, config_dict: Dict) -> "EvaluationConfig":
        """Create config from dictionary."""
        return cls(
            llm_configs=config_dict.get("llm_configs", cls().llm_configs),
            tests=config_dict.get("tests", cls().tests),
            output_dir=config_dict.get("output_dir", cls().output_dir),
            matcher_model=config_dict.get(
                "matcher_model", cls().matcher_model
            ),
            parameter_score_threshold=config_dict.get(
                "parameter_score_threshold", cls().parameter_score_threshold
            ),
            interpretation_score_threshold=config_dict.get(
                "interpretation_score_threshold",
                cls().interpretation_score_threshold,
            ),
            log_level=config_dict.get("log_level", cls().log_level),
        )
