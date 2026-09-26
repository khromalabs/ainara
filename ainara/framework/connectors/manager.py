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

import traceback
import importlib
import inspect
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .base import BaseConnector

# from ainara.framework.connectors.router import ConnectorRouter

logger = logging.getLogger(__name__)


class ConnectorManager:
    """
    Manages the discovery, configuration, and lifecycle of API Connectors.
    """

    def __init__(self, config_manager, router):
        self.config_manager = config_manager
        self.connectors: Dict[str, BaseConnector] = {}
        self.router = router
        self._discover_connectors()

    def _discover_connectors(self):
        """
        Scans the 'resources/connectors' directory for connector implementations.
        """
        # Define the path relative to the project root
        # Assuming this file is in ainara/framework/connectors/manager.py
        # We want to go up 3 levels to root, then down to ainara/orakle/connectors
        root_path = Path(__file__).parent.parent.parent.parent
        connectors_dir = root_path / "resources" / "connectors"

        if not connectors_dir.exists():
            logger.info(f"No connectors directory found at {connectors_dir}. Skipping discovery.")
            return

        logger.info(f"Scanning for connectors in: {connectors_dir}")

        # Prefix for importing modules
        prefix_module = "resources.connectors"

        for connector_file in connectors_dir.glob("*.py"):
            if connector_file.stem.startswith("__"):
                continue

            try:
                module_name = f"{prefix_module}.{connector_file.stem}"
                module = importlib.import_module(module_name)

                for name, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, BaseConnector)
                        and obj is not BaseConnector
                    ):
                        self._load_connector(obj)

            except Exception as e:
                logger.error(f"Failed to load connector from {connector_file}: {e}", exc_info=True)

    def _load_connector(self, connector_class):
        """
        Instantiates a connector if configuration is present.
        """
        try:
            # logger.info(f"GOING TO LOAD CONNECTOR: {connector_class}")
            # instance = connector_class(connector_config)
            instance = connector_class(self.config_manager)
            if hasattr(instance, "hiddenConnector") and instance.hiddenConnector:
                logger.info(f"Skipping hidden connector: {instance.MANIFEST['id']}")
            else:
                connector_id = instance.MANIFEST['id']
                self.connectors[connector_id] = instance
                logger.info(f"Loaded connector: {instance.MANIFEST['id']} ({connector_id})")
                self.router.register_connector(instance)
        except Exception as e:
            logger.error(f"Error loading connector class {connector_class.__name__}: {e}")
            traceback.print_exc()

    def get_connector(self, connector_id: str) -> Optional[BaseConnector]:
        return self.connectors.get(connector_id)

    def get_connectors_by_capability(self, capability: str) -> List[BaseConnector]:
        """
        Returns a list of loaded connectors that support the given capability.
        """
        matching = []
        for connector in self.connectors.values():
            if capability in connector.MANIFEST.get("capabilities", []):
                matching.append(connector)
        return matching
