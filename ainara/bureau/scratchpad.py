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

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 10000


class Scratchpad:
    """
    Per-run key-value store for sharing data between agents in a conductor plan.

    Each agent's full result dict is stored under its name.  Template variables
    like ``{{agent_name.response}}`` are resolved by looking up
    ``data[agent_name]["response"]``.
    """

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS):
        self.data: Dict[str, Dict[str, Any]] = {}
        self.max_chars = max_chars

    def store(self, agent_name: str, result: Dict[str, Any]) -> None:
        """Store an agent's result dict."""
        self.data[agent_name] = result
        logger.debug(f"Scratchpad: stored result for '{agent_name}'")

    def get(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve an agent's stored result."""
        return self.data.get(agent_name)

    def resolve_template(self, template: str) -> str:
        """
        Replace ``{{agent_name.field}}`` placeholders in *template* with
        values from the scratchpad, truncating to ``self.max_chars``.
        """
        import re

        def _replace(match):
            ref = match.group(1).strip()
            parts = ref.split(".", 1)
            if len(parts) != 2:
                logger.warning(f"Scratchpad: invalid template ref '{ref}'")
                return match.group(0)

            agent_name, field = parts
            agent_data = self.data.get(agent_name)
            if agent_data is None:
                logger.warning(f"Scratchpad: no data for agent '{agent_name}'")
                return match.group(0)

            value = agent_data.get(field)
            if value is None:
                logger.warning(
                    f"Scratchpad: no field '{field}' for agent '{agent_name}'"
                )
                return match.group(0)

            text = str(value)
            if len(text) > self.max_chars:
                logger.warning(
                    f"Scratchpad: value for '{agent_name}.{field}' "
                    f"exceeds {self.max_chars} chars ({len(text)}), "
                    "truncating for template injection"
                )
                text = (
                    text[: self.max_chars]
                    + f"\n[truncated, {self.max_chars} char limit]"
                )
            return text

        return re.sub(r"\{\{(.+?)\}\}", _replace, template)
