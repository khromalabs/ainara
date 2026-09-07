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

import datetime
from typing import Annotated, Any, Dict

from ainara.framework.skill import Skill

# test it in Polaris with:
# /testuserui ToolsHello {"success": true, "message": "Hello, John!", "timestamp": "2025-04-14T12:00:00"}


class ToolsHello(Skill):
    """A simple test skill that returns a greeting and a timestamp."""

    matcher_info = (
        "Use this skill to say hello or test the system. "
        "Keywords: hello, hi, test, ping."
    )

    async def run(
        self,
        name: Annotated[str, "The name of the person to greet"] = "World",
    ) -> Dict[str, Any]:
        """Returns a greeting message and the current timestamp."""
        timestamp = datetime.datetime.now().isoformat()
        message = f"Hello, {name}!"
        return {
            "success": True,
            "message": message,
            "timestamp": timestamp,
        }
