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

from ainara.framework.config import nexus_prefix_from_module_name
from ainara.framework.skill_properties import ConfigurablePropertiesMixin


class Skill(ConfigurablePropertiesMixin, ABC):
    """Base class for all Orakle skills.

    Subclasses should normally only need to define:

      - ``run``
      - ``matcher_info``

    Everything else has a safe default.

    Configuration that should be exposed to the wizard/assistant is declared
    through the class-level ``_PROPERTIES`` mapping.
    """

    # ------------------------------------------------------------------
    # Optional metadata defaults
    # ------------------------------------------------------------------
    hiddenCapability = False
    embeddings_boost_factor = 1.0
    default_schedule = None

    def __init__(self):
        super().__init__()

        self.name = self.__class__.__name__
        self.connector_manager = None
        self.required_data = {}

        # Backward-compatible instance default; the class attribute above is
        # still used for discovery before instantiation.
        self.default_schedule = None

        # Used later by discovery to warn when a subclass skipped
        # ``super().__init__()``.
        self._ainara_initialized = True

        # Eagerly resolve and validate all declared `_PROPERTIES`.
        #
        # This populates `self.properties` and raises
        # ``SkillConfigurationError`` immediately when configuration is
        # invalid.
        _ = self.properties

    @classmethod
    def _get_config_prefix(cls) -> str:
        """Return the full config prefix for this skill class.

        Nexus skills will resolve:

            module: khromalabs.ataria.crypto.tradingorders
            prefix: skills.nexus.khromalabs.ataria.crypto.tradingorders

        Native/non-Nexus skills currently resolve to an empty prefix.
        """
        return nexus_prefix_from_module_name(cls.__module__)

    @property
    def description(self) -> str:
        """Return the skill description from the class docstring."""
        return self.__class__.__doc__ or ""

    @property
    @abstractmethod
    def matcher_info(self) -> str:
        """Return the matcher text used by Orakle for skill discovery."""
        raise NotImplementedError

    @abstractmethod
    def run(self):
        """Execute the skill."""
        raise NotImplementedError
