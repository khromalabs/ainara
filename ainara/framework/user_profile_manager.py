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


import json
import logging
import os
# from datetime import datetime, timezone
from typing import Any, Dict, List

from ainara.framework.chat_memory import ChatMemory
from ainara.framework.config import config
from ainara.framework.llm.base import LLMBackend
from ainara.framework.template_manager import TemplateManager

logger = logging.getLogger(__name__)


class UserProfileManager:
    """Manages the user's semantic profile (beliefs, preferences, facts)."""

    def __init__(self, llm: LLMBackend, chat_memory: ChatMemory):
        self.llm = llm
        self.chat_memory = chat_memory
        self.profile_path = os.path.join(
            config.get("data.directory"), "user_profile.json"
        )
        self.template_manager = TemplateManager()
        self.profile = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        """Loads the user profile from disk, or creates a default one."""
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    logger.info(f"Loading user profile from {self.profile_path}")
                    profile = json.load(f)
                    # Ensure essential keys exist for backward compatibility
                    profile.setdefault("key_beliefs", {})
                    profile.setdefault("last_processed_timestamp", None)
                    return profile
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading profile, creating a new one: {e}")
        # Default structure for a new profile
        return {"key_beliefs": {}, "last_processed_timestamp": None}

    def _save_profile(self):
        """Saves the current profile to disk."""
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.profile, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save user profile: {e}")

    def get_relevant_beliefs(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        Finds beliefs relevant to the user's query.
        NOTE: This is a simple keyword-based search for the draft. A real
        implementation should use semantic vector search on the beliefs for better accuracy.
        """
        relevant_beliefs = []
        all_beliefs = [
            b
            for topic_beliefs in self.profile.get("key_beliefs", {}).values()
            for b in topic_beliefs
        ]

        # Very simple relevance logic based on keyword matching
        query_words = set(query.lower().split())
        for belief in sorted(
            all_beliefs, key=lambda b: b["last_updated"], reverse=True
        ):
            if any(word in belief["belief"].lower() for word in query_words):
                if len(relevant_beliefs) < top_k:
                    relevant_beliefs.append(belief)

        return relevant_beliefs

    # def process_new_messages_for_update(self):
    #     """
    #     Fetches all new messages since the last update, processes them in
    #     conversation turns, and updates the user profile.
    #     """
    #     last_timestamp = self.profile.get("last_processed_timestamp")
    #     logger.info(
    #         f"Starting profile update. Checking for messages since: {last_timestamp}"
    #     )
    #
    #     # Fetch all messages since the last processed timestamp
    #     new_messages = self.chat_memory.storage.get_messages_since(last_timestamp)
    #
    #     if not new_messages:
    #         logger.info("No new messages to process for profile update.")
    #         return
    #
    #     logger.info(f"Found {len(new_messages)} new messages to process.")
    #
    #     # Group messages into user/assistant turns
    #     conversation_turns = []
    #     for i, message in enumerate(new_messages):
    #         if message.get("role") == "assistant" and i > 0:
    #             prev_message = new_messages[i - 1]
    #             if prev_message.get("role") == "user":
    #                 conversation_turns.append((prev_message, message))
    #
    #     if not conversation_turns:
    #         logger.info("No complete user/assistant turns found in new messages.")
    #         # Update timestamp anyway to avoid reprocessing these single messages
    #         self.profile["last_processed_timestamp"] = new_messages[-1].get(
    #             "timestamp"
    #         )
    #         self._save_profile()
    #         return
    #
    #     logger.info(f"Processing {len(conversation_turns)} new conversation turns.")
    #     for user_msg, assistant_msg in conversation_turns:
    #         self.extract_and_update_belief(user_msg, assistant_msg)
    #
    #     # After processing all turns, update the timestamp to the last message processed
    #     latest_timestamp = new_messages[-1].get("timestamp")
    #     self.profile["last_processed_timestamp"] = latest_timestamp
    #     self._save_profile()
    #     logger.info(
    #         f"Profile update complete. New timestamp: {latest_timestamp}"
    #     )

    # def _extract_and_update_belief(
    #     self, user_message: Dict, assistant_message: Dict
    # ):
    #     """
    #     Runs the LLM on a single conversation turn to extract and save a belief.
    #     """
    #     try:
    #         conversation_snippet = (
    #             f"User: {user_message['content']}\n"
    #             f"Assistant: {assistant_message['content']}"
    #         )
    #
    #         prompt = self.template_manager.render(
    #             "framework.user_profile_manager.extract_belief",
    #             {"conversation_snippet": conversation_snippet},
    #         )
    #
    #         # Use a dedicated history for this one-off task
    #         extraction_history = []
    #         self.llm.add_msg(
    #             "You are a helpful memory analysis system that extracts structured data from conversations.",
    #             extraction_history,
    #             "system",
    #         )
    #         self.llm.add_msg(prompt, extraction_history, "user")
    #
    #         response_str = self.llm.chat(chat_history=extraction_history, stream=False)
    #
    #         # The LLM should return a JSON object or "None"
    #         if response_str.strip().lower() == "none":
    #             logger.info("LLM determined no new belief to be extracted.")
    #             return
    #
    #         new_belief_data = json.loads(response_str)
    #         topic = new_belief_data.get("topic", "general")
    #
    #         # Add provenance and timestamp
    #         new_belief_data["source_message_ids"] = [
    #             user_message.get("id"),
    #             assistant_message.get("id"),
    #         ]
    #         new_belief_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    #
    #         # Add to profile (non-destructive append-only model)
    #         if topic not in self.profile["key_beliefs"]:
    #             self.profile["key_beliefs"][topic] = []
    #         self.profile["key_beliefs"][topic].append(new_belief_data)
    #
    #         self._save_profile()
    #         logger.info(f"Updated user profile with new belief on topic: {topic}")
    #
    #     except json.JSONDecodeError:
    #         logger.warning(f"LLM returned invalid JSON for belief extraction: {response_str}")
    #     except Exception as e:
    #         logger.error(f"Failed to update user profile from conversation: {e}")
