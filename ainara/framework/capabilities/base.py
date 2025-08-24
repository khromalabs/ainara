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
from typing import Any, Dict


class CapabilityProvider(ABC):
    """Abstract base class for capability providers."""

    @abstractmethod
    def discover(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover and load capabilities of this provider's type.

        Returns:
            A dictionary of capabilities, where the key is the capability name
            and the value is a dictionary of its properties.
        """
        pass

    @abstractmethod
    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Execute a capability by its name.

        Args:
            name: The name of the capability to execute.
            arguments: The arguments to pass to the capability.

        Returns:
            The result of the execution.
        """
        pass

    @abstractmethod
    def format_for_llm(self, capability_data: Dict[str, Any]) -> str:
        """
        Format a single capability's description for an LLM prompt.

        Args:
            capability_data: The data dictionary for a single capability.

        Returns:
            A formatted string describing the capability.
        """
        pass
