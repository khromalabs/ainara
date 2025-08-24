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
from typing import Any, Dict

from ainara.framework.mcp.client_manager import MCPClientManager
from ainara.framework.mcp.tool import MCPTool

from .base import CapabilityProvider

logger = logging.getLogger(__name__)


class MCPToolProvider(CapabilityProvider):
    """Provider for discovering and executing MCP tools."""

    def __init__(self, mcp_client_manager: MCPClientManager):
        self.mcp_client_manager = mcp_client_manager
        self.capabilities: Dict[str, Dict[str, Any]] = {}

    def discover(self) -> Dict[str, Dict[str, Any]]:
        """Discover MCP tools and add them to the capabilities dictionary."""
        self.capabilities = {}
        if not self.mcp_client_manager:
            logger.info("MCP Client Manager not available, skipping MCP tool discovery.")
            return {}

        logger.info("Discovering MCP tools...")
        discovered_count = 0
        try:
            mcp_tools = self.mcp_client_manager.connect_and_discover()
            for tool in mcp_tools:
                capability_info = {
                    "instance": tool,
                    "type": "mcp",
                    "origin": "remote",
                    "description": tool.description,
                    "server": tool.server_name,
                    "hidden": False,
                    "run_info": self._get_mcp_tool_details(tool),
                }
                self.capabilities[tool.prefixed_name] = capability_info
                discovered_count += 1
                logger.info(
                    f"Discovered MCP tool: {tool.prefixed_name} from"
                    f" {tool.server_name}"
                )
        except Exception as e:
            logger.error(f"Failed during MCP tool discovery: {e}", exc_info=True)

        logger.info(f"Discovered {discovered_count} MCP tools.")
        return self.capabilities

    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute an MCP tool."""
        if not self.mcp_client_manager:
            raise RuntimeError("MCP Client Manager not available for execution.")

        logger.info(f"Executing MCP tool: {name} with args: {arguments}")
        try:
            return self.mcp_client_manager.execute_tool(name, arguments)
        except Exception as e:
            logger.error(f"Error executing MCP tool '{name}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to execute MCP tool '{name}': {e}") from e

    def format_for_llm(self, capability_data: Dict[str, Any]) -> str:
        """Format an MCP tool's description for an LLM prompt."""
        instance = capability_data["instance"]
        if hasattr(instance, "format_for_llm"):
            return instance.format_for_llm() + "---\n"

        # Fallback formatting
        name = next(
            (k for k, v in self.capabilities.items() if v == capability_data), None
        )
        if not name:
            return ""

        run_info = capability_data.get("run_info", {})
        params = run_info.get("parameters", {})
        desc = f"Tool: {name}\n"
        desc += f"Description: {capability_data['description']}\n"
        desc += f"Server: {capability_data['server']}\n"
        if params:
            desc += "Arguments:\n"
            for p_name, p_info in params.items():
                desc += f"- {p_name} (type: {p_info['type']})"
                if p_info["required"]:
                    desc += " (required)"
                desc += f": {p_info['description']}\n"
        return desc + "---\n"

    def _get_mcp_tool_details(self, tool: MCPTool) -> Dict[str, Any]:
        """Format MCP tool details similar to native skill run_info."""
        details = {
            "description": (
                f"Executes the MCP tool '{tool.name}' on server"
                f" '{tool.server_name}'."
            ),
            "parameters": {},
            "return_type": "any",
            "error": None,
        }
        try:
            if "properties" in tool.input_schema:
                required_params = tool.input_schema.get("required", [])
                for param_name, param_schema in tool.input_schema[
                    "properties"
                ].items():
                    details["parameters"][param_name] = {
                        "type": param_schema.get("type", "any"),
                        "default": "None",
                        "required": param_name in required_params,
                        "description": param_schema.get(
                            "description", "No description provided."
                        ),
                    }
        except Exception as e:
            logger.error(
                "Error parsing input schema for MCP tool"
                f" '{tool.prefixed_name}': {e}",
                exc_info=True,
            )
            details["error"] = f"Failed to parse input schema: {e}"
        return details
