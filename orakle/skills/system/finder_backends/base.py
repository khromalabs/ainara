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

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclass
class SearchResult:
    """Unified search result across all backends"""
    path: Path
    name: str
    type: str
    size: int
    created: datetime
    modified: datetime
    snippet: Optional[str] = None
    metadata: Dict[str, Any] = None
    score: float = 0.0


class SearchBackend(ABC):
    """Abstract base class for search backends"""
    
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the search backend"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available on the current system"""
        pass
    
    @abstractmethod
    async def search(
        self,
        params: Dict[str, Any],
        limit: int = 5
    ) -> List[SearchResult]:
        """Perform search using backend"""
        pass
