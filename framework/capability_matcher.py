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


import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from cachetools import LRUCache
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS


class CapabilityMatcher:
    """
    Efficient capability matching using embeddings, keywords and usage
    statistics
    """

    def __init__(self, cache_size: int = 1000):
        self.logger = logging.getLogger(__name__)

        # Initialize embedding model
        self.logger.info("Initializing sentence transformer model...")
        self.encoder = SentenceTransformer("all-MiniLM-L6-v2")

        # Initialize caches and storage
        self.query_cache = LRUCache(maxsize=cache_size)
        self.skill_embeddings = {}
        self.skill_keywords = {}
        self.skill_usage_stats = {}

        # Load usage statistics if they exist
        self._load_usage_stats()

    def _load_usage_stats(self):
        """Load skill usage statistics from disk"""
        stats_file = Path(__file__).parent / "data" / "skill_usage_stats.json"
        if stats_file.exists():
            try:
                with open(stats_file) as f:
                    self.skill_usage_stats = json.load(f)
                self.logger.info("Loaded skill usage statistics")
            except Exception as e:
                self.logger.error(f"Failed to load skill usage stats: {e}")

    def _save_usage_stats(self):
        """Save skill usage statistics to disk"""
        stats_file = Path(__file__).parent / "data" / "skill_usage_stats.json"
        stats_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(stats_file, "w") as f:
                json.dump(self.skill_usage_stats, f)
            self.logger.debug("Saved skill usage statistics")
        except Exception as e:
            self.logger.error(f"Failed to save skill usage stats: {e}")

    def extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text"""
        # Convert to lowercase and split
        words = text.lower().split()
        # Remove stop words and short words
        keywords = [
            w for w in words if w not in ENGLISH_STOP_WORDS and len(w) > 2
        ]
        # Remove special characters and numbers
        keywords = [re.sub(r"[^a-z]", "", w) for w in keywords]
        # Remove empty strings
        return [w for w in keywords if w]

    def precompute_embeddings(self, skills: Dict):
        """Pre-compute embeddings for all skills and their descriptions"""
        self.logger.info("Pre-computing skill embeddings...")
        for skill_name, skill_info in skills.items():
            # Combine skill name, description and parameters for
            # richer matching
            skill_text = (
                f"{skill_name} {skill_info.get('description', '')} {' '.join(skill_info.get('parameters', []))}"
            )
            self.skill_embeddings[skill_name] = self.encoder.encode(skill_text)

            # Extract keywords for quick matching
            self.skill_keywords[skill_name] = set(
                self.extract_keywords(skill_text)
            )

        self.logger.info(f"Pre-computed embeddings for {len(skills)} skills")

    def find_matching_skill(
        self, query: str, threshold: float = 0.7
    ) -> List[Tuple[str, float]]:
        """Multi-stage matching process"""
        # Check cache first
        if query in self.query_cache:
            self.logger.debug(f"Cache hit for query: {query}")
            return self.query_cache[query]

        matches = []

        # Stage 1: Quick keyword matching
        self.logger.debug("Performing keyword matching...")
        keyword_matches = self.keyword_match(query)
        if keyword_matches:
            matches.extend(keyword_matches)
            if matches[0][1] > threshold:
                self.query_cache[query] = matches
                return matches

        # Stage 2: Semantic matching using embeddings
        self.logger.debug("Performing semantic matching...")
        query_embedding = self.encoder.encode(query)
        semantic_matches = self.semantic_match(query_embedding)
        matches.extend(semantic_matches)

        # Stage 3: Apply usage statistics and heuristics
        matches = self.apply_heuristics(matches)

        # Cache results
        self.query_cache[query] = matches
        return matches

    def keyword_match(self, query: str) -> List[Tuple[str, float]]:
        """Fast keyword-based matching"""
        query_keywords = set(self.extract_keywords(query))
        matches = []
        for skill_name, keywords in self.skill_keywords.items():
            if query_keywords and keywords:  # Avoid division by zero
                overlap = len(query_keywords & keywords) / len(query_keywords)
                if overlap > 0:
                    matches.append((skill_name, overlap))
        return sorted(matches, key=lambda x: x[1], reverse=True)

    def semantic_match(self, query_embedding) -> List[Tuple[str, float]]:
        """Compute semantic similarity using pre-computed embeddings"""
        matches = []
        for skill_name, skill_embedding in self.skill_embeddings.items():
            similarity = np.dot(query_embedding, skill_embedding) / (
                np.linalg.norm(query_embedding)
                * np.linalg.norm(skill_embedding)
            )
            matches.append((skill_name, float(similarity)))
        return sorted(matches, key=lambda x: x[1], reverse=True)

    def apply_heuristics(
        self, matches: List[Tuple[str, float]]
    ) -> List[Tuple[str, float]]:
        """Apply usage statistics and other heuristics to refine rankings"""
        weighted_matches = []
        for skill_name, score in matches:
            # Apply logarithmic weighting to usage stats to prevent domination
            usage_weight = np.log1p(self.skill_usage_stats.get(skill_name, 0))
            # Combine base score with usage weight (adjustable factor)
            final_score = score * (1 + 0.2 * usage_weight)
            weighted_matches.append((skill_name, final_score))
        return sorted(weighted_matches, key=lambda x: x[1], reverse=True)

    def update_usage_stats(self, skill_name: str):
        """Update usage statistics for a skill"""
        self.skill_usage_stats[skill_name] = (
            self.skill_usage_stats.get(skill_name, 0) + 1
        )
        self._save_usage_stats()