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
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ainara.framework.config import config
from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)


class SearchProvider(Enum):
    GOOGLE = "google"


class SearchResult:
    def __init__(
        self, title: str, link: str, snippet: str, provider: SearchProvider
    ):
        self.title = title
        self.link = link
        self.snippet = snippet
        self.provider = provider

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "link": self.link,
            "snippet": self.snippet,
            "provider": self.provider.value,
        }


class SearchEngineBase(ABC):
    @abstractmethod
    async def search(
        self, query: str, num_results: int = 5
    ) -> List[SearchResult]:
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this search provider is properly configured and available"""
        pass


class GoogleSearch(SearchEngineBase):
    def __init__(self, api_key: str, cx: str):
        self.api_key = api_key
        self.cx = cx
        self.service = build("customsearch", "v1", developerKey=api_key)

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.cx)

    async def search(
        self, query: str, num_results: int = 5
    ) -> List[SearchResult]:
        try:
            res = (
                self.service.cse()
                .list(
                    q=query,
                    cx=self.cx,
                    num=min(
                        num_results, 10
                    ),  # Google CSE max is 10 per request
                )
                .execute()
            )

            results = []
            for item in res.get("items", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        link=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        provider=SearchProvider.GOOGLE,
                    )
                )
            return results

        except HttpError as e:
            logging.error(f"Google search error: {str(e)}")
            return []


class SearchWeb(Skill):
    """Search the world wide web (www) using many possible search providers"""

    def __init__(self):
        super().__init__()
        self.providers = {}
        self._initialize_providers()

    def _initialize_providers(self):
        search_config = config.get("apis.search", {})

        logging.info("Initializing search providers")
        # Initialize Google Search if configured
        google_config = search_config.get("google", {})
        if api_key := google_config.get("api_key"):
            if cx := google_config.get("cx"):
                logging.info("Initializing Google Search provider")
                self.providers[SearchProvider.GOOGLE] = GoogleSearch(
                    api_key, cx
                )

    async def run(
        self,
        query: str,
        provider: Optional[str] = None,
        num_results: int = 5,
        fallback: bool = True,
    ) -> Dict[str, Any]:
        """
        Perform **web** **search** using specified or best available provider
        **research** **internet** **searcher** **report**

        Args:
            query: Search web query string

        Returns:
            Dict containing search results
        """

        if not query or query.strip() == "":
            return {"status": "error", "message": "Query cannot be empty"}

            # provider: Specific provider to use (optional)
            # num_results: Number of results to return (optional)
            # fallback: Whether to try other providers if first choice fails (optional)
        if provider:
            try:
                provider_enum = SearchProvider(provider.lower())
                if provider_enum in self.providers:
                    results = await self.providers[provider_enum].search(
                        query, num_results
                    )
                    if results:
                        return {
                            "status": "success",
                            "provider": provider_enum.value,
                            "results": [r.to_dict() for r in results],
                        }
                    elif not fallback:
                        return {
                            "status": "error",
                            "message": f"No results from {provider}",
                        }
                else:
                    return {
                        "status": "error",
                        "message": f"Provider {provider} not available",
                    }
            except ValueError:
                return {
                    "status": "error",
                    "message": f"Unknown provider: {provider}",
                }

        # Try providers in priority order
        provider_priority = [
            SearchProvider.GOOGLE,  # First choice
        ]

        for provider in provider_priority:
            if (
                provider in self.providers
                and self.providers[provider].is_available
            ):
                results = await self.providers[provider].search(
                    query, num_results
                )
                if results:
                    return {
                        "status": "success",
                        "provider": provider.value,
                        "results": [r.to_dict() for r in results],
                    }
                elif not fallback:
                    break

        return {
            "status": "error",
            "message": "No results found from any available provider",
        }
