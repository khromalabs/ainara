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
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 10000

# Matches a string that is exactly one static placeholder, e.g.
# "{{$max_open_positions}}". Used to preserve the native value type for
# whole-placeholder skill params. Keep the inner pattern in sync with
# plan.STATIC_PLACEHOLDER_RE.
WHOLE_STATIC_PLACEHOLDER_RE = re.compile(r"^\{\{\s*\$([^{}\s]+)\s*\}\}$")


def walk_dotted_path(data: Any, parts: List[str], ref: str) -> tuple:
    """Walk dotted *parts* through nested dicts.

    Returns ``(value, error_message_or_None)``. Missing keys and null
    values are reported as errors so callers can distinguish them from
    real (falsy) values.
    """
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None, f"Static reference '{ref}': segment '{part}' not found"
        if current is None:
            return None, f"Static reference '{ref}': segment '{part}' is null"
    return current, None


class StaticBindings:
    """Per-run snapshot of plan variables and resolved config aliases.

    Static ``$name`` template references are resolved against this frozen
    snapshot (built once at plan-trigger time), never against live config.
    """

    def __init__(
        self,
        variables: Optional[Dict[str, Any]] = None,
        aliases: Optional[Dict[str, Any]] = None,
        alias_targets: Optional[Dict[str, str]] = None,
        config_root: Optional[Dict[str, Any]] = None,
    ):
        self.variables: Dict[str, Any] = variables or {}
        self.aliases: Dict[str, Any] = aliases or {}
        # Original config path each alias points to (for forensic reports).
        self.alias_targets: Dict[str, str] = alias_targets or {}
        self.config_root: Dict[str, Any] = config_root or {}

    def resolve(self, name: str, rest: List[str], ref: str) -> tuple:
        """Resolve ``$name.rest...`` against variables, aliases or config."""
        if name in self.variables:
            if rest:
                return None, (
                    f"Static reference '{ref}': variable '{name}' is a"
                    " scalar and cannot be traversed with a path"
                )
            return self.variables[name], None
        if name in self.aliases:
            if not rest:
                return self.aliases[name], None
            return walk_dotted_path(self.aliases[name], rest, ref)
        # Fallback: treat the whole ref as a full config path (e.g. $skills.…)
        return walk_dotted_path(self.config_root, [name] + rest, ref)


class Scratchpad:
    """
    Per-run key-value store for sharing data between agents in a conductor plan.

    Each agent's full result dict is stored under its name.  Template variables
    like ``{{agent_name.response}}`` are resolved by looking up
    ``data[agent_name]["response"]``.
    """

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        static_bindings: Optional[StaticBindings] = None,
    ):
        self.data: Dict[str, Dict[str, Any]] = {}
        self.max_chars = max_chars
        self.static_bindings = static_bindings

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
        * References beginning with ``$`` are static and resolved against
          the run's ``StaticBindings``, not step results.
        """
        ref = ref.strip()
        if ref.startswith("$"):
            return self._resolve_static_ref(ref)

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

        current = agent_data

        # --- walk the path --------------------------------------------------------
        for idx, part in enumerate(rest):
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
                        if isinstance(parsed, dict) and part in parsed:
                            current = parsed[part]
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass

            msg = f"Path '{ref}' not reachable: '{part}' not found"
            logger.warning("Scratchpad: %s", msg)
            return None, msg

        return current, None

    def _resolve_static_ref(self, ref: str) -> tuple:
        """Resolve a ``$name...`` reference against the run's static bindings."""
        body = ref[1:].strip()
        parts = body.split(".")
        if not body or any(not part for part in parts):
            return None, f"Invalid static reference '{ref}'"
        if self.static_bindings is None:
            return None, (
                f"Static reference '{ref}' used but this run has no static"
                " bindings available"
            )
        value, error = self.static_bindings.resolve(parts[0], parts[1:], ref)
        if error is not None:
            logger.warning("Scratchpad: %s", error)
        return value, error

    def _truncate_str(self, ref: str, text: str) -> str:
        if len(text) > self.max_chars:
            logger.warning(
                f"Scratchpad: value for '{ref}' "
                f"exceeds {self.max_chars} chars ({len(text)}), "
                "truncating for template injection"
            )
            return (
                text[: self.max_chars]
                + f"\n[truncated, {self.max_chars} char limit]"
            )
        return text

    def resolve_template(self, template: str) -> Any:
        """
        Replace ``{{agent_name.field}}`` placeholders in *template* with
        values from the scratchpad, truncating to ``self.max_chars``.

        ``{{$name}}`` / ``{{$name.path}}`` references are resolved against the
        run's static bindings (plan variables + config aliases). When the
        whole string is exactly one static placeholder, the resolved value
        keeps its native type (int/float/bool/...) instead of being
        stringified — used for skill params.
        """
        if not isinstance(template, str):
            return template

        whole = WHOLE_STATIC_PLACEHOLDER_RE.match(template.strip())
        if whole:
            ref = "$" + whole.group(1)
            value, error = self._resolve_static_ref(ref)
            if error is None and value is not None:
                if isinstance(value, str):
                    return self._truncate_str(ref, value)
                return value
            # Lenient fallback: leave the placeholder untouched.
            return template

        def _replace(match):
            ref = match.group(1).strip()
            value, error = self.resolve_dotted_path(ref)
            if value is None or error is not None:
                return match.group(0)
            return self._truncate_str(ref, str(value))

        return re.sub(r"\{\{(.+?)\}\}", _replace, template)
