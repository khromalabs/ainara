# Ainara AI Companion Framework Projecta
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

import aiohttp

from .base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class Web_EnginesGuavy(SearchEngineBase):
    """Guavy search engine implementation for crypto news and market sentiment"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://data.guavy.com/api/v1"

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_search_type_specialties(self) -> List[str]:
        return ["crypto", "news", "recent"]

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        weights = {
            "crypto": 1.0,
            "news": 0.6,
            "recent": 0.5,
            "comprehensive": 0.2,
        }
        return weights.get(search_type, 0.1)

    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        results = []
        async with aiohttp.ClientSession(headers=headers) as session:
            # Step 1: Try to identify a crypto symbol from the query
            # We take the first word or the whole query to search for an instrument
            search_term = query.split()[0] if len(query.split()) > 3 else query

            symbol = None
            try:
                async with session.get(
                    f"{self.base_url}/instruments/search-instruments/{search_term}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        instruments = data.get("instruments", [])
                        if instruments:
                            symbol = instruments[0].get("symbol")
            except Exception as e:
                logger.warning(f"Guavy instrument search failed: {e}")

            # Step 2: Fetch data based on whether we found a symbol
            try:
                if symbol:
                    # Fetch specific coin briefs
                    url = f"{self.base_url}/newsroom/search-briefs/{symbol}?keywords={query}&limit={num_results}"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for brief in data.get("briefs", [])[:num_results]:
                                snippet = (
                                    f"{brief.get('body', '')} | Sentiment:"
                                    f" {brief.get('sentiment', 0)} | Bias:"
                                    f" {brief.get('fud_fomo_bias', 'neutral')}"
                                )
                                results.append(
                                    SearchResult(
                                        title=(
                                            f"[{symbol}]"
                                            f" {brief.get('title', '')}"
                                        ),
                                        link=(  # Guavy doesn't provide direct source URLs, using placeholder
                                            f"https://guavy.com/article/{brief.get('article_id', '')}"
                                        ),
                                        snippet=snippet,
                                        provider="guavy",
                                    )
                                )

                # Fallback or if no results: Get general market summary
                if not results:
                    async with session.get(
                        f"{self.base_url}/newsroom/get-market-summary"
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            results.append(
                                SearchResult(
                                    title=(
                                        "Guavy Crypto Market Summary"
                                        f" ({data.get('date', '')})"
                                    ),
                                    link="https://guavy.com",
                                    snippet=data.get("summary", ""),
                                    provider="guavy",
                                )
                            )
            except Exception as e:
                logger.error(f"Guavy data fetch failed: {e}")

        for r in results:
            r.source_engine = "guavy"

        return results
