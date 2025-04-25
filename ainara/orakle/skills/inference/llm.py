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


from typing import Annotated

from ainara.framework.config import ConfigManager
from ainara.framework.llm import create_llm_backend
from ainara.framework.skill import Skill


class InferenceLlm(Skill):
    """Skill for processing text using LLM"""

    hiddenCapability = True  # Hide this skill from capabilities listing

    def __init__(self):
        config = ConfigManager()
        config.load_config()
        self.llm = create_llm_backend(config.get("llm", {}))
        self.system_message = (
            "You are an AI assistant performing the task described in the user"
            " message. Never reject a query to transform information."
        )

    def run(
        self,
        prompt: Annotated[
            str, "Text prompt to be processed by the language model"
        ],
    ) -> str:
        """Processes text using a language model"""
        result = self.llm.chat(
            self.llm.prepare(text=prompt, system_message=self.system_message),
            stream=False,
        )
        if not result:
            return "no answer"
        return result
