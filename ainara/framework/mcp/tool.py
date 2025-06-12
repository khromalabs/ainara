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

"""
Represents a tool discovered from an MCP server.
"""


class MCPTool:
    """Represents a discovered MCP tool."""

    def __init__(
        self,
        server_name: str,
        name: str,
        description: str,
        input_schema: dict,
        prefixed_name: str,
    ):
        """
        Initialize an MCP tool.

        Args:
            server_name: Name of the MCP server this tool belongs to
            name: Original name of the tool (without prefix)
            description: Description of the tool
            input_schema: JSON schema describing the tool's input parameters
            prefixed_name: Name including the server's prefix
        """
        self.server_name = server_name
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.prefixed_name = prefixed_name  # Name including the prefix

    def __repr__(self):
        return (
            f"MCPTool(server='{self.server_name}',"
            f" name='{self.prefixed_name}')"
        )

    def format_for_llm(self) -> str:
        """Format tool information for LLM to closely mimic native skills with Annotated metadata."""
        args_desc = []
        if "properties" in self.input_schema:
            for param_name, param_info in self.input_schema.get(
                "properties", {}
            ).items():
                # Map JSON schema type to Python type
                param_type = param_info.get("type", "string")
                type_mapping = {
                    "string": "str",
                    "number": "float",
                    "integer": "int",
                    "boolean": "bool",
                    "object": "dict",
                    "array": "list",
                }
                python_type = type_mapping.get(param_type, param_type)

                # Handle array items type if specified
                if param_type == "array" and "items" in param_info:
                    item_type = param_info["items"].get("type", "any")
                    python_item_type = type_mapping.get(item_type, item_type)
                    python_type = f"List[{python_item_type}]"

                # Handle enum or literal types
                if "enum" in param_info and isinstance(
                    param_info["enum"], list
                ):
                    python_type = (
                        f"Literal[{', '.join([repr(opt) for opt in param_info['enum']])}]"
                    )

                # Build constraints description
                constraints = []
                if param_type == "string":
                    if "minLength" in param_info:
                        constraints.append(
                            f"min length: {param_info['minLength']}"
                        )
                    if "maxLength" in param_info:
                        constraints.append(
                            f"max length: {param_info['maxLength']}"
                        )
                    if "pattern" in param_info:
                        constraints.append(f"pattern: {param_info['pattern']}")
                elif param_type in ("number", "integer"):
                    if "minimum" in param_info:
                        constraints.append(f"minimum: {param_info['minimum']}")
                    if "maximum" in param_info:
                        constraints.append(f"maximum: {param_info['maximum']}")

                constraints_str = (
                    f", constraints: {'; '.join(constraints)}"
                    if constraints
                    else ""
                )

                # Extract description and default value
                param_desc = param_info.get(
                    "description", "No description provided"
                )
                param_default = param_info.get("default", None)
                default_str = (
                    f", default: {repr(param_default)}"
                    if param_default is not None
                    else ""
                )

                # Build the description line similar to Annotated style
                arg_desc = (
                    f"- {param_name}:"
                    f" {param_desc}"
                    f" (type: {python_type}{default_str}{constraints_str})"
                )
                if param_name in self.input_schema.get("required", []):
                    arg_desc += " (required)"
                args_desc.append(arg_desc)

        return f"""
Tool: {self.prefixed_name}
Description: {self.description}
Arguments:
{chr(10).join(args_desc) if args_desc else "None"}
"""
