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
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Sample user-contributed search engine for Ainara's meta-search skill.

Copy this file into the directory configured as
``search.web.user_engines_directory`` (settable in the setup wizard's
Skills tab, or directly in ainara.yaml) and restart Orakle. No API key
is required.

Contract reference: docs/architecture/meta-search.md. The essentials:

- The FILE NAME is the engine key: this file becomes the engine
  ``wikipedia_search``, reads its settings from the
  ``apis.search.wikipedia_search`` config section, and those settings
  are passed to the constructor as keyword arguments. The name must not
  shadow an existing module (stdlib, installed package or core engine):
  such files are refused with a clear error at startup.
- Keyless engines set ``REQUIRES_API_KEY = False`` and decide their own
  availability via the ``is_available`` property (here: always
  available; a self-hosted MediaWiki would instead require base_url).
- ``PARTICIPATION = "specialty"`` means the engine only joins searches
  whose ``search_type`` matches one of its declared specialties. The
  ``"encyclopedia"`` specialty declared below CREATES a new search_type
  value dynamically: the LLM-facing capability schema is rebuilt at
  Orakle startup so queries like "look up X in the encyclopedia" are
  routed with ``search_type="encyclopedia"`` and served exclusively by
  this engine (general searches are not diluted with wiki results).
  This is the recommended mode for vertical sources. The alternative,
  ``PARTICIPATION = "weighted"``, makes the engine join EVERY
  meta-search with influence scaled by ``get_default_weight()`` — the
  right choice for a general-purpose provider (another web index, a
  private corpus) that should enrich all queries, at the cost of its
  results appearing on every search. Both modes are equally allowed for
  user-contributed engines: pick the one that matches what the source
  is for.
- ``search()`` must degrade silently: log and return [] on failure —
  the meta-search must survive one broken engine.
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from ainara.orakle.skills.search.web_engines.base import (
    SearchEngineBase,
    SearchResult,
)

logger = logging.getLogger(__name__)


class WikipediaSearch(SearchEngineBase):
    """Wikipedia (MediaWiki) full-text search engine

    Keyless engine against the public Wikipedia API by default; point
    ``base_url`` at any MediaWiki installation (Wiktionary, a self-hosted
    wiki, a Miraheze farm, ...) to search it instead.
    """

    REQUIRES_API_KEY = False

    # Only joins encyclopedia-typed searches (search_type="encyclopedia",
    # a type this engine itself creates) or when explicitly requested by
    # name via the "engine" parameter.
    PARTICIPATION = "specialty"

    DEFAULT_API_PATH = "/w/api.php"

    # Truncate page extracts to keep snippets LLM-friendly
    SNIPPET_MAX_CHARS = 400

    def __init__(
        self,
        base_url: Optional[str] = None,
        language: str = "en",
        api_path: Optional[str] = None,
    ):
        # Config section keys arrive as constructor kwargs, e.g.
        #   apis.search.wikipedia_search:
        #     base_url: https://es.wikipedia.org
        # Wikimedia projects host each language edition on its own
        # subdomain, so the default base URL is derived from `language`.
        # Self-hosted wikis: set base_url to the wiki root (and api_path
        # if the API is not at the standard /w/api.php location).
        self.base_url = (base_url or "").rstrip("/") or None
        self.api_path = (api_path or self.DEFAULT_API_PATH).rstrip("/")
        self.language = language or "en"

    @property
    def is_available(self) -> bool:
        # No credentials needed: always join the pool when discovered
        return True

    def get_search_type_specialties(self) -> List[str]:
        # Declaring "encyclopedia" creates that search_type dynamically
        return ["encyclopedia"]

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        # Sole engine for its vertical, so it can carry full influence
        return 1.0

    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        """
        Search a MediaWiki installation (Wikipedia by default)

        Args:
            query: The search query
            num_results: Number of results to return
            **kwargs: Additional parameters (unused; accepted so unexpected
                parameters from the meta-search never break the engine)

        Returns:
            List of SearchResult objects (empty on any failure)
        """
        base = self.base_url or f"https://{self.language}.wikipedia.org"
        params: Dict[str, Any] = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": max(1, min(num_results, 50)),
            "prop": "extracts|info",
            "inprop": "url",
            "exintro": 1,
            "explaintext": 1,
            "redirects": 1,
        }
        url = f"{base}{self.api_path}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    headers={"User-Agent": "AinaraMetaSearch/1.0"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status != 200:
                        logger.error(
                            f"wikipedia_search: HTTP {response.status} from"
                            f" {base}"
                        )
                        return []
                    data = await response.json()
                    return self._parse_results(data, num_results)
        except Exception as e:
            # Degrade silently: the meta-search must survive one broken
            # engine
            logger.error(f"wikipedia_search failed: {e}")
            return []

    def _parse_results(
        self, data: Dict[str, Any], num_results: int
    ) -> List[SearchResult]:
        """Parse the MediaWiki generator=search JSON into SearchResults"""
        results: List[SearchResult] = []
        pages = (data.get("query") or {}).get("pages") or {}

        # MediaWiki returns pages keyed by id; sort by index to keep the
        # API's own relevance order
        for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
            if len(results) >= num_results:
                break

            title = page.get("title", "")
            link = page.get("fullurl", "")
            extract = (page.get("extract") or "").strip()
            snippet = extract[: self.SNIPPET_MAX_CHARS]
            if len(extract) > self.SNIPPET_MAX_CHARS:
                snippet += "…"

            result = SearchResult(
                title=title,
                link=link,
                snippet=snippet or "(no intro text available)",
                provider="wikipedia",
            )
            result.source_engine = "wikipedia_search"
            # Preserve the API's relevance ranking
            result.relevance_score = max(
                0.1, 1.0 - 0.05 * page.get("index", 1)
            )
            # Engine-defined structured metadata (consumers treat unknown
            # keys as opaque; the human-readable essentials above are also
            # surfaced in snippet, which is what fusion and synthesis use)
            result.metadata = {
                "source": "wikipedia",
                "page_id": page.get("pageid"),
                "language": self.language,
            }
            results.append(result)

        if not results:
            logger.info("wikipedia_search: no results")
        return results
