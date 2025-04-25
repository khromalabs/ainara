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


class Web_EnginesMetaphor(SearchEngineBase):
    """Metaphor search engine implementation"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.metaphor.systems/search"

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_search_type_specialties(self) -> List[str]:
        """Metaphor works well for exploratory and conceptual searches"""
        return ["exploratory"]

    def get_search_type_params(self, search_type: str) -> Dict[str, Any]:
        """Return specialized parameters for different search types"""
        if search_type == "news":
            from datetime import datetime, timedelta
            # Default to news from the last 7 days
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            return {"start_published_date": start_date}
        return {}

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        """Metaphor weights by search type"""
        weights = {
            "comprehensive": 0.3,
            "academic": 0.2,
            "recent": 0.2,
            "exploratory": 0.5,
            "news": 0.2
        }
        return weights.get(search_type, 0.25)

    async def search(self, query: str, num_results: int = 5, **kwargs) -> List[SearchResult]:
        """
        Perform a search using Metaphor

        Args:
            query: The search query
            num_results: Number of results to return
            **kwargs: Additional parameters:
                - use_autoprompt: Whether to use Metaphor's autoprompt feature (default: True)
                - start_published_date: Filter for content published after this date
                - end_published_date: Filter for content published before this date
                - include_domains: List of domains to include
                - exclude_domains: List of domains to exclude

        Returns:
            List of SearchResult objects
        """
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }

        # Build request payload
        payload = {
            "query": query,
            "numResults": num_results,
            "useAutoprompt": kwargs.get("use_autoprompt", True)
        }

        # Add optional date filters
        if "start_published_date" in kwargs:
            payload["startPublishedDate"] = kwargs["start_published_date"]
        if "end_published_date" in kwargs:
            payload["endPublishedDate"] = kwargs["end_published_date"]

        # Add domain filters
        if "include_domains" in kwargs:
            payload["includeDomains"] = kwargs["include_domains"]
        if "exclude_domains" in kwargs:
            payload["excludeDomains"] = kwargs["exclude_domains"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_results(data)
                    else:
                        error_text = await response.text()
                        logger.error(f"Metaphor search failed: {response.status} - {error_text}")
                        raise Exception(f"Metaphor search failed: {response.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error in Metaphor search: {str(e)}")
            return []

    async def get_contents(self, urls: List[str]) -> Dict[str, str]:
        """
        Get the contents of specific URLs using Metaphor's contents endpoint

        Args:
            urls: List of URLs to fetch content for

        Returns:
            Dictionary mapping URLs to their extracted content
        """
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }

        payload = {
            "urls": urls
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.metaphor.systems/contents",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {item["url"]: item["extract"] for item in data["contents"]}
                    else:
                        error_text = await response.text()
                        logger.error(f"Metaphor contents fetch failed: {response.status} - {error_text}")
                        raise Exception(f"Metaphor contents fetch failed: {response.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error fetching Metaphor contents: {str(e)}")
            return {}

    def _parse_results(self, data: Dict[str, Any]) -> List[SearchResult]:
        """Parse Metaphor API response into SearchResult objects"""
        results = []

        for item in data.get("results", []):
            result = SearchResult(
                title=item.get("title", ""),
                link=item.get("url", ""),
                snippet=item.get("extract", ""),
                provider="metaphor"
            )
            # Add additional metadata
            result.source_engine = "metaphor"
            result.published_date = item.get("publishedDate")
            result.author = item.get("author")

            results.append(result)

        return results