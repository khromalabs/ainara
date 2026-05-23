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

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import yaml
from jsonschema import RefResolver, ValidationError, validate

logger = logging.getLogger(__name__)


class ConnectorRouter:
    """
    The central hub that routes semantic requests (Contracts) to
    concrete implementations (Connectors).

    It handles:
    1. Loading OpenAPI contracts.
    2. Registering connectors and their capabilities.
    3. Routing requests to the appropriate connector(s).
    4. Validating connector responses against the Contract schema.
    """

    # def __init__(self, contracts_dir: str, connectors_dir: str):
    def __init__(self, contracts_dir: str):
        self.contracts_dir = contracts_dir
        # self.connectors_dir = connectors_dir
        self.contracts: Dict[str, Dict] = {}  # Cache for loaded YAML specs
        self.routes: Dict[str, List[Dict]] = (
            {}
        )  # Map "contract:path:method" -> [handlers]
        self.resolvers: Dict[str, RefResolver] = (
            {}
        )  # JSON Schema resolvers per contract
        # # Load connectors, by now read all connectors present in directory
        # package_dir = os.path.dirname(self.connectors_dir)
        # for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
        #     # Skip base module and any module starting with underscore
        #     if module_name == "base" or module_name.startswith("_"):
        #         continue
        #     try:
        #         # Import the module
        #         module = importlib.import_module(f".{module_name}", __package__)
        #         self.register_connector(module)
        #     except Exception as e:
        #         logger.error(f"Error loading connector {module_name}: {str(e)}")

    def load_contract(self, contract_name: str) -> Optional[Dict]:
        """
        Loads and caches an OpenAPI YAML contract.
        """
        if contract_name in self.contracts:
            return self.contracts[contract_name]

        filename = f"{contract_name}.yml"
        path = os.path.join(self.contracts_dir, filename)

        if not os.path.exists(path):
            logger.error(f"Contract file not found: {path}")
            return None

        try:
            with open(path, "r") as f:
                spec = yaml.safe_load(f)
                self.contracts[contract_name] = spec
                # Create a resolver for $ref handling within this contract
                self.resolvers[contract_name] = RefResolver.from_schema(spec)
                logger.info(f"Loaded contract: {contract_name}")
                return spec
        except Exception as e:
            logger.error(f"Failed to load contract {contract_name}: {e}")
            return None

    def register_connector(self, connector: Any):
        """
        Inspects a connector instance for @capability decorated methods
        and registers them in the routing table.
        """

        # logger.info(f"REGISTERING CONNECTOR {connector}")

        if not hasattr(connector, "get_capabilities"):
            logger.warning(
                f"Connector {connector} does not support capability"
                " introspection."
            )
            return

        capabilities = connector.get_capabilities()
        for cap in capabilities:
            contract = cap["contract"]
            path = cap["path"]
            method = cap["method"]

            # Ensure contract is loaded
            if contract not in self.contracts:
                self.load_contract(contract)

            route_key = f"{contract}:{path}:{method}"
            if route_key not in self.routes:
                self.routes[route_key] = []

            self.routes[route_key].append(
                {"connector_id": connector.MANIFEST['id'], "handler": cap["handler"]}
            )
            logger.info(f"Registered route {route_key} -> {connector.MANIFEST['id']}")

    async def route_request(
        self,
        contract: str,
        path: str,
        method: str = "GET",
        params: Dict[str, Any] = None,
        target_connector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Routes a request to registered connectors.

        Args:
            contract: The contract name (e.g., 'messages')
            path: The API path (e.g., '/messages')
            method: HTTP method
            params: Arguments to pass to the handler
            target_connector: Optional ID to target a specific connector.
                              If None, queries all matching connectors (aggregation).

        Returns:
            A dictionary containing results from one or more connectors.
            Format: { "connector_id": result_data, ... }
        """
        method = method.upper()
        route_key = f"{contract}:{path}:{method}"

        if route_key not in self.routes:
            logger.warning(f"No handlers found for {route_key}")
            logger.warning(f"Routes available: {self.routes}")
            return {}

        results = {}
        tasks = []
        connector_map = {}  # task_index -> connector_id for async handlers
        sync_results = {}   # immediate results for sync handlers
        handlers = self.routes[route_key]

        for i, handler_info in enumerate(handlers):
            c_id = handler_info["connector_id"]

            # Skip if targeting specific connector
            if target_connector and c_id != target_connector:
                continue

            func = handler_info["handler"]
            try:
                args = params or {}
                coro_or_result = func(**args)

                if asyncio.iscoroutine(coro_or_result):
                    # Async handler: schedule task
                    task = asyncio.create_task(coro_or_result)
                    tasks.append(task)
                    connector_map[len(tasks) - 1] = c_id
                else:
                    # Sync handler: process immediately
                    if self._validate_response(contract, path, method, coro_or_result):
                        sync_results[c_id] = coro_or_result
                    else:
                        logger.error(f"Response from {c_id} failed validation for {route_key}")

            except Exception as e:
                logger.error(f"Error executing connector {c_id} for {route_key}: {e}")

        # Await all async tasks in parallel
        results.update(sync_results)
        if tasks:
            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            for idx, data_or_exc in enumerate(gathered):
                c_id = connector_map[idx]
                if isinstance(data_or_exc, Exception):
                    logger.error(f"Async handler {c_id} failed: {data_or_exc}")
                    continue
                try:
                    if self._validate_response(contract, path, method, data_or_exc):
                        results[c_id] = data_or_exc
                    else:
                        logger.error(f"Response from {c_id} failed validation for {route_key}")
                except Exception as e:
                    logger.error(f"Validation error for {c_id}: {e}")

        return results

    def _validate_response(
        self, contract_name: str, path: str, method: str, data: Any
    ) -> bool:
        """
        Validates the data returned by a connector against the OpenAPI schema.
        """
        spec = self.contracts.get(contract_name)
        if not spec:
            return False

        try:
            # Navigate the OpenAPI spec to find the response schema
            # We assume '200' OK response for successful execution
            operation = (
                spec.get("paths", {}).get(path, {}).get(method.lower(), {})
            )
            schema = (
                operation.get("responses", {})
                .get("200", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )

            if not schema:
                # If no schema is defined, we assume any result is valid (or void)
                return True

            resolver = self.resolvers.get(contract_name)
            validate(instance=data, schema=schema, resolver=resolver)
            return True

        except ValidationError as ve:
            logger.warning(f"Schema validation error: {ve.message}")
            return False
        except Exception as e:
            logger.error(f"Unexpected validation error: {e}")
            return False
