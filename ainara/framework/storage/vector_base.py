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
from typing import List, Dict, Any, Optional


class VectorStorageBackend(ABC):
    """Abstract base class for vector storage backends."""

    @abstractmethod
    def add_documents(self, documents: List[Dict[str, Any]]) -> List[str]:
        """Add documents to the vector store."""
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar documents."""
        pass

    @abstractmethod
    def delete(self, ids: List[str]) -> None:
        """Delete documents by their IDs."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Delete all data from the storage."""
        pass
