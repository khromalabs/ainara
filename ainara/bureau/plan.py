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
import re
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger(__name__)

# Binding names must be simple identifiers (no dots) so that the first
# segment of a static reference unambiguously identifies the binding.
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Static template references: {{$name}} or {{$name.path.to.key}}. The first
# segment is a binding name (variables / config_aliases) or a config root
# ('skills'); remaining segments are config keys (kept permissive).
STATIC_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*\$([A-Za-z_][A-Za-z0-9_]*(?:\.[^\s.${}]+)*)\s*\}\}"
)


class PlanValidationError(Exception):
    """Raised when a plan YAML is invalid."""


class StepNode:
    """Represents a single step (agent or skill) within a plan's DAG."""

    def __init__(
        self,
        name: str,
        definition: Dict[str, Any],
        plan_defaults: Dict[str, Any],
    ):
        self.name = name
        self.type: str = definition.get("type", "agent")
        self.depends_on: List[str] = definition.get("depends_on", [])
        self.execution_timeout = definition.get(
            "execution_timeout", plan_defaults.get("execution_timeout", 300)
        )

        # avoid_step_if: optional dot-path(s) into another step's result.
        # When present, if ANY resolved value is truthy, this step is skipped.
        # Format: "step_name.response.some.path" or a list of such strings.
        avoid_if_raw = definition.get("avoid_step_if")
        if isinstance(avoid_if_raw, str):
            self.avoid_step_if: List[str] = [avoid_if_raw]
        elif isinstance(avoid_if_raw, list):
            self.avoid_step_if: List[str] = avoid_if_raw
        else:
            self.avoid_step_if: List[str] = []

        if self.type == "agent":
            self.blueprint = definition.get("blueprint", {})
            self.goal_template = definition.get("goal", "")
            self.max_turns = definition.get(
                "max_turns", plan_defaults.get("max_turns", 20)
            )
            self.skill: Optional[str] = None
            self.params: Optional[Dict[str, Any]] = None
        elif self.type == "skill":
            self.skill = definition.get("skill")
            self.params = definition.get("params", {})
            self.blueprint = {}
            self.goal_template = ""
            self.max_turns = 0
        else:
            raise PlanValidationError(
                f"Step '{name}' has unknown type '{self.type}'. "
                "Supported types: 'agent', 'skill'."
            )


def iter_static_refs(steps: Dict[str, StepNode]) -> List[Tuple[str, str]]:
    """
    Collect ``(step_name, ref_body)`` pairs for every static ``{{$...}}``
    reference used in agent goals, agent blueprint system messages and
    skill string params. *ref_body* excludes the leading ``$``.
    """
    found: List[Tuple[str, str]] = []
    for step in steps.values():
        texts: List[str] = []
        if step.type == "agent":
            texts.append(step.goal_template)
            system_message = step.blueprint.get("system_message")
            if isinstance(system_message, str):
                texts.append(system_message)
        elif step.type == "skill":
            # TODO: Only top-level string params are scanned. Static refs
            # inside nested dicts/lists (e.g.
            # params: {filters: {min: "{{$x}}"}}) escape both this
            # load-time validation and the Conductor preflight, and are
            # sent to the skill verbatim. See the matching TODO in
            # Conductor._spawn_skill; fix both together.
            for param_value in (step.params or {}).values():
                if isinstance(param_value, str):
                    texts.append(param_value)
        for text in texts:
            for match in STATIC_PLACEHOLDER_RE.finditer(text):
                found.append((step.name, match.group(1)))
    return found


