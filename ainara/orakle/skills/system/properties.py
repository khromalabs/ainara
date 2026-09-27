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

"""Skill to inspect and modify configuration properties of skills and Nexus Apps"""

from typing import Annotated, Any, Dict, Literal, Optional

from jsonschema import Draft7Validator

from ainara.framework.config import config
from ainara.framework.skill import Skill


class SystemProperties(Skill):
    """Lists configuration properties of Nexus Skills, Nexus Apps, and modules. Updates properties to change values."""

    matcher_info = (
        "Use this skill when the user wants to inspect or modify configuration"
        " properties/settings of skills, Nexus Apps, or library modules."
        " Supports listing properties (optionally filtered by app or keywords,"
        " matches using criteria 'any') and updating one or more values."
        " Examples: 'list properties', 'show my screener settings', 'set"
        " risk.max_leverage to 3.5', 'update these properties'.\n\nKeywords:"
        " properties, settings, config, configure, adjust, customize, setup,"
        " preferences."
    )

    def _get_capabilities_manager(self):
        """Resolve the running CapabilitiesManager without modifying other files."""
        try:
            from flask import current_app

            return current_app.capabilities_manager
        except RuntimeError:
            from ainara.orakle import server as _server

            return _server.app.capabilities_manager

    def _get_property_catalog(self) -> Dict[str, Dict[str, Any]]:
        """Return a flat catalog of all configurable properties."""
        manager = self._get_capabilities_manager()
        return manager.get_config_properties()

    def _matches_app(
        self, full_key: str, prop: Dict[str, Any], app: str
    ) -> bool:
        """Check whether a property belongs to the given app/prefix."""
        app_l = app.lower()

        if full_key.lower().startswith(app_l):
            return True

        for field in ("vendor", "bundle", "module", "skill", "param"):
            value = prop.get(field)
            if isinstance(value, str) and app_l in value.lower():
                return True
        return False

    def _matches_keywords(
        self, full_key: str, prop: Dict[str, Any], keywords: str
    ) -> bool:
        """Check whether a property matches any the provided keywords."""
        kws = [k.strip().lower() for k in keywords.split() if k.strip()]
        if not kws:
            return True

        haystack = " ".join(
            str(part)
            for part in (
                full_key,
                prop.get("title"),
                prop.get("description"),
                prop.get("module"),
                prop.get("skill"),
                prop.get("vendor"),
                prop.get("bundle"),
            )
            if part is not None
        ).lower()

        return any(kw in haystack for kw in kws)

    def _property_group(self, full_key: str, prop: Dict[str, Any]) -> str:
        """Return a human-friendly group name for the inventory view."""
        if prop.get("scope") == "shared":
            parts = [
                prop.get("vendor"),
                prop.get("bundle"),
                prop.get("module"),
            ]
            parts = [p for p in parts if p]
            if parts:
                return ".".join(parts)

        skill = (
            prop.get("skill")
            or prop.get("param", "").split(".")[0]
            or full_key
        )
        return skill

    def _build_group_breakdown(self, properties: list) -> list:
        """Build a count-per-group breakdown from filtered properties."""
        groups = {}
        for full_key, prop in properties:
            group = self._property_group(full_key, prop)
            groups[group] = groups.get(group, 0) + 1
        return [
            {"group": g, "property_count": groups[g]}
            for g in sorted(groups, key=lambda x: groups[x], reverse=True)
        ]

    def _derive_vendor_bundle_module(
        self, full_key: str, prop: Dict[str, Any]
    ) -> tuple:
        """Derive vendor/bundle/module from the key when possible."""
        parts = full_key.split(".")
        if len(parts) >= 4 and parts[:2] == ["skills", "nexus"]:
            vendor = parts[2]
            bundle = parts[3]
            module_parts = parts[4:-1]
            module = ".".join(module_parts) if module_parts else None
            return vendor, bundle, module
        return prop.get("vendor"), prop.get("bundle"), prop.get("module")

    def _property_summary(
        self, full_key: str, prop: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a JSON-friendly summary for a single property."""
        schema = prop.get("schema", {})
        current_value = config.get_exact(full_key, schema.get("default"))
        vendor, bundle, module = self._derive_vendor_bundle_module(
            full_key, prop
        )
        return {
            "full_key": full_key,
            "title": schema.get("title"),
            "description": schema.get("description"),
            "type": schema.get("type"),
            "default": schema.get("default"),
            "value": current_value,
            "enum": schema.get("enum"),
            "minimum": schema.get("minimum"),
            "maximum": schema.get("maximum"),
            "vendor": vendor,
            "bundle": bundle,
            "module": module,
            "scope": prop.get("scope"),
            "skill": prop.get("skill"),
        }

    def _list_properties(
        self,
        app: Optional[str],
        keywords: Optional[str],
        limit: int,
    ) -> Dict[str, Any]:
        """Implementation of the `list` action."""
        catalog = self._get_property_catalog()

        filtered = []
        if app or keywords:
            for full_key, prop in catalog.items():
                if app and not self._matches_app(full_key, prop, app):
                    continue
                if keywords and not self._matches_keywords(
                    full_key, prop, keywords
                ):
                    continue
                filtered.append((full_key, prop))
        else:
            filtered = list(catalog.items())

        if not app and not keywords:
            # Inventory mode: return groups and counts instead of every property.
            return {
                "success": True,
                "mode": "inventory",
                "total_properties": len(filtered),
                "groups": self._build_group_breakdown(filtered),
            }

        total = len(filtered)

        if total == 0:
            return {
                "success": True,
                "mode": "list",
                "total_matches": 0,
                "limit": limit,
                "returned": 0,
                "properties": [],
            }

        if total > limit:
            return {
                "success": True,
                "mode": "too_many",
                "total_matches": total,
                "limit": limit,
                "message": (
                    "Too many results. Please narrow down with more specific"
                    " keywords or app."
                ),
                "groups": self._build_group_breakdown(filtered),
            }

        properties = [
            self._property_summary(full_key, prop)
            for full_key, prop in filtered
        ]

        return {
            "success": True,
            "mode": "list",
            "total_matches": total,
            "limit": limit,
            "returned": len(properties),
            "properties": properties,
        }

    def _update_properties(
        self, updates: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Implementation of the `update` action."""
        if not updates:
            return {"success": False, "error": "No updates provided"}

        catalog = self._get_property_catalog()

        validation_results = {}
        updates_items = list(updates.items())

        # Validate everything first
        for full_key, value in updates_items:
            prop = catalog.get(full_key)
            if prop is None:
                validation_results[full_key] = {
                    "valid": False,
                    "error": f"Unknown property '{full_key}'",
                }
                continue

            schema = prop.get("schema")
            if not isinstance(schema, dict):
                validation_results[full_key] = {
                    "valid": False,
                    "error": f"No schema available for '{full_key}'",
                }
                continue

            try:
                Draft7Validator(schema).validate(value)
                validation_results[full_key] = {"valid": True}
            except Exception as ex:
                validation_results[full_key] = {
                    "valid": False,
                    "error": str(ex),
                }

        has_errors = any(
            not item["valid"] for item in validation_results.values()
        )

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "applied": False,
                "results": validation_results,
            }

        if has_errors:
            return {
                "success": False,
                "applied": False,
                "results": validation_results,
            }

        # All validated successfully -> apply sequentially
        applied_results = {}
        for full_key, value in updates_items:
            try:
                config.set_exact(full_key, value)
                applied_results[full_key] = {"applied": True}
            except Exception as ex:
                applied_results[full_key] = {
                    "applied": False,
                    "error": str(ex),
                }

        return {
            "success": True,
            "dry_run": False,
            "applied": True,
            "results": applied_results,
        }

    async def run(
        self,
        action: Annotated[
            Literal["list", "update"],
            "'list' to inspect properties, 'update' to change values",
        ],
        app: Annotated[
            Optional[str],
            "Skill name, Nexus App name, or configuration prefix "
            "(e.g. 'ataria', 'skills.nexus.khromalabs.ataria', 'screener')",
        ] = None,
        keywords: Annotated[
            Optional[str],
            "Space-separated keywords to filter property names, titles, and"
            " descriptions",
        ] = None,
        updates: Annotated[
            Optional[Dict[str, Any]],
            "For 'update': a JSON object mapping each property's full key to"
            " its new value."
            " All keys must already exist in the property catalog and be"
            " compliant with the property's JSON schema. Example:"
            " {'skills.nexus.khromalabs.ataria.crypto.tradingaccount.breakeven_buffer_pct':"
            " 0.15}."
            " Use dry_run=true to validate without saving.",
        ] = None,
        dry_run: Annotated[
            bool,
            "If True, validate without writing. Only used with 'update'",
        ] = False,
        limit: Annotated[
            int,
            "Maximum number of properties to return. "
            "If more than this many match, returns a too_many response with"
            " group counts.",
        ] = 25,
    ) -> Dict[str, Any]:
        """List or update configuration properties of skills and Nexus Apps.

        For 'update', `updates` must be a dict mapping full config keys to
        new values, e.g.
        {"skills.nexus.khromalabs.ataria.crypto.tradingaccount.breakeven_buffer_pct": 0.15}.
        """
        if action == "list":
            return self._list_properties(
                app=app,
                keywords=keywords,
                limit=limit,
            )

        if action == "update":
            if updates is None:
                return {
                    "success": False,
                    "error": "`updates` is required for the 'update' action",
                }
            return self._update_properties(updates, dry_run=dry_run)

        return {"success": False, "error": f"Unsupported action: {action}"}
