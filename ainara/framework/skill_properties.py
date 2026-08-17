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

        if "type" not in schema:
            inferred = cls._infer_type_from_default(schema.get("default"))
            if not inferred:
                raise SkillConfigurationError(
                    f"Property '{prop_name}' must define 'type' or have a "
                    "default from which a type can be inferred"
                )
            schema["type"] = inferred

        schema.setdefault("description", "")
        return schema

    # ------------------------------------------------------------------
    # Value validation
    # ------------------------------------------------------------------

    @classmethod
    def _validate_value(cls, prop_name: str, schema: Dict[str, Any], value: Any) -> None:
        """Validate a resolved value against the property's JSON Schema fragment."""
        expected_type = schema.get("type")

        if expected_type == "string" and not isinstance(value, str):
            raise SkillConfigurationError(
                f"Property '{prop_name}' expected string, got "
                f"{type(value).__name__}"
            )
        if expected_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SkillConfigurationError(
                    f"Property '{prop_name}' expected number, got "
                    f"{type(value).__name__}"
                )
        if expected_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise SkillConfigurationError(
                    f"Property '{prop_name}' expected integer, got "
                    f"{type(value).__name__}"
                )
        if expected_type == "boolean" and not isinstance(value, bool):
            raise SkillConfigurationError(
                f"Property '{prop_name}' expected boolean, got "
                f"{type(value).__name__}"
            )
        if expected_type == "array" and not isinstance(value, list):
            raise SkillConfigurationError(
                f"Property '{prop_name}' expected array, got "
                f"{type(value).__name__}"
            )
        if expected_type == "object" and not isinstance(value, dict):
            raise SkillConfigurationError(
                f"Property '{prop_name}' expected object, got "
                f"{type(value).__name__}"
            )

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
