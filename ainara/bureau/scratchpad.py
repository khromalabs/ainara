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

import json
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

    def resolve_dotted_path(self, ref: str) -> tuple:
        """
        Resolve a dotted reference ``agent_name.path.to.key`` against
        the stored results. Returns ``(value, error_message_or_None)``.
        If the path cannot be resolved, *value* is ``None`` and
        *error_message* describes the problem.

        * The ``response`` field is automatically parsed as JSON when
          encountered along the path.
        * If the first segment after the agent name is not found but
          the agent result has a ``response`` key containing valid
          JSON, that JSON is parsed and the path is attempted inside
          it. (Common when a step's output is entirely inside its
          ``response`` JSON.)
        """
        parts = ref.split(".")
        if len(parts) < 2:
            msg = f"Invalid dotted reference '{ref}' (need at least agent.field)"
            logger.warning("Scratchpad: %s", msg)
            return None, msg

        agent_name = parts[0]
        rest = parts[1:]

        # --- resolve agent data -------------------------------------------------
        agent_data = self.data.get(agent_name)
        if agent_data is None:
            msg = f"No data for agent '{agent_name}' in reference '{ref}'"
            logger.warning("Scratchpad: %s", msg)
            return None, msg

        logger.info("Resolving '%s': agent_data keys=%s", ref, list(agent_data.keys()))

        current = agent_data

        # --- walk the path --------------------------------------------------------
        for idx, part in enumerate(rest):
            logger.info(
                "  segment[%d]='%s', current_type=%s, current_keys=%s",
                idx,
                part,
                type(current).__name__,
                list(current.keys()) if isinstance(current, dict) else "N/A",
            )
            if isinstance(current, dict) and part in current:
                current = current[part]
                # auto‑parse JSON response strings
                if part == "response" and isinstance(current, str):
                    try:
                        current = json.loads(current)
                    except (json.JSONDecodeError, TypeError):
                        pass  # leave as string
                continue

            # ---- fallback for missing key at first segment -----------------------
            if idx == 0 and isinstance(current, dict) and "response" in current:
                response_val = current["response"]
                if isinstance(response_val, str):
                    try:
                        parsed = json.loads(response_val)
                        logger.info(
                            "  fallback: parsing response JSON, keys=%s",
                            list(parsed.keys()),
                        )
                        if isinstance(parsed, dict) and part in parsed:
                            logger.info(
                                "  fallback: found '%s' in parsed response, setting current=parsed[part]",
                                part,
                            )
                            current = parsed[part]
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass

            msg = f"Path '{ref}' not reachable: '{part}' not found"
            logger.warning("Scratchpad: %s", msg)
            return None, msg

        return current, None

    def resolve_template(self, template: str) -> str:
        """
        Replace ``{{agent_name.field}}`` placeholders in *template* with
        values from the scratchpad, truncating to ``self.max_chars``.
        """
        import re

        def _replace(match):
            ref = match.group(1).strip()
            value, error = self.resolve_dotted_path(ref)
            if value is None or error is not None:
                return match.group(0)

            text = str(value)
            if len(text) > self.max_chars:
                logger.warning(
                    f"Scratchpad: value for '{ref}' "
                    f"exceeds {self.max_chars} chars ({len(text)}), "
                    "truncating for template injection"
                )
                text = (
                    text[: self.max_chars]
                    + f"\n[truncated, {self.max_chars} char limit]"
                )
            return text

        return re.sub(r"\{\{(.+?)\}\}", _replace, template)
