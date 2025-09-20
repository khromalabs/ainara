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

# import importlib.util
# import json
import logging
# import os
from pathlib import Path
from typing import Any, Dict, Optional

from flask import send_from_directory

from ainara.framework.mcp.client_manager import MCPClientManager

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
        self.nexus_path = Path(nexus_path)
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        if not self.nexus_path.is_dir():
            logger.warning(
                f"Nexus path '{self.nexus_path}' does not exist or is not a"
                " directory. Creating it."
            )
            self.nexus_path.mkdir(parents=True, exist_ok=True)

    def discover(self) -> Dict[str, Dict[str, Any]]:
        """Discover and load skills from Nexus bundles."""
        self.capabilities = {}
        logger.info(f"Scanning for Nexus bundles in: {self.nexus_path}")

        for vendor_dir in self.nexus_path.iterdir():
            if not vendor_dir.is_dir() or vendor_dir.name.startswith(
                ("_", ".")
            ):
                logger.info(f"Skipping: {vendor_dir}")
                continue

            for bundle_dir in vendor_dir.iterdir():
                if not bundle_dir.is_dir() or bundle_dir.name.startswith(
                    ("_", ".")
                ):
                    continue

                prefix_module = (
                    f"ainara.nexus.{vendor_dir.name}.{bundle_dir.name}"
                )
                logger.info(f"Scanning for Nexus bundles for: {prefix_module}")
                bundle_caps = super().discover(
                    bundle_dir,
                    prefix_module,
                    class_name_prefix=vendor_dir.name.capitalize()
                    + bundle_dir.name.capitalize(),
                    capability_type="nexus",
                )

                if bundle_caps:
                    # Add vendor and bundle info to all skills in this bundle
                    # This is done for all skills, regardless of whether they have a UI component.
                    for cap_data in bundle_caps.values():
                        cap_data["vendor"] = vendor_dir.name
                        cap_data["bundle"] = bundle_dir.name

                    # If skills were found, look for a UI components directory
                    ui_components_path = bundle_dir / "_components"
                    if ui_components_path.is_dir():
                        logger.info(
                            "Found UI components for bundle"
                            f" '{bundle_dir.name}' at: {ui_components_path}"
                        )
                        # Add ui info to each capability, verifying component existence
                        for cap_id, cap_data in bundle_caps.items():
                            # Derive component name from skill ID by convention
                            skill_prefix = f"{vendor_dir.name}_{bundle_dir.name}_"
                            if not cap_id.startswith(skill_prefix):
                                logger.warning(
                                    f"Skill ID '{cap_id}' does not follow the expected naming convention "
                                    f"'{skill_prefix}...' and will not be linked to a UI component."
                                )
                                continue

                            component_base_name = cap_id[len(skill_prefix):]
                            # Convert snake_case to PascalCase
                            component_name = "".join(
                                word.capitalize()
                                for word in component_base_name.split("_")
                            )

                            # Verify component directory exists
                            component_dir = (ui_components_path / component_name).resolve()
                            if component_dir.is_dir():
                                # This skill has a verified UI component
                                cap_data["ui"] = {
                                    "component": component_name,
                                }
                                # ui_path is for internal use by serve_component
                                cap_data["ui_path"] = str(ui_components_path)
                                logger.debug(
                                    f"Associated skill '{cap_id}' with component '{component_name}'"
                                )
                            else:
                                logger.warning(
                                    f"Skill '{cap_id}' found, but corresponding component directory "
                                    f"'{component_dir}' not found. This skill will not have a UI component."
                                )
                                cap_data["type"] = "skill"
                    else:
                        logger.info(
                            "No '_components' directory found for bundle"
                            f" '{bundle_dir.name}'."
                        )
                    self.capabilities.update(bundle_caps)

        logger.info(f"Loaded {len(self.capabilities)} nexus skills.")
        return self.capabilities

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
            if (
                cap_data.get("type") == "nexus"
                and cap_data.get("vendor") == vendor
                and cap_data.get("bundle") == bundle
            ):
                ui_path = cap_data.get("ui_path")
                break

        if not ui_path:
            raise FileNotFoundError(
                f"No UI components found for bundle '{vendor}/{bundle}'."
            )

        ui_dir = Path(ui_path).resolve()
        file_path = Path(*rest)

        # Security check: ensure the resolved path is within the UI directory.
        # send_from_directory should handle this, but an extra check is good practice.
        full_path = (ui_dir / file_path).resolve()
        if not str(full_path).startswith(str(ui_dir)):
            raise PermissionError("Access denied: path traversal attempt.")

        logger.info(f"Serving Nexus component: {file_path} from {ui_dir}")
        return send_from_directory(ui_dir, file_path)
