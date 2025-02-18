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
