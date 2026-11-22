# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
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

"""Service registry for framework-internal skills.

System skills (ainara/framework/system_skills/) are loaded
parameter-less by the middleware at import time, but some need live
framework objects (memory stores, LLMs) that only exist after the
ChatManager wires the application. Services registered here by the
owner component are fetched by skills at run() time, keeping
BaseSystemSkill's constructor-free load contract intact.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SERVICES: Dict[str, Any] = {}


def register_service(name: str, service: Any) -> None:
    """Register (or replace) a named service for system-skill use."""
    _SERVICES[name] = service
    logger.info("Service registry: registered %r", name)


def get_service(name: str) -> Optional[Any]:
    """Return a registered service, or None if not registered."""
    return _SERVICES.get(name)


def unregister_service(name: str) -> None:
    """Remove a service registration (owner teardown)."""
    if _SERVICES.pop(name, None) is not None:
        logger.info("Service registry: unregistered %r", name)
