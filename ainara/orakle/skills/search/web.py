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


import asyncio
import datetime
import logging
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from ainara.framework.config import config
from ainara.framework.skill import Skill

from .web_engines import discover_engines
from .web_engines.base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class SearchWeb(Skill):
    """Search the internet for information about any topic or product or news or current events or just anything not present in my built-in knowledge."""

    if not config.get("apis.search"):
        hiddenCapability = True

    boostFactor = 2

    matcher_info = (
        "Primarily use when the user explicitly requests a web search,"
        " internet lookup, or research. Also consider for queries seeking"
        " information beyond built-in knowledge, such as: current events,"
        " breaking news, specific facts, product details or reviews, company"
        " information, recent developments, public opinions, diverse"
        " perspectives, real-time data, or general knowledge questions"
        " requiring external lookup."
    )

    def __init__(self):
        super().__init__()
        self.engines = {}
        self._initialize_engines()
        self.llm = None

        # Update docstring with available engines
        self._update_docstring()

    # def reload(self):
    #     super().reload(config)
    #     self._initialize_engines()

    def _initialize_engines(self):
        """Initialize search engines based on configuration"""
        search_config = config.get("apis.search", {})

        # Discover all available engine implementations
        engine_classes = discover_engines()

        # Initialize each discovered engine if configured
        for engine_name, engine_class in engine_classes.items():
            engine_config = search_config.get(engine_name, {})

            # Check if this engine has an API key configured
            if api_key := engine_config.get("api_key"):
                try:
                    # Handle special case for Google which needs both api_key and cx
                    if engine_name == "google":
                        if cx := engine_config.get("cx"):
                            self.engines[engine_name] = engine_class(
                                api_key, cx
                            )
                            logger.info("Google search engine initialized")
                    else:
                        # For other engines, just pass the API key
                        self.engines[engine_name] = engine_class(api_key)
                        logger.info(
                            f"{engine_name.capitalize()} search engine"
                            " initialized"
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to initialize {engine_name} search: {str(e)}"
                    )

        if not self.engines:
            logger.warning(
                "No search engines configured. Please add API keys to your"
                " config."
            )
        else:
            # Collect engine specialties for potential future use
            self._collect_engine_specialties()

    def _update_docstring(self):
        """Dynamically update the class docstring with available engines"""
        if not self.engines:
            self.__doc__ = (
                "Search the internet for information about any topic, product,"
                " news, current events, or factual questions. No search"
                " engines are currently configured."
            )
            return

        # Get list of available engines
        engine_names = list(self.engines.keys())
        engines_str = ", ".join(engine_names)

        # Get list of search types with specialized engines
        search_types = {}
        for engine_name, engine in self.engines.items():
            for specialty in engine.get_search_type_specialties():
                if specialty not in search_types:
                    search_types[specialty] = []
                search_types[specialty].append(engine_name)

        # Build docstring
        doc = (
            "Search the internet for information about any topic, product,"
            " news, current events, or factual questions using multiple"
            f" search providers ({engines_str})."
        )

        # Add search type specialties
        if "news" in search_types:
            news_engines = ", ".join(search_types["news"])
            doc += (
                " Use search_type='news' for specialized news search"
                f" (optimized for {news_engines})."
            )

        if "academic" in search_types:
            academic_engines = ", ".join(search_types["academic"])
            doc += (
                " Use search_type='academic' for academic research (optimized"
                f" for {academic_engines})."
            )

        if "exploratory" in search_types:
            exploratory_engines = ", ".join(search_types["exploratory"])
            doc += (
                " Use search_type='exploratory' for exploratory searches"
                f" (optimized for {exploratory_engines})."
            )

        self.__doc__ = doc

    def _collect_engine_specialties(self):
        """
        Collect search type specialties from all available engines

        This builds a mapping of search types to the engines that specialize in them,
        which can be used for intelligent engine selection.
        """
        self.engine_specialties = {}

        for name, engine in self.engines.items():
            specialties = engine.get_search_type_specialties()

            for specialty in specialties:
                if specialty not in self.engine_specialties:
                    self.engine_specialties[specialty] = []
                self.engine_specialties[specialty].append(name)

        logger.debug(f"Engine specialties: {self.engine_specialties}")

    async def initialize(self, chat_manager):
        """Initialize the skill with the chat manager"""
        # Store LLM for advanced result fusion if available
        if hasattr(chat_manager, "llm"):
            self.llm = chat_manager.llm

    async def run(
        self,
        query: Annotated[str, "Search web query string"],
        search_type: Annotated[
            Literal[
                "comprehensive", "academic", "recent", "exploratory", "news"
            ],
            "Type of search to perform",
        ] = "comprehensive",
        num_results: Annotated[int, "Number of results to return"] = 20,
        engine: Annotated[
            Optional[Union[str, List[str]]],
            "Which search engine(s) to use (single string or list of strings)."
            " If None or 'meta', uses all available engines",
        ] = None,
        recency: Annotated[
            Optional[str],
            "Filter results by recency (e.g., '24h', '7d', '1w', '1m', '1y')."
            " h=hours, d=days, w=weeks, m=months, y=years",
        ] = None,
        **kwargs: Annotated[
            Optional[Dict[str, Any]], "Additional engine-specific parameters"
        ],
    ) -> Dict[str, Any]:
        """Perform a web search or research on the Internet"""
        if not query or query.strip() == "":
            return {"status": "error", "message": "Query cannot be empty"}

        if not self.engines:
            return {
                "status": "error",
                "message": (
                    "No search engines configured. Please add API keys to your"
                    " config."
                ),
                "results": [],
            }

        # Validate search type
        valid_search_types = [
            "comprehensive",
            "academic",
            "recent",
            "exploratory",
            "news",
        ]
        if search_type not in valid_search_types:
            search_type = "comprehensive"

        # Handle engine parameter - convert to list if it's a string
        engines_to_use = []

        if engine is None or engine == "meta":
            # Use all available engines for meta search
            engines_to_use = list(self.engines.keys())
        elif isinstance(engine, list):
            # User specified a list of engines
            engines_to_use = engine
        else:
            # User specified a single engine as a string
            engines_to_use = [engine]

        # Filter to only include available engines
        available_engines = []
        for eng in engines_to_use:
            if eng in self.engines:
                available_engines.append(eng)
            else:
                logger.warning(f"Engine '{eng}' not found, skipping")

        # If no valid engines were specified, use all available
        if not available_engines:
            logger.warning(
                "No valid engines specified, using all available engines"
            )
            available_engines = list(self.engines.keys())

        # Execute search
        try:
            # Recency is already extracted as a parameter

            # If we're using multiple engines, perform meta-search
            if len(available_engines) > 1:
                results = await self._meta_search(
                    query=query,
                    num_results=num_results,
                    search_type=search_type,
                    engines=available_engines,
                    recency=recency,
                    **kwargs,
                )
            else:
                # Single engine search
                engine_name = available_engines[0]

                # Add recency parameters for single engine
                engine_kwargs = dict(kwargs)
                if recency:
                    self._add_recency_params(
                        recency,
                        [engine_name],
                        {"engine_params": engine_kwargs},
                    )
                    if f"{engine_name}_params" in engine_kwargs:
                        engine_kwargs.update(
                            engine_kwargs.pop(f"{engine_name}_params")
                        )

                results = await self.engines[engine_name].search(
                    query=query, num_results=num_results, **engine_kwargs
                )
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return {
                "status": "error",
                "message": f"Search failed: {str(e)}",
                "query": query,
                "results": [],
            }

        # Format results for return
        formatted_results = [result.to_dict() for result in results]

        return {
            "status": "success",
            "query": query,
            "results": formatted_results,
            "search_type": search_type,
            "engine": ",".join(available_engines),
            "count": len(formatted_results),
            "recency": recency,
        }

    async def _meta_search(
        self,
        query: str,
        num_results: int,
        search_type: str,
        engines: List[str],
        recency: str,
        **kwargs,
    ) -> List[SearchResult]:
        """
        Perform a meta-search across multiple engines and combine results intelligently.

        Args:
            query: The search query
            num_results: Number of results to return
            search_type: Type of search (comprehensive, academic, recent, exploratory, news)
            engines: List of engine names to use
            recency: Optional recency filter
            **kwargs: Additional parameters

        Returns:
            List of SearchResult objects
        """
        # Process recency parameter if provided
        recency = kwargs.pop("recency", None)
        if recency:
            # Add recency parameters to kwargs for each engine
            self._add_recency_params(recency, engines, kwargs)

        # Add search type specific parameters for each engine
        for engine_name in engines:
            if engine_name in self.engines:
                # Get engine-specific parameters for this search type
                engine_params = self.engines[
                    engine_name
                ].get_search_type_params(search_type)

                if engine_params:
                    # Add these parameters to the kwargs
                    kwargs.setdefault(f"{engine_name}_params", {})
                    kwargs[f"{engine_name}_params"].update(engine_params)

        # Get weights for engines based on search type
        weights = self._collect_engine_weights(search_type, engines)

        # Execute searches in parallel
        search_tasks = []
        for engine_name in engines:
            if engine_name in self.engines:
                # Request more results than needed to have margin for deduplication
                engine_num_results = int(num_results * 1.5)

                # Create search task
                task = asyncio.create_task(
                    self._search_with_engine(
                        self.engines[engine_name],
                        engine_name,
                        query,
                        engine_num_results,
                        **kwargs,
                    )
                )
                search_tasks.append(task)

        # Wait for all searches to complete
        all_results = await asyncio.gather(
            *search_tasks, return_exceptions=True
        )

        # Process results, handling any exceptions
        normalized_results = []
        for result in all_results:
            if isinstance(result, Exception):
                logger.error(f"Search engine error: {str(result)}")
                continue

            if isinstance(result, dict) and "results" in result:
                normalized_results.extend(result["results"])
            elif isinstance(result, list):
                normalized_results.extend(result)

        # Apply initial weighting to ensure specialized engines are represented
        weighted_initial_results = self._apply_initial_weighting(
            normalized_results, weights, search_type
        )

        # Determine fusion strategy based on config and LLM availability
        fusion_strategy = config.get("search.meta.fusion_strategy", "llm")

        # Apply fusion strategy
        if fusion_strategy == "llm" and self.llm:
            final_results = await self._llm_fusion(
                weighted_initial_results, query, search_type, recency, weights
            )
        elif fusion_strategy == "simple":
            final_results = self._simple_fusion(weighted_initial_results)
        else:
            # Default to weighted fusion
            final_results = self._weighted_fusion(
                weighted_initial_results, weights
            )

        # Remove duplicates
        deduplicated_results = self._remove_duplicates(final_results)

        # Limit to requested number
        return deduplicated_results[:num_results]

    async def _search_with_engine(
        self,
        engine: SearchEngineBase,
        engine_name: str,
        query: str,
        num_results: int,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute search with a specific engine and handle errors"""
        try:
            # Extract engine-specific parameters if available
            engine_params = kwargs.get(f"{engine_name}_params", {})

            # Merge with general kwargs, but engine-specific params take precedence
            search_kwargs = {**kwargs}
            search_kwargs.update(engine_params)

            # Remove all engine-specific param dictionaries to avoid confusion
            for k in list(search_kwargs.keys()):
                if k.endswith("_params"):
                    del search_kwargs[k]

            results = await engine.search(query, num_results, **search_kwargs)
            return {"engine": engine_name, "results": results}
        except Exception as e:
            logger.error(f"Error searching with {engine_name}: {str(e)}")
            return {"engine": engine_name, "results": []}

    def _simple_fusion(
        self, results: List[SearchResult]
    ) -> List[SearchResult]:
        """Simple round-robin fusion of results from different engines"""
        # Group results by engine
        engine_results = {}
        for result in results:
            engine = result.source_engine
            if engine not in engine_results:
                engine_results[engine] = []
            engine_results[engine].append(result)

        # Interleave results
        final_results = []
        max_per_engine = (
            max(len(results) for results in engine_results.values())
            if engine_results
            else 0
        )

        for i in range(max_per_engine):
            for engine in engine_results:
                if i < len(engine_results[engine]):
                    final_results.append(engine_results[engine][i])

        return final_results

    def _apply_initial_weighting(
        self,
        results: List[SearchResult],
        weights: Dict[str, float],
        search_type: str,
    ) -> List[SearchResult]:
        """Apply initial weighting to results based on engine weights and specialties"""
        # Create a copy of results with scores
        scored_results = []
        default_weight = 0.2

        # Check which engines specialize in this search type
        specialized_engines = self.engine_specialties.get(search_type, [])

        for result in results:
            engine = result.source_engine
            # Base score from engine weight
            score = weights.get(engine, default_weight)

            # Boost for specialized engines
            if engine in specialized_engines:
                score *= 1.5

            # Calculate position score (earlier results get higher scores)
            position_score = 1.0 / (results.index(result) + 1)

            # Combine scores
            final_score = score * position_score

            # Apply relevance score if available
            if hasattr(result, "relevance_score") and result.relevance_score:
                final_score *= result.relevance_score

            scored_results.append((result, final_score))

        # Sort by score (descending)
        scored_results.sort(key=lambda x: x[1], reverse=True)

        # Return just the results, without scores
        return [item[0] for item in scored_results]

    def _select_results_for_llm(
        self,
        results: List[SearchResult],
        weights: Dict[str, float],
        max_results: int = 30,
    ) -> List[SearchResult]:
        """Select a balanced set of results for LLM consideration based on engine weights"""
        if not weights or not results:
            return results[:max_results]

        # Group results by engine
        engine_results = {}
        for result in results:
            engine = result.source_engine
            if engine not in engine_results:
                engine_results[engine] = []
            engine_results[engine].append(result)

        # Calculate how many results to take from each engine based on weights
        total_weight = sum(weights.values())
        engine_allocations = {}
        for engine, weight in weights.items():
            if engine in engine_results:
                # Allocate slots proportionally to weight, with a minimum of 1
                allocation = max(1, int((weight / total_weight) * max_results))
                engine_allocations[engine] = min(
                    allocation, len(engine_results[engine])
                )

        # Adjust allocations to fit within max_results
        while sum(engine_allocations.values()) > max_results:
            # Find engine with most allocations and reduce by 1
            max_engine = max(engine_allocations.items(), key=lambda x: x[1])[0]
            engine_allocations[max_engine] -= 1

        # Select results from each engine
        selected_results = []
        for engine, allocation in engine_allocations.items():
            selected_results.extend(engine_results[engine][:allocation])

        return selected_results

    def _weighted_fusion(
        self, results: List[SearchResult], weights: Dict[str, float]
    ) -> List[SearchResult]:
        """Combine results using a weighted scoring approach"""
        scored_results = []
        default_weight = 0.2

        # Create a mapping of URLs to avoid scoring the same URL multiple times
        url_to_result = {}

        for result in results:
            # Skip results without URLs
            if not result.link:
                continue

            # Normalize URL
            norm_url = SearchEngineBase.normalize_url(result.link)

            # Calculate base score
            position_score = 1.0 / (results.index(result) + 1)

            # Get engine weight
            engine = result.source_engine
            engine_weight = weights.get(engine, default_weight)

            # Calculate final score
            final_score = position_score * engine_weight

            # Apply relevance score if available
            if hasattr(result, "relevance_score") and result.relevance_score:
                final_score *= result.relevance_score

            # If we've seen this URL before, keep the highest scoring version
            if norm_url in url_to_result:
                existing_score = url_to_result[norm_url][1]
                if final_score > existing_score:
                    url_to_result[norm_url] = (result, final_score)
            else:
                url_to_result[norm_url] = (result, final_score)

        # Convert back to a list of (result, score) tuples
        scored_results = list(url_to_result.values())

        # Sort by score (descending)
        scored_results.sort(key=lambda x: x[1], reverse=True)

        # Return just the results, without scores
        return [item[0] for item in scored_results]

    async def _llm_fusion(
        self,
        results: List[SearchResult],
        original_query: str,
        search_type: str,
        recency: str = None,
        engine_weights: Dict[str, float] = None,
    ) -> List[SearchResult]:
        """Use LLM to rerank and combine results based on relevance to query"""
        if not self.llm:
            # Fallback to weighted fusion if LLM not available
            logger.warning(
                "LLM fusion requested but no LLM available, falling back to"
                " weighted fusion"
            )
            return self._weighted_fusion(
                results,
                self._collect_engine_weights(
                    "comprehensive", list(self.engines.keys())
                ),
            )

        # Select a balanced set of results for LLM consideration based on engine weights
        results_for_llm = self._select_results_for_llm(
            results, engine_weights, max_results=30
        )

        # Prepare context for LLM
        context = f"Query: {original_query}\n\nResults:\n"

        for i, result in enumerate(results_for_llm):
            context += f"{i+1}. Title: {result.title}\n"
            context += f"   URL: {result.link}\n"
            context += f"   Snippet: {result.snippet[:200]}...\n"
            context += f"   Source: {result.source_engine}\n\n"

        # Add engine weights to context
        if engine_weights:
            context += "Engine weights for this search type:\n"
            for engine, weight in engine_weights.items():
                context += f"- {engine}: {weight}\n"
            context += "\n"

        recency_prompt = ""
        if recency:
            recency_prompt = (
                "Don't return any result older than this recency filter:"
                f" {recency} or newer than the current date which is"
                f" {datetime.datetime.now().date()}"
            )

        # Find engine with highest weight for this search type
        preferred_engine = ""
        if engine_weights:
            preferred_engine = max(engine_weights.items(), key=lambda x: x[1])[
                0
            ]

        # Ask LLM to rerank
        prompt = f"""
        {context}
        {recency_prompt}

        Based on the query and the search results above, rerank the results in order of relevance to the query.
        Prioritize these factors:
        - Compatibility with the search type intention: {search_type}
        - Direct relevance to the query
        - Source engine weight (higher weight engines like {preferred_engine} should be preferred for {search_type} searches)
        - Recency expressed in any field of the results (if applicable)
        - Information quality and comprehensiveness
        - Source credibility

        Return a JSON array with the reranked result indices, like: [3, 1, 5, 2, 4]
        Only return the JSON array, nothing else.
        """

        try:
            # Get response from LLM
            response = await self.llm.chat(
                [{"role": "user", "content": prompt}], stream=False
            )

            # Extract JSON array from response
            if isinstance(response, dict) and "content" in response:
                response_text = response["content"]
            else:
                response_text = str(response)

            # Log the LLM response for debugging
            logger.debug(f"LLM fusion response: {response_text}")

            # Find JSON array in response
            import json
            import re

            match = re.search(r"\[.*\]", response_text)
            if match:
                reranked_indices = json.loads(match.group(0))

                # Reorder results based on LLM ranking
                reranked_results = []
                for idx in reranked_indices:
                    if 0 <= idx - 1 < len(results_for_llm):
                        reranked_results.append(results_for_llm[idx - 1])

                # Add any results not included in the reranking
                included_indices = set(
                    idx - 1
                    for idx in reranked_indices
                    if 0 <= idx - 1 < len(results_for_llm)
                )
                for i, result in enumerate(results):
                    if i not in included_indices and i >= len(results_for_llm):
                        reranked_results.append(result)

                return reranked_results
            else:
                logger.warning(
                    "Could not extract JSON array from LLM response. Full"
                    f" response: {response_text}"
                )
        except Exception as e:
            logger.error(
                f"Error in LLM fusion: {str(e)}", exc_info=True
            )  # Include stack trace

        # Fallback to weighted fusion
        return self._weighted_fusion(
            results,
            self._collect_engine_weights(
                "comprehensive", list(self.engines.keys())
            ),
        )

    def _remove_duplicates(
        self, results: List[SearchResult]
    ) -> List[SearchResult]:
        """Remove duplicate  + fusion_strategyresults based on URL"""
        unique_results = []
        seen_urls = set()

        for result in results:
            # Skip results without URLs
            if not result.link:
                unique_results.append(result)
                continue

            # Normalize URL for comparison
            norm_url = SearchEngineBase.normalize_url(result.link)

            if norm_url not in seen_urls:
                seen_urls.add(norm_url)
                unique_results.append(result)

        return unique_results

    def _add_recency_params(
        self, recency: str, engines: List[str], kwargs: Dict[str, Any]
    ) -> None:
        """
        Add recency parameters to kwargs for each engine

        Args:
            recency: Recency string (e.g., "24h", "7d")
            engines: List of engine names
            kwargs: Dictionary of parameters to update
        """
        from .web_engines.base import SearchEngineBase

        # Parse recency string into date parameters
        date_params = SearchEngineBase.parse_recency(recency)
        if not date_params:
            return

        # Add engine-specific recency parameters
        for engine_name in engines:
            if engine_name not in self.engines:
                continue

            kwargs.setdefault(f"{engine_name}_params", {})

            # Handle engine-specific recency parameters
            if engine_name == "perplexity":
                # Perplexity uses search_recency_filter
                if int(recency[:-1]) <= 1 and recency[-1].lower() == "d":
                    kwargs[f"{engine_name}_params"][
                        "search_recency_filter"
                    ] = "day"
                elif int(recency[:-1]) <= 7 and recency[-1].lower() in [
                    "d",
                    "w",
                ]:
                    kwargs[f"{engine_name}_params"][
                        "search_recency_filter"
                    ] = "week"
                elif int(recency[:-1]) <= 1 and recency[-1].lower() == "m":
                    kwargs[f"{engine_name}_params"][
                        "search_recency_filter"
                    ] = "month"
                else:
                    kwargs[f"{engine_name}_params"][
                        "search_recency_filter"
                    ] = "year"

            elif engine_name == "metaphor":
                # Metaphor uses start_published_date
                kwargs[f"{engine_name}_params"]["start_published_date"] = (
                    date_params["start_date"]
                )

            elif engine_name == "tavily":
                # Tavily might use time_period (if supported)
                kwargs[f"{engine_name}_params"]["time_period"] = recency

            # Google doesn't have a direct recency filter in this implementation

    def _collect_engine_weights(
        self, search_type: str, engines: List[str]
    ) -> Dict[str, float]:
        """
        Collect weights for each engine based on search type

        Args:
            search_type: The type of search being performed
            engines: List of engine names to get weights for

        Returns:
            Dictionary mapping engine names to their weights
        """
        weights = {}

        # Try to get weights from config first
        config_weights = config.get(f"search.meta.weights.{search_type}")

        for engine_name in engines:
            if engine_name in self.engines:
                if config_weights and engine_name in config_weights:
                    # Use weight from config if available
                    weights[engine_name] = config_weights[engine_name]
                else:
                    # Otherwise use the engine's self-reported weight
                    weights[engine_name] = self.engines[
                        engine_name
                    ].get_default_weight(search_type)

        return weights
