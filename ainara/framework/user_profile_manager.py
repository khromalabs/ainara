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
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from ainara.framework.chat_memory import ChatMemory
from ainara.framework.config import config
from ainara.framework.llm.base import LLMBackend
from ainara.framework.storage import get_vector_backend
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

        # Ensure all beliefs have a unique ID and save profile if changed
        profile_updated = False
        for beliefs in self.profile.get("key_beliefs", {}).values():
            for belief in beliefs:
                if "id" not in belief:
                    belief["id"] = str(uuid.uuid4())
                    profile_updated = True
        if profile_updated:
            logger.info(
                "Added unique IDs to one or more beliefs. Saving profile."
            )
            self._save_profile()

        # Initialize vector storage for beliefs
        vector_type = config.get(
            "user_profile.vector_storage.type",
            config.get("memory.vector_storage.type", "chroma"),
        )
        vector_path = config.get(
            "user_profile.vector_storage.path",
            config.get(
                "memory.vector_db_path",
                os.path.join(config.get("data.directory"), "vector_db"),
            ),
        )
        embedding_model = config.get(
            "user_profile.vector_storage.embedding_model",
            config.get(
                "memory.vector_storage.embedding_model",
                "sentence-transformers/all-mpnet-base-v2",
            ),
        )

        # Ensure path is expanded
        vector_path = os.path.expanduser(vector_path)
        try:
            self.vector_storage = get_vector_backend(
                vector_type,
                vector_db_path=vector_path,
                embedding_model=embedding_model,
                collection_name="user_profile_beliefs",
            )
            logger.info(
                f"Using {vector_type} vector backend for user profile beliefs"
            )
            # Sync profile to vector store on startup
            self._sync_profile_to_vector_store()
        except ImportError:
            logger.warning(
                f"Vector storage backend '{vector_type}' dependencies not"
                " found. User profile search will fall back to keyword"
                " matching."
            )
            self.vector_storage = None
        except Exception as e:
            logger.error(
                f"Failed to initialize vector storage for profile: {e}"
            )
            self.vector_storage = None

    def _load_profile(self) -> Dict[str, Any]:
        """Loads the user profile from disk, or creates a default one."""
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    logger.info(
                        f"Loading user profile from {self.profile_path}"
                    )
                    profile = json.load(f)
                    # Ensure essential keys exist for backward compatibility
                    profile.setdefault("key_beliefs", {})
                    profile.setdefault("extended_beliefs", {})
                    profile.setdefault("last_processed_timestamp", None)
                    return profile
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading profile, creating a new one: {e}")
        # Default structure for a new profile
        new_profile = {
            "key_beliefs": {},
            "extended_beliefs": {},
            "last_processed_timestamp": None,
        }
        self._save_profile(new_profile)
        return profile

    def _save_profile(self, local_profile=None):
        """Saves the current profile to disk."""
        try:
            if local_profile:
                self.profile = local_profile
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.profile, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save user profile: {e}")

    def _sync_profile_to_vector_store(self):
        """Clears and rebuilds the belief vector index from the profile."""
        if not self.vector_storage:
            logger.debug(
                "Vector storage not available, skipping profile sync."
            )
            return

        logger.info("Syncing user profile beliefs to vector store...")
        self.vector_storage.reset()  # Clear the collection

        all_beliefs = [
            b
            for topic_beliefs in self.profile.get(
                "extended_beliefs", {}
            ).values()
            for b in topic_beliefs
        ]

        if not all_beliefs:
            logger.info("No extended beliefs found in profile to index.")
            return

        documents_to_add = []
        for belief in all_beliefs:
            # The document content is the belief text itself
            content = belief.get("belief", "")
            if not content:
                continue

            # The metadata will be the entire belief object
            metadata = belief.copy()
            documents_to_add.append(
                {"page_content": content, "metadata": metadata}
            )

        if documents_to_add:
            self.vector_storage.add_documents(documents_to_add)
            logger.info(
                f"Successfully indexed {len(documents_to_add)} extended"
                " beliefs in vector store."
            )

    def get_key_beliefs(self) -> List[Dict]:
        """Returns a flat list of all key beliefs."""
        return [
            belief
            for topic_beliefs in self.profile.get("key_beliefs", {}).values()
            for belief in topic_beliefs
        ]

    def get_relevant_beliefs(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        Finds beliefs relevant to the user's query using semantic vector
        search, with a fallback to keyword matching.
        """
        # Use vector search if available
        if self.vector_storage:
            try:
                logger.info(
                    "Performing semantic search for extended beliefs with"
                    f" query: '{query}'"
                )
                results = self.vector_storage.search(query, limit=top_k)
                # The search result contains documents; extract the original
                # belief from the metadata of each document.
                return [doc.get("metadata", {}) for doc in results]
            except Exception as e:
                logger.error(
                    f"Vector search for beliefs failed: {e}. Falling back to"
                    " keyword search."
                )

        raise RuntimeError("VectorDB required")

    def process_new_messages_for_update(self):
        """
        Fetches all new messages since the last update, processes them in
        conversation turns, and updates the user profile.
        """
        last_timestamp = self.profile.get("last_processed_timestamp")
        logger.info(
            "Starting profile update. Checking for messages since:"
            f" {last_timestamp}"
        )

        # Fetch all messages since the last processed timestamp
        new_messages = self.chat_memory.storage.get_messages_since(
            last_timestamp
        )

        if not new_messages:
            logger.info("No new messages to process for profile update.")
            return

        logger.info(f"Found {len(new_messages)} new messages to process.")

        # Group messages into user/assistant turns
        conversation_turns = []
        for i, message in enumerate(new_messages):
            if message.get("role") == "assistant" and i > 0:
                prev_message = new_messages[i - 1]
                if prev_message.get("role") == "user":
                    conversation_turns.append((prev_message, message))

        if not conversation_turns:
            logger.info(
                "No complete user/assistant turns found in new messages."
            )
            # Update timestamp anyway to avoid reprocessing these single messages
            self.profile["last_processed_timestamp"] = new_messages[-1].get(
                "timestamp"
            )
            self._save_profile()
            return

        logger.info(
            f"Processing {len(conversation_turns)} new conversation turns."
        )
        for user_msg, assistant_msg in conversation_turns:
            self._extract_and_update_belief(user_msg, assistant_msg)

        # After processing all turns, update the timestamp to the last message processed
        latest_timestamp = new_messages[-1].get("timestamp")
        self.profile["last_processed_timestamp"] = latest_timestamp
        self._save_profile()
        logger.info(
            f"Profile update complete. New timestamp: {latest_timestamp}"
        )

    def _extract_and_update_belief(
        self, user_message: Dict, assistant_message: Dict
    ):
        """
        Runs the LLM on a single conversation turn to extract and save a belief.
        """
        try:
            conversation_snippet = (
                f"User: {user_message['content']}\n"
                f"Assistant: {assistant_message['content']}"
            )

            prompt = self.template_manager.render(
                "framework.user_profile_manager.extract_belief",
                {"conversation_snippet": conversation_snippet},
            )

            # Use a dedicated history for this one-off task
            extraction_history = []
            self.llm.add_msg(
                "You are a helpful memory analysis system that extracts"
                " structured data from conversations.",
                extraction_history,
                "system",
            )
            self.llm.add_msg(prompt, extraction_history, "user")

            response_str = self.llm.chat(
                chat_history=extraction_history, stream=False
            )

            # The LLM should return a JSON object or "None"
            if response_str.strip().lower() == "none":
                logger.info("LLM determined no new belief to be extracted.")
                return

            response_data = json.loads(response_str)
            target_section = response_data.get("target", "extended_beliefs")
            new_belief = response_data.get("belief_data", {})

            if not new_belief or not new_belief.get("belief"):
                logger.warning("LLM returned empty belief data. Skipping.")
                return

            if target_section not in ["key_beliefs", "extended_beliefs"]:
                logger.warning(
                    f"LLM returned invalid target section: '{target_section}'."
                    " Defaulting to extended_beliefs."
                )
                target_section = "extended_beliefs"

            topic = new_belief.get("topic", "general")

            # Add provenance and timestamp
            new_belief["source_message_ids"] = [
                user_message.get("id"),
                assistant_message.get("id"),
            ]
            new_belief["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Add to profile (non-destructive append-only model)
            self.profile[target_section].setdefault(topic, []).append(
                new_belief
            )

            self._save_profile()
            logger.info(
                f"Added new belief to '{target_section}' under topic: {topic}"
            )

        except json.JSONDecodeError:
            logger.warning(
                "LLM returned invalid JSON for belief extraction:"
                f" {response_str}"
            )
        except Exception as e:
            logger.error(
                f"Failed to update user profile from conversation: {e}"
            )
