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
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


def capability(contract: str, path: str, method: str = "GET"):
    """
    Decorator to mark a method as a capability handler for a specific contract route.

    Args:
        contract: The name of the contract file (e.g., 'messages' for messages.yml)
        path: The API path defined in the contract (e.g., '/messages')
        method: The HTTP verb (default: 'GET')
    """

    def decorator(func: Callable):
        if not hasattr(func, "_capability_meta"):
            func._capability_meta = []

        # Store metadata on the function itself
        func._capability_meta.append(
            {"contract": contract, "path": path, "method": method.upper()}
        )
        return func

    return decorator


class BaseConnector:
    """
    Base class for Connectors in the Contract-Driven architecture.
    Connectors expose capabilities via @capability decorated methods rather
    than implementing abstract methods.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.id = self.MANIFEST.get("id", "unknown_connector")
        self._validate_config()
        self.initialize()

    @property
    def MANIFEST(self) -> Dict[str, Any]:
        """
        Returns the connector manifest.
        Should be overridden by subclasses to define 'id', 'required_config', etc.
        """
        return {}

    def initialize(self):
        """Optional hook for post-init setup (e.g. setting up clients)."""
        pass

    def _validate_config(self):
        """Ensures all keys listed in MANIFEST['required_config'] are present."""
        required = self.MANIFEST.get("required_config", [])
        missing = [key for key in required if not self.config.get(key)]

        if missing:
            raise ValueError(
                f"Connector '{self.id}' missing required configuration keys:"
                f" {missing}"
            )

    def get_capabilities(self) -> List[Dict[str, Any]]:
        """
        Introspects the instance to find methods decorated with @capability.
        Returns a list of capability definitions used by the ConnectorRouter.
        """
        caps = []
        # Inspect all methods of the instance
        for attr_name in dir(self):
            try:
                attr = getattr(self, attr_name)
                if hasattr(attr, "_capability_meta"):
                    for meta in attr._capability_meta:
                        caps.append(
                            {
                                "contract": meta["contract"],
                                "path": meta["path"],
                                "method": meta["method"],
                                "handler": attr,
                            }
                        )
            except Exception as e:
                logger.warning(
                    f"Error inspecting attribute {attr_name} on {self.id}: {e}"
                )
                continue
        return caps
