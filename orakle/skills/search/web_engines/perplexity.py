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

import json
import logging
import re
from typing import Any, Dict, List

import aiohttp

from .base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class Web_EnginesPerplexity(SearchEngineBase):
    """Perplexity AI search engine implementation using chat completions API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.perplexity.ai/chat/completions"
        self.default_model = "sonar"

        # Available models
        self.models = {
            "sonar": {"context_length": 128000, "type": "Chat Completion"},
            "sonar-pro": {"context_length": 200000, "type": "Chat Completion"},
            "sonar-reasoning": {"context_length": 128000, "type": "Chat Completion"},
            "sonar-reasoning-pro": {"context_length": 128000, "type": "Chat Completion"},
            "sonar-deep-research": {"context_length": 128000, "type": "Chat Completion"},
        }

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_search_type_specialties(self) -> List[str]:
        """Perplexity works well for news, recent, and comprehensive searches"""
        return ["news", "recent", "comprehensive"]

    def get_search_type_params(self, search_type: str) -> Dict[str, Any]:
        """Return specialized parameters for different search types"""
        if search_type == "news":
            return {
                "focus": "news",
                "search_recency_filter": "day"
            }
        elif search_type == "academic":
            return {"focus": "academic"}
        return {}

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        """Perplexity weights by search type"""
        weights = {
            "comprehensive": 0.35,
            "academic": 0.4,
            "recent": 0.5,
            "exploratory": 0.3,
            "news": 0.5
        }
        return weights.get(search_type, 0.25)

    async def search(self, query: str, num_results: int = 5, **kwargs) -> List[SearchResult]:
        """
        Perform a search using Perplexity AI's chat completions API

        Args:
            query: The search query
            num_results: Number of results to return
            **kwargs: Additional parameters:
                - model: Perplexity model to use (default: "sonar")
                - temperature: Controls randomness (default: 0.2)
                - max_tokens: Maximum tokens in response (default: 1024)
                - search_domain_filter: Filter for specific domains
                - search_recency_filter: Filter for recency
                - focus: Focus area ("web", "news", "academic", etc.) - mapped to system message

        Returns:
            List of SearchResult objects
        """
        # Get model from kwargs or use default
        model = kwargs.get("model", self.default_model)
        if model not in self.models:
            logger.warning(f"Unknown Perplexity model: {model}, falling back to {self.default_model}")
            model = self.default_model

        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Create system message based on focus if provided
        system_message = "You are a helpful search assistant. "
        if "focus" in kwargs:
            focus = kwargs["focus"]
            if focus == "news":
                system_message += "Focus on recent news articles and current events. "
            elif focus == "academic":
                system_message += "Focus on academic and scholarly sources. "

        system_message += (
            "Search the web for the query and return results in a structured format. "
            f"Return exactly {num_results} search results if possible. "
            "For each result, include the title, URL, and a brief snippet or summary. "
            "Format your response as a JSON array of objects with 'title', 'url', and 'snippet' fields."
        )

        # Build request payload
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": query}
            ],
            "temperature": kwargs.get("temperature", 0.2),
            "max_tokens": kwargs.get("max_tokens", 1024)
        }

        # Add optional parameters if provided
        if "search_domain_filter" in kwargs:
            payload["search_domain_filter"] = kwargs["search_domain_filter"]
        if "search_recency_filter" in kwargs:
            payload["search_recency_filter"] = kwargs["search_recency_filter"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_results(data, query)
                    else:
                        error_text = await response.text()
                        logger.error(f"Perplexity search failed: {response.status} - {error_text}")
                        raise Exception(f"Perplexity search failed: {response.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error in Perplexity search: {str(e)}")
            return []

    def _parse_results(self, data: Dict[str, Any], query: str) -> List[SearchResult]:
        """Parse Perplexity chat completions API response into SearchResult objects"""
        results = []

        try:
            # Extract the content from the response
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content", "")

                # Try to parse JSON from the content
                # First, find JSON array in the text if it's embedded in other text
                # Look for JSON array pattern
                json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
                if json_match:
                    try:
                        search_results = json.loads(json_match.group(0))
                    except json.JSONDecodeError:
                        # If that fails, try to parse the entire content as JSON
                        try:
                            search_results = json.loads(content)
                        except json.JSONDecodeError:
                            # If all JSON parsing fails, create a single result with the raw content
                            logger.warning("Failed to parse JSON from Perplexity response")
                            results.append(
                                SearchResult(
                                    title="Perplexity Search Results",
                                    link="",
                                    snippet=content,
                                    provider="perplexity"
                                )
                            )
                            results[0].source_engine = "perplexity"
                            results[0].relevance_score = 1.0
                            return results
                else:
                    # No JSON found, use the content as a single result
                    results.append(
                        SearchResult(
                            title="Perplexity Search Results",
                            link="",
                            snippet=content,
                            provider="perplexity"
                        )
                    )
                    results[0].source_engine = "perplexity"
                    results[0].relevance_score = 1.0
                    return results

                # Process the parsed search results
                if isinstance(search_results, list):
                    for i, item in enumerate(search_results):
                        if isinstance(item, dict):
                            result = SearchResult(
                                title=item.get("title", f"Result {i+1}"),
                                link=item.get("url", ""),
                                snippet=item.get("snippet", ""),
                                provider="perplexity"
                            )
                            # Add additional metadata
                            result.source_engine = "perplexity"
                            result.relevance_score = 0.9 - (i * 0.05)  # Decrease score slightly for each result
                            results.append(result)

            # If we couldn't extract any results, create a fallback result
            if not results:
                results.append(
                    SearchResult(
                        title=f"Perplexity Results for: {query}",
                        link="",
                        snippet="No structured results could be extracted from the Perplexity response.",
                        provider="perplexity"
                    )
                )
                results[0].source_engine = "perplexity"
                results[0].relevance_score = 0.5

        except Exception as e:
            logger.error(f"Error parsing Perplexity results: {str(e)}")
            # Create an error result
            results.append(
                SearchResult(
                    title="Error Processing Perplexity Results",
                    link="",
                    snippet=f"An error occurred while processing the search results: {str(e)}",
                    provider="perplexity"
                )
            )
            results[0].source_engine = "perplexity"
            results[0].relevance_score = 0.1

        return results
