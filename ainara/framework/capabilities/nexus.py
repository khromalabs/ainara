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
import mimetypes
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from flask import send_from_directory

from ainara.framework.config import config, register_nexus_root, nexus_prefix_from_module_name
from ainara.framework.mcp.client_manager import MCPClientManager
from ainara.framework.nexus_apps import (
    register_bundle_namespace,
    resolve_app_payload,
)
from ainara.framework.skill import Skill
from ainara.framework.skill_properties import ConfigurablePropertiesMixin

from .skills import BasePythonSkillProvider

logger = logging.getLogger(__name__)


class NexusSkillProvider(BasePythonSkillProvider):
    """Provider for discovering and executing skills from Nexus bundles."""

    def __init__(
        self,
        nexus_path: str,
        config,
        mcp_client_manager: Optional[MCPClientManager],
    ):
        super().__init__(config, mcp_client_manager)

        # Ensure .mjs files are served with the correct MIME type (fixes Windows issue)
        mimetypes.add_type("application/javascript", ".mjs")

        self.nexus_paths = config.get_nexus_base_paths()
        # Primary alias: discover() stays single-root until the multi-root
        # scan lands; the alias keeps existing callers working unchanged.
        self.nexus_path = config.get_nexus_base_path()
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        self.bundle_config_params = {}

        # Namespace resolution: app-shaped roots (dev repo payload/,
        # installed bundles) have no physical ainara/nexus/<vendor>/<bundle>
        # nesting on disk — discover() registers each bundle via
        # register_bundle_namespace() (see framework.nexus_apps) instead of
        # sys.path tricks.
        logger.info(
            f"Nexus roots (precedence order): "
            f"{[str(p) for p in self.nexus_paths]}"
        )

        if not self.nexus_path.is_dir():
            # Legacy fallback root only — never auto-create it. Nexus apps
            # are independent repos/installs (nexus.dev_apps / installed
            # apps); an empty ainara/nexus in the source tree serves no
            # purpose and would silently resurrect a removed directory.
            logger.info(
                f"Nexus path '{self.nexus_path}' does not exist — skipped "
                "(legacy primary root; dev_apps/installed roots remain active)"
            )

    def _collect_bundle_config_params(
        self,
        vendor: str,
        bundle: str,
        prefix_module: str,
    ):
        if (vendor, bundle) in self.bundle_config_params:
            return

        # --- Runtime Registry Lookup ---
        params = []
        for module_name, classes in (
            ConfigurablePropertiesMixin._runtime_registry.items()
        ):
            # Only process modules that belong to this specific bundle
            if not module_name.startswith(prefix_module):
                continue

            # Calculate relative module path to match old metadata structure
            if module_name == prefix_module:
                relative_module = ""
            elif module_name.startswith(prefix_module + "."):
                relative_module = module_name[len(prefix_module) + 1:]
            else:
                continue

            for cls in classes:
                # Skip actual Skill classes; their properties are already
                # collected as scope="skill" in skills.py
                if issubclass(cls, Skill):
                    continue

                for prop in cls.get_config_properties():
                    p = dict(prop)
                    p["scope"] = "shared"
                    p["module"] = relative_module
                    p["vendor"] = vendor
                    p["bundle"] = bundle
                    params.append(p)

        self.bundle_config_params[(vendor, bundle)] = params
        # -----------------------------------

    def get_extra_config_properties(self) -> Dict[str, Dict[str, Any]]:
        properties = {}
        for (vendor, bundle), params in self.bundle_config_params.items():
            for p in params:
                full_key = p.get("full_key")
                if full_key:
                    properties[full_key] = p
        return properties

    def discover(self) -> Dict[str, Dict[str, Any]]:
        """Discover and load skills from Nexus bundles across all roots.

        Roots are scanned in ``self.nexus_paths`` order (dev > installed >
        primary). App-shaped roots (``payload/nexus.json`` or ``nexus.json``
        at the top, identity taken from the manifest) contribute one bundle
        each; the legacy vendor-layout primary root contributes one bundle
        per ``<vendor>/<bundle>`` directory with a physical bundle marker
        (``nexus.json`` or ``__init__.py``). The first root that contains a
        (vendor, bundle) pair owns it; copies in lower-precedence roots are
        skipped. Skills accumulate in a local dict because
        ``super().discover()`` resets ``self.capabilities`` on every call
        (with the old pattern, only the last-scanned bundle would have
        survived a multi-root scan).
        """
        all_caps: Dict[str, Dict[str, Any]] = {}
        seen_bundles: set = set()

        for root in self.nexus_paths:
            if not root.is_dir():
                logger.warning(
                    f"Nexus root does not exist or is not a directory,"
                    f" skipping: {root}"
                )
                continue

            # App-shaped roots first: <root>/payload/nexus.json (dev repo)
            # or <root>/nexus.json (installed app — artifact root equals
            # bundle root). Identity comes from the manifest.
            app = resolve_app_payload(root)
            if app:
                vendor, bundle, bundle_dir = app
                self._load_bundle(
                    all_caps, seen_bundles, vendor, bundle, bundle_dir
                )
                continue

            try:
                # sorted(): iterdir() order is filesystem-dependent; a
                # deterministic scan order keeps logs and verification
                # reproducible across runs and machines.
                vendor_entries = sorted(root.iterdir())
            except OSError as e:
                # Installed roots are user-space content; one unreadable
                # root must not zero out the whole provider.
                logger.warning(f"Cannot list Nexus root '{root}': {e} — skipping root")
                continue
            logger.info(f"Scanning for Nexus bundles in: {root}")

            for vendor_dir in vendor_entries:
                if not vendor_dir.is_dir() or vendor_dir.name.startswith(
                    ("_", ".")
                ):
                    logger.info(f"Skipping: {vendor_dir}")
                    continue

                for bundle_dir in sorted(vendor_dir.iterdir()):
                    if not bundle_dir.is_dir() or bundle_dir.name.startswith(
                        ("_", ".")
                    ):
                        continue
                    # Physical-bundle guard: a directory with neither
                    # nexus.json nor __init__.py is not a bundle (e.g. a
                    # source-repo mount whose dev material sits at top).
                    # Prevents import-noise scans of non-bundle trees.
                    if not (
                        (bundle_dir / "nexus.json").is_file()
                        or (bundle_dir / "__init__.py").is_file()
                    ):
                        logger.info(f"Skipping non-bundle directory: {bundle_dir}")
                        continue
                    self._load_bundle(
                        all_caps,
                        seen_bundles,
                        vendor_dir.name,
                        bundle_dir.name,
                        bundle_dir,
                    )

        self.capabilities = all_caps
        logger.info(f"Loaded {len(self.capabilities)} nexus skills.")
        return self.capabilities

    def _load_bundle(
        self,
        all_caps: Dict[str, Dict[str, Any]],
        seen_bundles: set,
        vendor: str,
        bundle: str,
        bundle_dir: Path,
    ) -> None:
        """Load one (vendor, bundle) from ``bundle_dir`` into ``all_caps``.

        First-wins: the highest-precedence root that CONTAINS the bundle
        owns it, even if it yields zero skills — never silently fall back
        to a lower-precedence copy (that would mask dev-tree errors).
        """
        bundle_key = (vendor, bundle)
        if bundle_key in seen_bundles:
            logger.info(
                f"Skipping '{vendor}/{bundle}'"
                f" in {bundle_dir}: already loaded from a"
                " higher-precedence root"
            )
            return
        seen_bundles.add(bundle_key)

        prefix_module = f"ainara.nexus.{vendor}.{bundle}"
        logger.info(f"Scanning for Nexus bundles for: {prefix_module}")

        # External Nexus roots must be registered BEFORE skill
        # instantiation so that `Skill._get_config_prefix()` can
        # derive the correct full config keys from `__module__`.
        if not prefix_module.startswith("ainara."):
            root_name = prefix_module.split(".")[0]
            register_nexus_root(root_name, f"skills.nexus.{root_name}")

        # App-shaped bundles have no physical ainara/nexus/<vendor>/<bundle>
        # nesting on disk — register the namespace alias so skill imports
        # resolve. Idempotent + first-wins (see framework.nexus_apps).
        register_bundle_namespace(bundle_dir, vendor, bundle)

        bundle_caps = super().discover(
            bundle_dir,
            prefix_module,
            class_name_prefix=vendor.capitalize() + bundle.capitalize(),
            capability_type="nexus",
        )

        if not bundle_caps:
            return

        # Add vendor and bundle info to all skills in this bundle
        # This is done for all skills, regardless of whether they have a UI component.
        for cap_data in bundle_caps.values():
            cap_data["vendor"] = vendor
            cap_data["bundle"] = bundle

        # If skills were found, look for a UI components directory
        ui_components_path = bundle_dir / "_components"
        if ui_components_path.is_dir():
            logger.info(
                "Found UI components for bundle"
                f" '{bundle}' at: {ui_components_path}"
            )
            # Add ui info to each capability, verifying component existence
            for cap_id, cap_data in bundle_caps.items():
                # Derive component name from skill ID by convention
                skill_prefix = f"{vendor}_{bundle}_"
                if not cap_id.startswith(skill_prefix):
                    logger.warning(
                        f"Skill ID '{cap_id}' does not follow the"
                        " expected naming convention"
                        f" '{skill_prefix}...' and will not be"
                        " linked to a UI component."
                    )
                    continue

                component_base_name = cap_id[len(skill_prefix):]
                # Convert snake_case to PascalCase
                component_name = "".join(
                    word.capitalize()
                    for word in component_base_name.split("_")
                )

                # Verify component directory exists
                component_dir = (
                    ui_components_path / component_name
                ).resolve()
                if component_dir.is_dir():
                    # This skill has a verified UI component
                    cap_data["ui"] = {
                        "component": component_name,
                    }
                    # ui_path is for internal use by serve_component
                    cap_data["ui_path"] = str(ui_components_path)
                    logger.info(
                        f"Associated skill '{cap_id}'"
                        f" ({ui_components_path}) with component"
                        f" '{component_name}'"
                    )
                else:
                    logger.warning(
                        f"Skill '{cap_id}' found, but"
                        " corresponding component directory"
                        f" '{component_dir}' not found. This skill"
                        " will not have a UI component."
                    )
                    # Not necessary to make this distinction to a
                    # UI-less nexus skill
                    # cap_data["type"] = "skill"
        else:
            logger.info(
                "No '_components' directory found for bundle"
                f" '{bundle}'."
            )

        self._collect_bundle_config_params(vendor, bundle, prefix_module)
        all_caps.update(bundle_caps)

    def serve_component(self, component_path: str) -> Any:
        """Serve a UI component file from a Nexus bundle."""
        # component_path is expected to be like: vendor/bundle/component/file.js
        path_parts = Path(component_path).parts
        if len(path_parts) < 3:
            raise FileNotFoundError("Invalid component path format.")

        vendor, bundle, *rest = path_parts

        # Find the capability that matches this bundle to get its UI path.
        # All skills in a bundle share the same UI path.
        ui_path = None
        for cap_data in self.capabilities.values():
            # logger.info(f"cap_data: {cap_data}")
            if (
                cap_data.get("type") == "nexus"
                and cap_data.get("vendor") == vendor
                and cap_data.get("bundle") == bundle
                and cap_data.get("ui_path")
            ):
                ui_path = cap_data.get("ui_path")
                break

        if not ui_path:
            raise FileNotFoundError(
                f"No UI components found for bundle '{vendor}/{bundle}'."
            )

        ui_dir = Path(ui_path).resolve()
        file_path = Path(*rest).as_posix()

        # Security check: ensure the resolved path is within the UI directory.
        # send_from_directory should handle this, but an extra check is good practice.
        full_path = (ui_dir / file_path).resolve()
        if not str(full_path).startswith(str(ui_dir)):
            raise PermissionError("Access denied: path traversal attempt.")

        logger.info(f"Serving Nexus component: {file_path} from {ui_dir}")
        return send_from_directory(ui_dir, file_path)
