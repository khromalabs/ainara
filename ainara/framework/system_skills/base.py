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


class BaseSystemSkill(ABC):
    """Abstract base class for system skills that run within the middleware."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The unique name/ID of the skill."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """A brief, one-line description of the skill."""
        pass

    @property
    @abstractmethod
    def matcher_info(self) -> str:
        """Detailed information for the matcher, including keywords."""
        pass

    @abstractmethod
    def run(self, query: str, parameters: dict, chat_manager=None) -> Any:
        """
        Execute the system skill's logic directly.

        Args:
            query: The original user query that triggered the skill.
            parameters: The parameters extracted by the LLM for this skill.
            chat_manager: The active ChatManager instance for context.

        Returns:
            The result of the execution, which will be passed to the
            interpretation model. This is often a list of strings or a dict.
        """
        pass

    @property
    def run_info(self) -> Dict[str, Any]:
        """Information about how to run the skill, including parameters."""
        return {}

    @property
    def full_description(self) -> str:
        """A more detailed description, often from a docstring."""
        return self.description

    @property
    def embeddings_boost_factor(self) -> float:
        """A multiplier to boost the skill's relevance in matching."""
        return 1.0

    @property
    def type(self) -> str:
        """The type of the skill."""
        return "system"

    @property
    def ui(self) -> Any:
        """UI component information, if any."""
        return None

    @property
    def vendor(self) -> str:
        """The vendor of the skill."""
        return "ainara"

    @property
    def bundle(self) -> str:
        """The bundle or package the skill belongs to."""
        return "framework"

    @property
    def parameters(self) -> list:
        """A list of parameters (legacy or simplified view)."""
        return []

    def get_definition(self) -> Dict[str, Any]:
        """Returns the skill definition as a dictionary for the framework."""
        return {
            "name": self.name,
            "description": self.description,
            "matcher_info": self.matcher_info,
            "run_info": self.run_info,
            "full_description": self.full_description,
            "embeddings_boost_factor": self.embeddings_boost_factor,
            "type": self.type,
            "ui": self.ui,
            "vendor": self.vendor,
            "bundle": self.bundle,
            "parameters": self.parameters,
        }
