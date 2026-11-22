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

"""Deep Recall as a system skill.

A thin adapter: the conversation model reaches Deep Recall through the
ordinary ORAKLE channel (a normal <orakle> recall query), the selection
flow picks this skill like any other, and run() delegates to the
DeepRecallEngine fetched from the service registry. The engine is wired
by the ChatManager (it owns the corpus objects), not at skill load time.
"""

from typing import Any, Dict, Optional

from ainara.framework.skills.register import get_service
from ainara.framework.system_skills.base import BaseSystemSkill


class SystemSkillDeepRecall(BaseSystemSkill):
    """Deliberative recall of the user's own past: memories + logs."""

    @property
    def name(self) -> str:
        return "deep_recall"

    @property
    def description(self) -> str:
        return (
            "Deep Recall: recover the full picture of past events,"
            " shared history, previous conversations and past decisions"
            " from the user's memories and conversation records."
        )

    @property
    def matcher_info(self) -> str:
        return (
            "The user asks to recall, remember, revisit or reconstruct"
            " something from their OWN past: what they said or decided"
            " before, previous conversations, shared history, personal"
            " events, plans made earlier, 'what did we say/talk about',"
            " 'remember when', 'do you recall', 'lo que hablamos',"
            " 'recuerda cuando'. Also for checking the recorded history"
            " before stating anything about past events. NOT for general"
            " knowledge, encyclopedic or historical facts about the"
            " world, web search, or current/real-time information."
        )

    @property
    def run_info(self) -> Dict[str, Any]:
        return {
            "info": (
                "Pass the recall topic as the query: the events, topic"
                " or period to reconstruct from the recorded history."
            ),
            "parameters": {
                "timeframe": {
                    "type": "string",
                    "required": False,
                    "default": None,
                    "description": (
                        "Approximate period the recalled events happened,"
                        " as the user stated it (e.g. 'a few days ago',"
                        " 'last week', 'in March'). Optional; scopes the"
                        " history search and cuts investigation time."
                    ),
                },
            },
        }

    def run(
        self,
        query: str,
        parameters: dict,
        chat_history: Optional[list] = None,
    ) -> Dict[str, Any]:
        # Third positional arg receives the conversation history from
        # the middleware call site (legacy positional contract of
        # BaseSystemSkill.run; named for what it actually is).
        engine = get_service("deep_recall_engine")
        if engine is None:
            return {
                "success": False,
                "error": (
                    "Deep Recall engine is not available in this session."
                ),
            }
        params = parameters or {}
        result = engine.run(
            query,
            history_tail=chat_history,
            timeframe=params.get("timeframe"),
        )
        if result is None:
            return {
                "success": False,
                "error": (
                    "The recall investigation could not be completed."
                ),
            }
        return result
