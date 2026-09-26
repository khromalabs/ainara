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

import re
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Set, Type

from ainara.framework.config import config, nexus_prefix_from_module_name


class SkillConfigurationError(Exception):
    """Raised when a skill declares invalid or unsupported configuration properties."""


class ConfigurablePropertiesMixin:
    """Reusable support for declarative, class-level `_PROPERTIES`.

    A class using this mixin may declare a mapping like:

        class MySkill(ConfigurablePropertiesMixin):
            _PROPERTIES = {
                "risk.max_leverage": {
                    "type": "number",
                    "default": 5.0,
                    "minimum": 1.0,
                    "maximum": 50.0,
                    "title": "Max leverage",
                    "description": "Longer documentation for this property.",
                }
            }

    The mixin provides:

      - `get_config_properties()`: normalized descriptors for capability
        discovery and wizard rendering.
      - `properties`: a read-only mapping of resolved values.
    """

    _PROPERTIES: Dict[str, Any] = {}

    # --- NEW: Runtime Registry ---
    _runtime_registry: Dict[str, Set[Type["ConfigurablePropertiesMixin"]]] = {}

    def __init_subclass__(cls, **kwargs):
        """Automatically register subclasses for runtime discovery."""
        super().__init_subclass__(**kwargs)
        module_name = cls.__module__
        registry = ConfigurablePropertiesMixin._runtime_registry
        if module_name not in registry:
            registry[module_name] = set()
        registry[module_name].add(cls)
    # -----------------------------

    # ------------------------------------------------------------------
    # Prefix handling
    # ------------------------------------------------------------------

    @classmethod
    def _get_config_prefix(cls) -> str:
        """Return the Nexus config key prefix for this class.

        Classes in ``ainara.nexus.*`` modules are scoped under
        ``skills.nexus.*``. Non-Nexus classes keep an empty prefix.
        """
        return nexus_prefix_from_module_name(cls.__module__)

    @classmethod
    def _get_full_key(cls, prop_name: str) -> str:
        prefix = cls._get_config_prefix()
        if prefix:
            return f"{prefix}.{prop_name}"
        return prop_name

    # ------------------------------------------------------------------
    # Schema normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_type_from_default(default: Any) -> Optional[str]:
        if isinstance(default, bool):
            return "boolean"
        if isinstance(default, int):
            return "integer"
        if isinstance(default, float):
            return "number"
        if isinstance(default, str):
            return "string"
        if isinstance(default, list):
            return "array"
        if isinstance(default, dict):
            return "object"
        return None

    @classmethod
    def _normalize_schema(cls, prop_name: str, raw_schema: Any) -> Dict[str, Any]:
        """Validate and complete a single property schema."""
        if not isinstance(raw_schema, dict):
            raise SkillConfigurationError(
                f"Property '{prop_name}' must be a dict, got "
                f"{type(raw_schema).__name__}"
            )

        schema = dict(raw_schema)

        if not schema.get("title"):
            raise SkillConfigurationError(
                f"Property '{prop_name}' must define a non-empty 'title'"
            )

        # Validate that composite keys are lists when present
        for key in ("anyOf", "oneOf", "allOf"):
            if key in schema and not isinstance(schema[key], list):
                raise SkillConfigurationError(
                    f"Property '{prop_name}' must define '{key}' as a list"
                )

        if "type" not in schema:
            if any(key in schema for key in ("anyOf", "oneOf", "allOf")):
                # Derive a primary display type from the first non-null branch.
                # The anyOf/oneOf/allOf schema is still preserved for validation.
                primary = None
                branches = []
                for key in ("anyOf", "oneOf", "allOf"):
                    branches.extend(schema.get(key, []))

                for branch in branches:
                    if not isinstance(branch, dict):
                        continue
                    branch_type = branch.get("type")
                    if isinstance(branch_type, list):
                        branch_type = next(
                            (t for t in branch_type if t != "null"), None
                        )
                    if branch_type and branch_type != "null":
                        primary = branch_type
                        break

                if primary is None and any(
                    isinstance(b, dict) and b.get("type") == "null"
                    for b in branches
                ):
                    primary = "null"

                schema["type"] = primary or "string"
            else:
                inferred = cls._infer_type_from_default(schema.get("default"))
                if not inferred:
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' must define 'type', "
                        "'anyOf'/'oneOf', or have a default from which "
                        "a type can be inferred"
                    )
                schema["type"] = inferred

        schema.setdefault("description", "")
        return schema

    # ------------------------------------------------------------------
    # Value validation
    # ------------------------------------------------------------------

    @staticmethod
    def _value_matches_type(expected_type: str, value: Any) -> bool:
        """Return whether `value` matches a single JSON Schema type name."""
        if expected_type == "null":
            return value is None
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "number":
            return not isinstance(value, bool) and isinstance(value, (int, float))
        if expected_type == "integer":
            return not isinstance(value, bool) and isinstance(value, int)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        # Unknown type names are ignored so valid custom schemas don't break.
        return True

    @classmethod
    def _validate_common_constraints(
        cls,
        prop_name: str,
        schema: Dict[str, Any],
        value: Any,
    ) -> None:
        """Validate enum/minimum/maximum/pattern at any schema level."""
        if "enum" in schema and value not in schema["enum"]:
            raise SkillConfigurationError(
                f"Property '{prop_name}' value {value!r} is not in enum "
                f"{schema['enum']!r}"
            )

        if "minimum" in schema and value is not None:
            try:
                if value < schema["minimum"]:
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' value {value!r} is below "
                        f"minimum {schema['minimum']!r}"
                    )
            except TypeError:
                pass

        if "maximum" in schema and value is not None:
            try:
                if value > schema["maximum"]:
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' value {value!r} is above "
                        f"maximum {schema['maximum']!r}"
                    )
            except TypeError:
                pass

        if "pattern" in schema and isinstance(value, str):
            if not re.fullmatch(schema["pattern"], value):
                raise SkillConfigurationError(
                    f"Property '{prop_name}' value {value!r} does not match "
                    f"pattern {schema['pattern']!r}"
                )

    @classmethod
    def _validate_simple_schema(
        cls,
        prop_name: str,
        schema: Dict[str, Any],
        value: Any,
    ) -> None:
        """Validate a schema fragment that has no anyOf/oneOf/allOf."""
        expected_type = schema.get("type")

        if isinstance(expected_type, list):
            if not any(cls._value_matches_type(t, value) for t in expected_type):
                raise SkillConfigurationError(
                    f"Property '{prop_name}' value {value!r} does not match "
                    f"any of the allowed types {expected_type!r}"
                )
        elif expected_type is not None:
            if not cls._value_matches_type(expected_type, value):
                raise SkillConfigurationError(
                    f"Property '{prop_name}' expected {expected_type}, got "
                    f"{type(value).__name__}"
                )

        cls._validate_common_constraints(prop_name, schema, value)

    @classmethod
    def _validate_value(
        cls,
        prop_name: str,
        schema: Dict[str, Any],
        value: Any,
    ) -> None:
        """Validate a value against a schema that may include anyOf/oneOf/allOf."""
        has_any = "anyOf" in schema
        has_one = "oneOf" in schema
        has_all = "allOf" in schema

        if has_any or has_one or has_all:
            if has_any:
                branches = schema["anyOf"]
                if not isinstance(branches, list):
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' must define 'anyOf' as a list"
                    )
                matches = 0
                for branch in branches:
                    try:
                        cls._validate_value(prop_name, branch, value)
                        matches += 1
                    except SkillConfigurationError:
                        pass
                if matches == 0:
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' value {value!r} does not match "
                        f"any of the allowed schemas"
                    )

            if has_one:
                branches = schema["oneOf"]
                if not isinstance(branches, list):
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' must define 'oneOf' as a list"
                    )
                matches = 0
                for branch in branches:
                    try:
                        cls._validate_value(prop_name, branch, value)
                        matches += 1
                    except SkillConfigurationError:
                        pass
                if matches != 1:
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' value {value!r} must match "
                        f"exactly one of the allowed schemas"
                    )

            if has_all:
                branches = schema["allOf"]
                if not isinstance(branches, list):
                    raise SkillConfigurationError(
                        f"Property '{prop_name}' must define 'allOf' as a list"
                    )
                for branch in branches:
                    cls._validate_value(prop_name, branch, value)

            # Top-level enum/range/pattern constraints still apply.
            cls._validate_common_constraints(prop_name, schema, value)
            return

        cls._validate_simple_schema(prop_name, schema, value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def get_config_properties(cls) -> list:
        """Return normalized config property descriptors for discovery."""
        result = []
        for prop_name, raw_schema in cls._PROPERTIES.items():
            schema = cls._normalize_schema(prop_name, raw_schema)
            result.append(
                {
                    "param": prop_name,
                    "full_key": cls._get_full_key(prop_name),
                    "schema": schema,
                }
            )
        return result

    @property
    def properties(self) -> Mapping[str, Any]:
        """Return a read-only mapping of every declared property resolved value.

        Resolution order:
          1. exact config value under the class config prefix
          2. schema default

        The result is cached on first access so repeated property reads do not
        re-validate or re-read config.
        """
        if not hasattr(self, "_resolved_properties"):
            resolved = {}
            for prop_name, raw_schema in self._PROPERTIES.items():
                schema = self._normalize_schema(prop_name, raw_schema)
                full_key = self._get_full_key(prop_name)
                value = config.get_exact(full_key, schema.get("default"))
                self._validate_value(prop_name, schema, value)
                resolved[prop_name] = value

            self._resolved_properties = MappingProxyType(resolved)

        return self._resolved_properties
