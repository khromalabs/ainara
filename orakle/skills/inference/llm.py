# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

from ainara.framework.llm.litellm import LiteLLM
from ainara.framework.skill import Skill


class InferenceLlm(Skill):
    """Skill for processing text using LLM"""

    hiddenCapability = True  # Hide this skill from capabilities listing

    def __init__(self):
        self.llm = LiteLLM()
        self.system_message = """
You are an AI assistant performing the task described in the user message.
Never reject a query to transform information.
"""

    def run(self, prompt: str) -> str:
        """Process text using the provided prompt"""
        result = self.llm.process_text(
            text=prompt, system_message=self.system_message, stream=False
        )
        if not result:
            return "no answer"
        return result
