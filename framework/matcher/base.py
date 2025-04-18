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

import logging
from abc import ABC, abstractmethod
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OrakleMatcherBase(ABC):
    """Base class for skill matching implementations"""

    def __init__(self):
        """Initialize the matcher"""
        self.skills_registry: Dict[str, Dict[str, Any]] = {}
        self.usage_stats = Counter()

    @abstractmethod
    def register_skill(
        self, skill_id: str, description: str, metadata: Optional[Dict] = None
    ):
        """
        Register a new skill with the matcher.

        Args:
            skill_id: Unique identifier for the skill
            description: Natural language description of the skill
            metadata: Additional skill metadata
        """
        pass

    @abstractmethod
    def match(
        self, query: str, threshold: float = 0.6, top_k: int = 5
    ) -> List[Dict]:
        """
        Find the best matching skills for a given query.

        Args:
            query: The user's query text
            threshold: Minimum similarity score threshold
            top_k: Maximum number of matches to return

        Returns:
            List of matching skills with scores
        """
        pass

    def record_usage(self, skill_id: str):
        """Record successful usage of a skill"""
        if skill_id in self.skills_registry:
            self.usage_stats[skill_id] += 1