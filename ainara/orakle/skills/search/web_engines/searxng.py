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
from typing import Any, Dict, List, Optional

import aiohttp

from .base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class Web_EnginesSearxng(SearchEngineBase):
    """SearXNG search engine implementation (self-hosted metasearch engine)

    SearXNG is keyless: it queries a user-provided (usually local) instance.
    Note the instance must allow JSON output: add "json" to the
    "search.formats" list in the instance's settings.yml, otherwise requests
    with format=json are rejected (HTTP 403).

    The engine is opt-in: SearchWeb only instantiates it when
    apis.search.searxng.base_url is configured (leave it empty to disable
    SearXNG entirely). In practice base_url is the only setting most users
    need; api_key is entirely optional and rarely required (only for
    instances behind an authenticated reverse proxy).
    """

    # Classic searx/searxng service default. Note the official SearXNG Docker
    # image instead exposes the instance on port 8080; adjust via config if
    # needed.
    DEFAULT_BASE_URL = "http://127.0.0.1:8888"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        category_map: Optional[Dict[str, str]] = None,
    ):
        # Normalize trailing slashes so we can safely append "/search"
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
        # Optional mapping from SearchWeb search types to SearXNG categories,
        # e.g. {"news": "news", "academic": "science"}
        self.category_map = category_map or {}

    @property
    def is_available(self) -> bool:
        # SearXNG requires no credentials; a base_url is always present
        # (defaulted), so the engine is considered available
        return True

    def get_search_type_specialties(self) -> List[str]:
        """Specialties depend on the per-instance category configuration"""
        return list(self.category_map.keys())

    def get_search_type_params(self, search_type: str) -> Dict[str, Any]:
        """
        Map SearchWeb search types to SearXNG categories

        The mapping is configurable per instance via the "categories" config
        section. Unmapped search types fall back to the instance's default
        (general) category.
        """
        if search_type in self.category_map:
            return {"categories": self.category_map[search_type]}
        return {}

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        # Local instance: no quotas or rate limits to worry about, so it can
        # carry a relatively high weight
        return 0.6

    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        """
        Perform a search using a SearXNG instance

        Args:
            query: The search query
            num_results: Number of results to return
            **kwargs: Additional parameters:
                - categories: SearXNG category override (e.g. "news",
                  "science"). Usually injected by SearchWeb via the configured
                  category mapping.
                - time_range: "day", "week", "month" or "year". Usually
                  injected by SearchWeb's recency handling.
                - language: Language code (e.g. "en")
                - safesearch: 0 (off), 1 (moderate), 2 (strict)

        Returns:
            List of SearchResult objects
        """
        params: Dict[str, Any] = {
            "q": query,
            "format": "json",
        }

        # Optional parameters if provided
        if "categories" in kwargs and kwargs["categories"]:
            params["categories"] = kwargs["categories"]
        if "time_range" in kwargs and kwargs["time_range"]:
            params["time_range"] = kwargs["time_range"]
        if "language" in kwargs and kwargs["language"]:
            params["language"] = kwargs["language"]
        if "safesearch" in kwargs and kwargs["safesearch"]:
            params["safesearch"] = kwargs["safesearch"]

        headers = {"Accept": "application/json"}
        if self.api_key:
            # Only needed when the instance sits behind a reverse proxy with
            # token auth; plain SearXNG instances require no key
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/search"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_results(data, num_results)
                    elif response.status == 403:
                        # Common misconfiguration: JSON output not enabled on
                        # the instance. Log a clear hint before the generic
                        # error path.
                        error_text = await response.text()
                        logger.error(
                            "SearXNG returned 403. Most likely the JSON output"
                            " format is disabled on this instance: add 'json'"
                            " to the 'search.formats' list in the instance's"
                            " settings.yml and restart it. Response:"
                            f" {error_text}"
                        )
                        raise Exception(
                            f"SearXNG search failed: {response.status} -"
                            f" {error_text}"
                        )
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"SearXNG search failed: {response.status} -"
                            f" {error_text}"
                        )
                        raise Exception(
                            f"SearXNG search failed: {response.status} -"
                            f" {error_text}"
                        )
        except Exception as e:
            logger.error(f"Error in SearXNG search: {str(e)}")
            return []

    def _parse_results(
        self, data: Dict[str, Any], num_results: int
    ) -> List[SearchResult]:
        """Parse SearXNG JSON response into SearchResult objects"""
        results = []

        try:
            # SearXNG has no "count" parameter; the first page typically
            # returns 20-30 results, so slice down to what was requested.
            # TODO: Add pagination via the "pageno" parameter if larger
            # num_results values need to be fully honored.
            for i, item in enumerate(data.get("results", [])):
                if len(results) >= num_results:
                    break

                result = SearchResult(
                    title=item.get("title", f"Result {i+1}"),
                    link=item.get("url", ""),
                    snippet=item.get("content", ""),
                    provider="searxng",
                )
                result.source_engine = "searxng"
                result.relevance_score = max(0.1, 0.9 - (i * 0.05))
                if item.get("publishedDate"):
                    result.published_date = item["publishedDate"]
                results.append(result)

            if not results:
                logger.warning("SearXNG response contained no results")
        except Exception as e:
            logger.error(f"Error parsing SearXNG results: {str(e)}")

        return results
