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
import mimetypes
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from flask import send_from_directory

from ainara.framework.config import config, register_nexus_root, nexus_prefix_from_module_name
from ainara.framework.mcp.client_manager import MCPClientManager
from ainara.framework.nexus_apps import (
    BUNDLE_MANIFEST,
    register_bundle_namespace,
    resolve_app_payload,
)
from ainara.framework.skill import Skill
from ainara.framework.skill_properties import ConfigurablePropertiesMixin

from .skills import BasePythonSkillProvider
from .base import resolve_ui_mode

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
        # Version-staleness tracking: what this process loaded per bundle
        # ('vendor/bundle' -> {version, manifest_path, bundle_dir}) and the
        # drift warnings already emitted (warn-once; see
        # _check_bundle_version_drift). Long-running hosts (standalone
        # Orakle spawned by scripts/scheduler.py) never re-import bundle
        # modules, so a Polaris wizard update swaps the files on disk while
        # the process keeps executing the code it loaded at startup —
        # silently, without these diagnostics.
        self._loaded_bundle_versions: Dict[str, Dict[str, Any]] = {}
        self._bundle_drift_warnings: Dict[str, str] = {}

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

        # Record what this process is loading so execute() can detect a
        # later on-disk update (see _check_bundle_version_drift).
        self._record_loaded_bundle_version(vendor, bundle, bundle_dir)

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
                    mode, ui_mode_error = resolve_ui_mode(cap_data)
                    if ui_mode_error:
                        # Fail-closed (#29): never guess a surface mode
                        self.load_errors.append(
                            {
                                "skill_id": cap_id,
                                "error": f"UI association dropped: {ui_mode_error}",
                            }
                        )
                        logger.error(
                            f"Skill '{cap_id}': {ui_mode_error}."
                            " The skill loads headless (no UI component)."
                        )
                        continue

                    cap_data["ui"] = {
                        "component": component_name,
                        "mode": mode,
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

    # ------------------------------------------------------------------
    # Bundle staleness diagnostics
    #
    # Installed bundles are swapped atomically on disk (install protocol
    # v0), but Python never re-imports the modules a process already
    # loaded, and the mid-session modification guard in
    # BasePythonSkillProvider.execute() only covers user skills (nexus
    # providers get no startup_time). A host that stays up across a
    # Polaris wizard update — standalone Orakle spawned by
    # scripts/scheduler.py, notably — therefore keeps executing the code
    # it loaded at startup, silently. These helpers make that state
    # observable: the loaded manifest version is logged at load time and
    # re-checked on every execution, warning once when the on-disk bundle
    # no longer matches it. Warn-only by design: a pending restart must
    # not take scheduled runs down.
    # ------------------------------------------------------------------

    @staticmethod
    def _find_manifest_path(bundle_dir: Path) -> Path:
        """Locate nexus.json for a loaded bundle directory.

        Installed apps: bundle root == payload dir (manifest inside).
        Dev repos: manifest sits next to the payload/ directory.
        """
        manifest_path = bundle_dir / BUNDLE_MANIFEST
        if not manifest_path.is_file():
            manifest_path = bundle_dir.parent / BUNDLE_MANIFEST
        return manifest_path

    @staticmethod
    def _read_manifest_version(manifest_path: Path) -> Optional[str]:
        """Quiet manifest version read — no logging; callers decide.

        Returns None when missing, unreadable, or lacking a version.
        (read_manifest() in framework.nexus_apps already warns, but only
        at load time; the drift check needs its own silent read.)
        """
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            version = data.get("manifest", {}).get("version")
        except (OSError, ValueError, AttributeError):
            return None
        return str(version) if version else None

    def _record_loaded_bundle_version(
        self, vendor: str, bundle: str, bundle_dir: Path
    ) -> None:
        """Snapshot the manifest version this process is loading.

        Called from _load_bundle, i.e. exactly when the bundle modules are
        imported, so the recorded version is the code that will actually
        execute. Also emits the one log line that makes "which build is
        this process running?" answerable from orakle.log alone.
        """
        key = f"{vendor}/{bundle}"
        manifest_path = self._find_manifest_path(bundle_dir)
        version = self._read_manifest_version(manifest_path)
        self._loaded_bundle_versions[key] = {
            "version": version,
            "manifest_path": manifest_path,
            "bundle_dir": bundle_dir,
        }
        # Fresh load: clear any drift warning from a previous scan.
        self._bundle_drift_warnings.pop(key, None)
        logger.info(
            f"Loaded bundle '{key}' v{version or 'unknown'}"
            f" from {bundle_dir}"
        )

    def _check_bundle_version_drift(
        self, capability_data: Dict[str, Any]
    ) -> None:
        """Warn once when the on-disk bundle differs from the loaded one.

        Three warn-worthy states, each emitted once per occurrence (a
        return to a healthy match re-arms the warning):

        - version drift: on-disk manifest version != loaded version
        - manifest missing while the bundle directory still exists
          (update in flight or corrupted install)
        - manifest present but unreadable

        A vanished bundle *directory* is deliberately silent: that is an
        uninstall/swap; execution will fail on its own and a manifest
        warning would be noise.
        """
        vendor = capability_data.get("vendor")
        bundle = capability_data.get("bundle")
        if not vendor or not bundle:
            return
        key = f"{vendor}/{bundle}"
        loaded = self._loaded_bundle_versions.get(key)
        if not loaded:
            return
        loaded_version = loaded["version"] or "unknown"
        manifest_path: Path = loaded["manifest_path"]
        bundle_dir: Path = loaded["bundle_dir"]

        signature: Optional[str] = None
        message: Optional[str] = None
        if not bundle_dir.exists():
            # Uninstall/swap in progress — stay silent (see docstring).
            self._bundle_drift_warnings.pop(key, None)
            return
        if not manifest_path.is_file():
            signature = "missing"
            message = (
                f"Bundle '{key}' manifest missing at {manifest_path}"
                f" although the bundle directory still exists — update in"
                f" flight or corrupted install; this process keeps"
                f" executing loaded v{loaded_version}."
            )
        else:
            disk_version = self._read_manifest_version(manifest_path)
            if disk_version is None:
                signature = "unreadable"
                message = (
                    f"Bundle '{key}' manifest unreadable at"
                    f" {manifest_path}; this process keeps executing"
                    f" loaded v{loaded_version}."
                )
            elif disk_version != loaded["version"]:
                signature = f"drift:{disk_version}"
                message = (
                    f"Bundle '{key}' updated on disk (loaded"
                    f" v{loaded_version}, on-disk v{disk_version}) but this"
                    f" process has not reloaded it — the previously loaded"
                    f" code keeps executing until restart. Restart the"
                    f" application (or the scheduler.py services) to apply"
                    f" the update."
                )

        if signature is None:
            # Healthy match — re-arm warn-once for a future drift.
            self._bundle_drift_warnings.pop(key, None)
            return
        if self._bundle_drift_warnings.get(key) == signature:
            return
        self._bundle_drift_warnings[key] = signature
        logger.warning(message)

    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a nexus skill, after bundle-staleness diagnostics."""
        capability_data = self.capabilities.get(name)
        if capability_data:
            try:
                self._check_bundle_version_drift(capability_data)
            except Exception:
                # Diagnostics must never break skill execution.
                logger.warning(
                    f"Bundle version drift check failed for '{name}'",
                    exc_info=True,
                )
        return super().execute(name, arguments)

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
