# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import aiohttp

from .base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class Web_EnginesNewsapi(SearchEngineBase):
    """NewsAPI implementation for news-specific searches"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://newsapi.org/v2"

    @property
    def is_available(self) -> bool:
        """Check if this search provider is properly configured and available"""
        return bool(self.api_key)

    def get_search_type_specialties(self) -> List[str]:
        """NewsAPI specializes in news searches"""
        return ["news", "recent"]

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        """NewsAPI weights by search type"""
        weights = {
            "news": 0.9,  # Highest weight for news searches
            "recent": 0.7,  # Good for recent content
            "comprehensive": 0.3,
            "academic": 0.1,
            "exploratory": 0.2,
        }
        return weights.get(search_type, 0.3)

    def get_search_type_params(self, search_type: str) -> Dict[str, Any]:
        """Return engine-specific parameters for a given search type"""
        params = {}

        if search_type == "news":
            # Default to top headlines for news search type
            params["endpoint"] = "top-headlines"
            params["country"] = "us"  # Default country
        else:
            # Use everything endpoint for other search types
            params["endpoint"] = "everything"

        return params

    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        """
        Search for news articles using NewsAPI

        Args:
            query: The search query
            num_results: Number of results to return
            **kwargs: Additional parameters:
                - endpoint: 'everything' or 'top-headlines' (default: 'everything')
                - language: Language code (default: 'en')
                - country: Country code for top-headlines (default: None)
                - sources: Comma-separated list of news sources (default: None)
                - domains: Comma-separated list of domains (default: None)
                - from_date: Start date in YYYY-MM-DD format (default: 7 days ago)
                - to_date: End date in YYYY-MM-DD format (default: today)
                - sort_by: 'relevancy', 'popularity', or 'publishedAt' (default: 'publishedAt')

        Returns:
            List of SearchResult objects
        """
        try:
            # Determine which endpoint to use
            endpoint = kwargs.get("endpoint", "everything")

            # Build request parameters
            params = {
                "apiKey": self.api_key,
                "pageSize": min(
                    num_results, 100
                ),  # NewsAPI max is 100 per request
                "page": 1,
            }

            # Add query parameter (required for 'everything', optional for 'top-headlines')
            if endpoint == "everything" or query:
                params["q"] = query

            # Add optional parameters
            if language := kwargs.get("language"):
                params["language"] = language
            else:
                params["language"] = "en"  # Default to English

            if endpoint == "top-headlines" and (
                country := kwargs.get("country")
            ):
                params["country"] = country

            if sources := kwargs.get("sources"):
                params["sources"] = sources

            if domains := kwargs.get("domains"):
                params["domains"] = domains

            # Handle date parameters
            if from_date := kwargs.get("from_date"):
                params["from"] = from_date
            else:
                # Default to 7 days ago
                week_ago = datetime.now() - timedelta(days=7)
                params["from"] = week_ago.strftime("%Y-%m-%d")

            if to_date := kwargs.get("to_date"):
                params["to"] = to_date

            # Handle sorting
            if sort_by := kwargs.get("sort_by"):
                if (
                    endpoint == "everything"
                ):  # sort_by only works with 'everything' endpoint
                    params["sortBy"] = sort_by
            elif endpoint == "everything":
                params["sortBy"] = "publishedAt"  # Default to most recent

            # Make the API request
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/{endpoint}"
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(
                            f"NewsAPI error: {response.status} - {error_text}"
                        )
                        return []

                    data = await response.json()

                    if data.get("status") != "ok":
                        logger.error(
                            "NewsAPI returned error:"
                            f" {data.get('message', 'Unknown error')}"
                        )
                        return []

                    return self._parse_results(data)

        except Exception as e:
            logger.error(f"NewsAPI search error: {str(e)}")
            return []

    def _parse_results(self, data: Dict[str, Any]) -> List[SearchResult]:
        """Parse NewsAPI response into SearchResult objects"""
        results = []

        for article in data.get("articles", []):
            # Create basic search result
            result = SearchResult(
                title=article.get("title", ""),
                link=article.get("url", ""),
                snippet=article.get("description", ""),
                provider="newsapi",
            )

            # Add additional fields
            result.source_engine = "newsapi"
            result.published_date = article.get("publishedAt")
            result.author = article.get("author")
            result.image_url = article.get("urlToImage")

            # Add source information to snippet if available
            source_name = article.get("source", {}).get("name")
            if source_name and not result.snippet.startswith(
                f"[{source_name}]"
            ):
                result.snippet = f"[{source_name}] {result.snippet}"

            # Add content if available and snippet is empty
            if not result.snippet and article.get("content"):
                result.snippet = article.get("content")

            results.append(result)

        return results
