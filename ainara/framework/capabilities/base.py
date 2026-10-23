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
from typing import Any, Dict, Optional, Tuple

# Valid surface modes for skills that declare a UI component
# (docs/proposals/nexus-panel-mode.md, issue #29). Binary by design:
# two behaviors means two components.
UI_MODES = ("view", "panel")


def resolve_ui_mode(cap_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve the declared surface mode for a skill with a UI component.

    The mode is declared by the skill author as the ``ui_mode`` class
    attribute on the skill (``"view"`` or ``"panel"``). Undeclared means
    ``"view"`` — byte-identical behavior for every skill shipped before
    the declaration existed.

    Fail-closed (issue #29): an unknown declared value is never silently
    coerced to a default. The caller receives an error and must drop the
    skill's UI association (the skill keeps working headless), recording
    it as a load error.

    Returns:
        (mode, error): ``mode`` is "view" or "panel", or None when the
        declaration is invalid (then ``error`` describes why).
    """
    instance = cap_data.get("instance")
    declared = getattr(instance, "ui_mode", None)
    if declared is None:
        return "view", None
    if declared not in UI_MODES:
        return None, (
            f"invalid ui_mode {declared!r} (expected one of"
            f" {', '.join(UI_MODES)})"
        )
    return declared, None


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
