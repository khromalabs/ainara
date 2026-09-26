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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentContext:
    """
    A context container for Agents that mimics the interface of ChatManager.

    This class acts as an adapter, allowing the OrakleMiddleware to operate
    on autonomous Agents without requiring modification to the middleware itself.
    It holds the agent's isolated state, history, and goal.
    """

    def __init__(
        self,
        goal: str,
        user_profile_summary: Optional[str] = None,
        initial_history: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Initialize the Agent Context.

        Args:
            goal: The specific goal or mission for this agent instance.
                  This maps to 'current_summary' in ChatManager.
            user_profile_summary: Information about the user (if available).
            initial_history: Optional starting history (e.g. system prompt).
        """
        # Map the Agent's goal to 'current_summary' so OrakleMiddleware
        # can inject it into the context for the LLM.
        self.current_summary = f"Agent Goal: {goal}"

        self.user_profile_summary = user_profile_summary or ""

        # The agent's internal monologue/history
        self.chat_history: List[Dict[str, Any]] = initial_history or []

    def add_message(self, role: str, content: str, **kwargs):
        """
        Add a message to the agent's history.

        Args:
            role: The role of the message sender (system, user, assistant).
            content: The content of the message.
            **kwargs: Additional metadata (e.g., tokens, sticky).
        """
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.chat_history.append(msg)

    def add_chat_history_to_params(
        self, params: Dict[str, Any], skill_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Injects chat history into skill parameters if requested by the skill.

        This replicates the logic from ChatManager.add_chat_history_to_params
        to ensure skills that need context (like summarizers) work within
        an Agent loop.

        Args:
            params: The parameters prepared for the skill execution.
            skill_info: The definition of the skill being executed.

        Returns:
            Updated parameters dict with history injected if needed.
        """
        # Check if skill requires chat history
        # We look for a parameter named "_chat_history"
        if any(
            param.get("name") == "_chat_history"
            for param in skill_info.get("parameters", [])
        ):
            params["_chat_history"] = self.prepare_chat_history_for_skill()
            logger.debug("Added chat history to agent skill params")

        return params

    def prepare_chat_history_for_skill(self) -> List[Dict[str, str]]:
        """
        Prepare chat history in a format suitable for skills.

        Filters out system messages and metadata, returning only the
        conversation flow.

        Returns:
            List of dicts with 'role' and 'content'.
        """
        formatted_history = []
        for msg in self.chat_history:
            # Only include user and assistant messages, skip system messages
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                if msg["role"] in ["user", "assistant"]:
                    formatted_history.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )
        return formatted_history
