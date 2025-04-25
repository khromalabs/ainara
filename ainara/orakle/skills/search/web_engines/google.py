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
from typing import List

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class Web_EnginesGoogle(SearchEngineBase):
    """Google Custom Search Engine implementation"""

    def __init__(self, api_key: str, cx: str):
        self.api_key = api_key
        self.cx = cx
        self.service = build("customsearch", "v1", developerKey=api_key)

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.cx)

    def get_search_type_specialties(self) -> List[str]:
        """Google is a general-purpose search engine with no strong specialties"""
        return ["comprehensive"]

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        """Google weights by search type"""
        weights = {
            "comprehensive": 0.25,
            "academic": 0.2,
            "recent": 0.1,
            "exploratory": 0.1,
            "news": 0.1,
        }
        return weights.get(search_type, 0.25)

    async def search(
        self, query: str, num_results: int = 5, **kwargs
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
                result = SearchResult(
                    title=item.get("title", ""),
                    link=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    provider="google",
                )
                result.source_engine = "google"
                results.append(result)
            return results

        except HttpError as e:
            logger.error(f"Google search error: {str(e)}")
            return []