class Plan:
    """
    A conductor plan loaded from a YAML file.

    Parses the YAML, validates the DAG structure, and provides helpers
    for resolving execution waves (groups of agents that can run in parallel).
    """

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.name = filepath.stem
        self.raw: Dict[str, Any] = {}
        self.on_failure: str = "notify"
        self.max_parallel: int = 4
        self.scratchpad_max_chars: int = 10000
        self.defaults: Dict[str, Any] = {}
        self.steps: Dict[str, StepNode] = {}
        self.variables: Dict[str, Any] = {}
        self.config_aliases: Dict[str, str] = {}

        self._load()
        self._validate()

    def _resolve_includes(self, text: str) -> str:
        """Replace !include directives with referenced file contents, in-memory only."""
        pattern = re.compile(r"^\s*!include\s+(.+)\s*$", re.MULTILINE)

        def replacer(match):
            filepath = self.filepath.parent / match.group(1).strip()
            try:
                return filepath.read_text(encoding="utf-8")
            except FileNotFoundError:
                raise PlanValidationError(
                    f"Include file not found: {filepath}"
                )

        return pattern.sub(replacer, text)

    def _load(self) -> None:
        """Load and parse the YAML file."""
        try:
            raw_text = self._resolve_includes(
                self.filepath.read_text(encoding="utf-8")
            )
            logger.debug(f"== CONDUCTOR PLAN {self.filepath} =========")
            logger.debug(raw_text)
            logger.debug("========================")
            self.raw = yaml.safe_load(raw_text) or {}
        except PlanValidationError:
            raise
        except Exception as e:
            raise PlanValidationError(
                f"Failed to read plan file '{self.filepath}': {e}"
            )

        if not isinstance(self.raw, dict):
            raise PlanValidationError(
                f"Plan file '{self.filepath}' must contain a YAML mapping"
            )

        # Optional top-level fields
        self.on_failure = self.raw.get("on_failure", "notify")
        self.max_parallel = self.raw.get("max_parallel", 4)
        self.scratchpad_max_chars = self.raw.get("scratchpad_max_chars", 10000)
        self.defaults = self.raw.get("defaults", {})
        # avoid_report_if (optional) – a single condition string
        self.avoid_report_if = self.raw.get("avoid_report_if")

        # Optional static bindings
        variables_raw = self.raw.get("variables") or {}
        aliases_raw = self.raw.get("config_aliases") or {}
        if not isinstance(variables_raw, dict):
            raise PlanValidationError(
                f"Plan '{self.name}': 'variables' must be a mapping of"
                " name -> scalar"
            )
        if not isinstance(aliases_raw, dict):
            raise PlanValidationError(
                f"Plan '{self.name}': 'config_aliases' must be a mapping of"
                " name -> config path"
            )
        self.variables = variables_raw
        self.config_aliases = aliases_raw

        # Steps (required)
        steps_raw = self.raw.get("steps")
        if not steps_raw or not isinstance(steps_raw, dict):
            raise PlanValidationError(
                f"Plan '{self.name}' must define a 'steps' mapping"
            )

        for step_name, step_def in steps_raw.items():
            if not isinstance(step_def, dict):
                raise PlanValidationError(
                    f"Step '{step_name}' in plan '{self.name}' must be a"
                    " mapping"
                )
            node = StepNode(step_name, step_def, self.defaults)
            if node.type == "skill" and not node.skill:
                raise PlanValidationError(
                    f"Skill step '{step_name}' in plan '{self.name}' "
                    "must define a 'skill' field"
                )
            if node.type == "agent" and not node.goal_template:
                raise PlanValidationError(
                    f"Agent step '{step_name}' in plan '{self.name}' "
                    "must define a 'goal' field"
                )
            self.steps[step_name] = node

    def _validate(self) -> None:
        """Validate DAG: check references and detect cycles."""
        step_names = set(self.steps.keys())

        for step in self.steps.values():
            for dep in step.depends_on:
                if dep not in step_names:
                    raise PlanValidationError(
                        f"Plan '{self.name}': step '{step.name}' depends on "
                        f"unknown step '{dep}'"
                    )

        # Cycle detection via topological sort (Kahn's algorithm)
        in_degree = {name: 0 for name in step_names}
        adjacency: Dict[str, List[str]] = {name: [] for name in step_names}

        for step in self.steps.values():
            for dep in step.depends_on:
                adjacency[dep].append(step.name)
                in_degree[step.name] += 1

        queue = deque(name for name, deg in in_degree.items() if deg == 0)
        visited = 0

        while queue:
            node = queue.popleft()
            visited += 1
            for child in adjacency[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if visited != len(step_names):
            raise PlanValidationError(
                f"Plan '{self.name}': dependency cycle detected in step DAG"
            )

        # Validate avoid_step_if references
        for step in self.steps.values():
            if not step.avoid_step_if:
                continue

            for avoid_path in step.avoid_step_if:
                # Strip leading negation prefix if present
                cleaned_path = avoid_path
                if avoid_path.startswith('not '):
                    cleaned_path = avoid_path[4:].strip()
                    if not cleaned_path:
                        raise PlanValidationError(
                            f"Plan '{self.name}': step '{step.name}' has "
                            "empty path after 'not' in avoid_step_if"
                        )

                # Parse the reference: "step_name.response.some.path"
                parts = cleaned_path.split(".")
                if len(parts) < 2:
                    raise PlanValidationError(
                        f"Plan '{self.name}': step '{step.name}' has invalid "
                        f"avoid_step_if='{avoid_path}'. "
                        "Expected format: 'step_name.response.path' "
                        "(or 'not step_name.response.path')"
                    )

                referenced_step = parts[0]

                # Check that the referenced step exists
                if referenced_step not in step_names:
                    raise PlanValidationError(
                        f"Plan '{self.name}': step '{step.name}' references "
                        f"unknown step '{referenced_step}' in avoid_step_if"
                    )

                # Check that the referenced step is in the dependency chain
                if not self._is_transitive_dependency(
                    step.name, referenced_step
                ):
                    raise PlanValidationError(
                        f"Plan '{self.name}': step '{step.name}' has"
                        f" avoid_step_if referencing '{referenced_step}', but"
                        " that step is not in its dependency chain. Add"
                        f" '{referenced_step}' to depends_on (directly or"
                        " transitively)."
                    )

        # --- Static bindings (variables / config_aliases) validation ---
        var_names = set(self.variables.keys())
        alias_names = set(self.config_aliases.keys())

        for name in var_names | alias_names:
            if not IDENTIFIER_RE.match(str(name)):
                raise PlanValidationError(
                    f"Plan '{self.name}': binding name '{name}' is invalid; "
                    "use simple identifiers (letters, digits, underscores; "
                    "no dots)"
                )

        duplicates = var_names & alias_names
        if duplicates:
            raise PlanValidationError(
                f"Plan '{self.name}': names defined in both 'variables' and "
                f"'config_aliases': {sorted(duplicates)}"
            )

        for name, value in self.variables.items():
            if value is None or isinstance(value, (dict, list)):
                raise PlanValidationError(
                    f"Plan '{self.name}': variable '{name}' must be a scalar"
                    f" (str/int/float/bool), got {type(value).__name__}"
                )
            if isinstance(value, str) and STATIC_PLACEHOLDER_RE.search(value):
                raise PlanValidationError(
                    f"Plan '{self.name}': variable '{name}' contains a"
                    " {{$...}} reference; chained definitions are not"
                    " supported"
                )

        for name, target in self.config_aliases.items():
            if not isinstance(target, str) or not target.strip():
                raise PlanValidationError(
                    f"Plan '{self.name}': config alias '{name}' must map to"
                    " a non-empty config path string"
                )
            if target.strip().startswith("$"):
                raise PlanValidationError(
                    f"Plan '{self.name}': config alias '{name}' target must"
                    " be a raw config path without the leading '$'"
                )

        # --- Static reference scan: catch unknown names at load time ---
        allowed_roots = var_names | alias_names | {"skills"}
        for step_name, body in iter_static_refs(self.steps):
            root = body.split(".")[0]
            if root not in allowed_roots:
                raise PlanValidationError(
                    f"Plan '{self.name}': step '{step_name}' uses unknown"
                    f" static reference '${body}'. It must start with a"
                    " 'variables' name, a 'config_aliases' name, or"
                    " 'skills' (full config path)"
                )

    def _is_transitive_dependency(
        self, step_name: str, potential_dep: str
    ) -> bool:
        """
        Check if potential_dep is a transitive dependency of step_name.
        Uses BFS to traverse the dependency graph backwards.
        """
        if step_name == potential_dep:
            return False

        visited = set()
        queue = [step_name]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            step = self.steps.get(current)
            if not step:
                continue

            for dep in step.depends_on:
                if dep == potential_dep:
                    return True
                if dep not in visited:
                    queue.append(dep)

        return False

    def get_root_steps(self) -> List[str]:
        """Return step names with no dependencies (DAG roots)."""
        return [
            name for name, step in self.steps.items() if not step.depends_on
        ]

    def get_ready_steps(self, completed: Set[str]) -> List[str]:
        """
        Return step names whose dependencies are all in *completed*
        and that haven't been completed themselves yet.
        """
        ready = []
        for name, step in self.steps.items():
            if name in completed:
                continue
            if all(dep in completed for dep in step.depends_on):
                ready.append(name)
        return ready
