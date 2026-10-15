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


__version__ = "0.11.1"
__version_info__ = (0,11,1)


def _use_system_dns_for_aiohttp():
    """Resolve aiohttp hostnames through the OS resolver, not aiodns.

    aiohttp defaults to aiodns whenever it is installed (ccxt pulls it
    in). aiodns queries DNS servers directly, bypassing the system
    resolver, so it fails wherever only the OS resolver may reach DNS:
    e.g. VPN clients with DNS-leak protection, which drop direct queries
    even to the VPN's own server. Every async LiteLLM call and every ccxt
    exchange call then times out. The threaded resolver is aiohttp's own
    default when aiodns is absent.
    """
    try:
        import aiohttp.connector
        import aiohttp.resolver
    except ImportError:
        return
    aiohttp.connector.DefaultResolver = aiohttp.resolver.ThreadedResolver


_use_system_dns_for_aiohttp()
