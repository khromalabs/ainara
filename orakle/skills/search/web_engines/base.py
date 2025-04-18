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


from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class SearchResult:
    def __init__(
        self, title: str, link: str, snippet: str, provider: str
    ):
        self.title = title
        self.link = link
        self.snippet = snippet
        self.provider = provider

        # Additional fields that may be populated by specific engines
        self.relevance_score = None
        self.source_engine = None
        self.published_date = None
        self.author = None
        self.image_url = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.link,
            "snippet": self.snippet,
            "engine": self.source_engine or self.provider,
            "relevance_score": self.relevance_score,
            "published_date": self.published_date,
            "author": self.author,
            "image_url": self.image_url
        }


class SearchEngineBase(ABC):
    """Base class for all search engine implementations"""
    
    @abstractmethod
    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        """
        Search for the given query and return a list of search results
        
        Args:
            query: The search query
            num_results: Number of results to return
            **kwargs: Additional engine-specific parameters
            
        Returns:
            List of SearchResult objects
        """
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this search provider is properly configured and available"""
        pass
    
    def get_search_type_specialties(self) -> List[str]:
        """
        Return list of search types this engine specializes in
        
        Override this method to indicate which search types this engine performs well with.
        Default implementation returns an empty list (no specialization).
        """
        return []
    
    def get_search_type_params(self, search_type: str) -> Dict[str, Any]:
        """
        Return engine-specific parameters for a given search type
        
        Override this method to provide specialized parameters for different search types.
        Default implementation returns an empty dict (no special parameters).
        """
        return {}
    
    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        """
        Return default weight for this engine for a given search type
        
        Override this method to provide custom weights for different search types.
        Default implementation returns 0.25 (equal weighting for up to 4 engines).
        """
        return 0.25
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize URL to identify duplicates despite minor differences"""
        # Remove protocol
        norm_url = url.lower()
        for prefix in ['https://', 'http://', 'www.']:
            if norm_url.startswith(prefix):
                norm_url = norm_url[len(prefix):]

        # Remove trailing slash
        if norm_url.endswith('/'):
            norm_url = norm_url[:-1]

        # Remove common tracking parameters
        if '?' in norm_url:
            base_url, params = norm_url.split('?', 1)
            return base_url

        return norm_url
        
    @staticmethod
    def parse_recency(recency: str) -> dict:
        """
        Parse recency string into date parameters
        
        Args:
            recency: String like "24h", "7d", "1w", "1m", "1y"
                    (h=hours, d=days, w=weeks, m=months, y=years)
                    
        Returns:
            Dictionary with start_date and end_date (if applicable)
        """
        from datetime import datetime, timedelta
        
        if not recency:
            return {}
            
        now = datetime.now()
        unit = recency[-1].lower()
        try:
            value = int(recency[:-1])
        except ValueError:
            return {}
            
        if unit == 'h':
            delta = timedelta(hours=value)
        elif unit == 'd':
            delta = timedelta(days=value)
        elif unit == 'w':
            delta = timedelta(weeks=value)
        elif unit == 'm':
            delta = timedelta(days=value*30)  # Approximate
        elif unit == 'y':
            delta = timedelta(days=value*365)  # Approximate
        else:
            return {}
            
        start_date = now - delta
        
        return {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": now.strftime("%Y-%m-%d")
        }