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


class Web_EnginesBrave(SearchEngineBase):
    """Brave Search engine implementation using the Brave Search API"""

    # TODO: The free tier is limited (roughly 1 request/second and a monthly
    # query quota). Add retry-with-backoff and rate-limit handling, and honor
    # rate limit headers, once needed.

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_search_type_specialties(self) -> List[str]:
        """Brave is a solid general-purpose engine with good recency support"""
        return ["recent", "comprehensive"]

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        """Brave weights by search type"""
        weights = {
            "comprehensive": 0.7,
            "recent": 0.6,
            "news": 0.4,
            "exploratory": 0.4,
        }
        return weights.get(search_type, 0.25)

    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        """
        Perform a search using the Brave Search API

        Args:
            query: The search query
            num_results: Number of results to return (Brave caps at 20 per
                request)
            **kwargs: Additional parameters:
                - freshness: Time filter ("pd" = last 24h, "pw" = last 7 days,
                  "pm" = last 31 days, "py" = last year). Usually injected by
                  SearchWeb's recency handling.
                - country: Country code (e.g. "us")
                - search_lang: Search language (e.g. "en")
                - safesearch: "off", "moderate" or "strict"

        Returns:
            List of SearchResult objects
        """
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }

        # Brave caps results per request at 20
        count = max(1, min(num_results, 20))

        params: Dict[str, Any] = {"q": query, "count": count}

        # Optional parameters if provided
        if "freshness" in kwargs and kwargs["freshness"]:
            params["freshness"] = kwargs["freshness"]
        if "country" in kwargs and kwargs["country"]:
            params["country"] = kwargs["country"]
        if "search_lang" in kwargs and kwargs["search_lang"]:
            params["search_lang"] = kwargs["search_lang"]
        if "safesearch" in kwargs and kwargs["safesearch"]:
            params["safesearch"] = kwargs["safesearch"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.base_url, headers=headers, params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_results(data)
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Brave search failed: {response.status} -"
                            f" {error_text}"
                        )
                        raise Exception(
                            f"Brave search failed: {response.status} -"
                            f" {error_text}"
                        )
        except Exception as e:
            logger.error(f"Error in Brave search: {str(e)}")
            return []

    def _parse_results(self, data: Dict[str, Any]) -> List[SearchResult]:
        """Parse Brave API response into SearchResult objects"""
        results = []

        try:
            web_results = data.get("web", {}).get("results", [])

            for i, item in enumerate(web_results):
                result = SearchResult(
                    title=item.get("title", f"Result {i+1}"),
                    link=item.get("url", ""),
                    snippet=item.get("description", ""),
                    provider="brave",
                )
                result.source_engine = "brave"
                result.relevance_score = max(0.1, 0.9 - (i * 0.05))
                results.append(result)

            if not results:
                logger.warning("Brave response contained no web results")

            # TODO: The response also contains other sections we could exploit
            # in the future, e.g. data["news"]["results"] (to specialize in the
            # "news" search type using Brave's news index) and
            # data["infobox"] (structured summaries that could enrich results).
        except Exception as e:
            logger.error(f"Error parsing Brave results: {str(e)}")

        return results
