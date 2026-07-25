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
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


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
        # Plan-level input variables. Seeded into the scratchpad under "vars" at
        # run start so step params can reference {{vars.<name>}} (e.g. a coin the
        # whole plan is parameterized on). Defaults defined here; a run may
        # override any of them (conductor.trigger_plan(vars=...)).
        self.vars: Dict[str, Any] = {}
        self.steps: Dict[str, StepNode] = {}

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

        # Optional plan-level input variables (a flat mapping of scalars). Keep it
        # flat: the scratchpad resolves one level ({{vars.coin}}), so nested
        # values could not be referenced anyway.
        vars_raw = self.raw.get("vars", {}) or {}
        if not isinstance(vars_raw, dict):
            raise PlanValidationError(
                f"Plan '{self.name}': 'vars' must be a mapping"
            )
        for k, v in vars_raw.items():
            if isinstance(v, (dict, list)):
                raise PlanValidationError(
                    f"Plan '{self.name}': vars.{k} must be a scalar"
                    " (vars are single-level; {{vars.name}} resolves one level)"
                )
        self.vars = dict(vars_raw)

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
                # Parse the reference: "step_name.response.some.path"
                parts = avoid_path.split(".")
                if len(parts) < 2:
                    raise PlanValidationError(
                        f"Plan '{self.name}': step '{step.name}' has invalid "
                        f"avoid_step_if='{avoid_path}'. "
                        "Expected format: 'step_name.response.path'"
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
