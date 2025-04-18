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