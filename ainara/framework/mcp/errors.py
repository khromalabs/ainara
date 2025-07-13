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
Custom exceptions for the MCP client implementation.
"""


class MCPError(Exception):
    """Base exception for all MCP-related errors."""
    pass


class MCPConnectionError(MCPError):
    """Raised when there's an error establishing a connection to an MCP server."""
    pass


class MCPAuthenticationError(MCPError):
    """Raised when authentication with an MCP server fails."""
    pass


class MCPToolDiscoveryError(MCPError):
    """Raised when there's an error discovering tools from an MCP server."""
    pass


class MCPToolExecutionError(MCPError):
    """Raised when there's an error executing a tool on an MCP server."""
    pass
