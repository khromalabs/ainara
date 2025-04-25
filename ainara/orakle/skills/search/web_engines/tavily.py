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
from typing import Any, Dict, List

import aiohttp

from .base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class Web_EnginesTavily(SearchEngineBase):
    """Tavily AI search engine implementation"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.tavily.com/search"

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_search_type_specialties(self) -> List[str]:
        """Tavily works well for comprehensive and academic searches"""
        return ["comprehensive", "academic"]

    def get_search_type_params(self, search_type: str) -> Dict[str, Any]:
        """Return specialized parameters for different search types"""
        if search_type == "news":
            return {"search_depth": "advanced"}
        return {}

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        """Tavily weights by search type"""
        weights = {
            "comprehensive": 0.35,
            "academic": 0.4,
            "recent": 0.3,
            "exploratory": 0.2,
            "news": 0.3,
        }
        return weights.get(search_type, 0.25)

    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        """
        Perform a search using Tavily AI

        Args:
            query: The search query
            num_results: Number of results to return
            **kwargs: Additional parameters:
                - search_depth: "basic" or "advanced" (default: "advanced")
                - include_domains: List of domains to include
                - exclude_domains: List of domains to exclude
                - include_answer: Whether to include a generated answer (default: False)

        Returns:
            List of SearchResult objects
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # Build request payload
        payload = {
            "query": query,
            "max_results": num_results,
            "search_depth": kwargs.get("search_depth", "advanced"),
        }

        # Add optional parameters if provided
        if "include_domains" in kwargs:
            payload["include_domains"] = kwargs["include_domains"]
        if "exclude_domains" in kwargs:
            payload["exclude_domains"] = kwargs["exclude_domains"]
        if "include_answer" in kwargs:
            payload["include_answer"] = kwargs["include_answer"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url, headers=headers, json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_results(data)
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Tavily search failed: {response.status} -"
                            f" {error_text}"
                        )
                        raise Exception(
                            f"Tavily search failed: {response.status} -"
                            f" {error_text}"
                        )
        except Exception as e:
            logger.error(f"Error in Tavily search: {str(e)}")
            return []

    def _parse_results(self, data: Dict[str, Any]) -> List[SearchResult]:
        """Parse Tavily API response into SearchResult objects"""
        results = []

        # Extract the answer if present
        answer = data.get("answer")
        if answer:
            # Create a special result for the generated answer
            answer_result = SearchResult(
                title="Tavily Generated Answer",
                link="",  # No direct link for the answer
                snippet=answer,
                provider="tavily",
            )
            answer_result.source_engine = "tavily"
            answer_result.relevance_score = (
                1.0  # Highest relevance for the direct answer
            )
            results.append(answer_result)

        # Extract regular search results
        for item in data.get("results", []):
            result = SearchResult(
                title=item.get("title", ""),
                link=item.get("url", ""),
                snippet=item.get("content", ""),
                provider="tavily",
            )
            # Add additional metadata
            result.source_engine = "tavily"
            result.relevance_score = item.get("relevance_score")
            result.published_date = item.get("published_date")

            results.append(result)

        return results