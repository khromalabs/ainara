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
        self.storage = chat_memory.storage
        self.template_manager = TemplateManager()

        # This path is only needed for the one-time migration
        self.profile_path = os.path.join(
            config.get("data.directory"), "user_profile.json"
        )

        # Setup database table for beliefs
        self._create_beliefs_table()

        # Run a one-time migration from the old JSON file if it exists
        self._run_migration()

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
            # Sync profile to vector store on startup only if needed
            needs_reset = self.storage.get_metadata("vector_db_needs_reset")
            if needs_reset == "true":
                logger.info("Vector DB needs reset. Starting full sync...")
                self._sync_profile_to_vector_store()
            else:
                logger.info("Vector DB is consistent. Skipping startup sync.")
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

    def _create_beliefs_table(self):
        """Creates the user_beliefs table in the database if it doesn't exist."""
        try:
            with self.storage.conn:
                self.storage.conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_beliefs (
                        id TEXT PRIMARY KEY,
                        belief_type TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        belief TEXT NOT NULL,
                        relevance REAL NOT NULL DEFAULT 1.0,
                        last_updated TEXT NOT NULL,
                        source_message_ids TEXT,
                        confidence REAL,
                        metadata TEXT
                    )
                    """
                )
                self.storage.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_beliefs_topic ON"
                    " user_beliefs(topic);"
                )
                self.storage.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_beliefs_type ON"
                    " user_beliefs(belief_type);"
                )
            logger.debug("user_beliefs table checked/created successfully.")
        except Exception as e:
            logger.error(f"Failed to create user_beliefs table: {e}")
            raise

    def _run_migration(self):
        """Migrates data from user_profile.json to the database if needed."""
        if not os.path.exists(self.profile_path):
            return  # No old file to migrate

        try:
            # Check if the beliefs table is empty
            cursor = self.storage.conn.cursor()
            cursor.execute("SELECT COUNT(id) FROM user_beliefs")
            if cursor.fetchone()[0] > 0:
                logger.info(
                    "Beliefs table is not empty. Skipping migration from JSON."
                )
                return

            logger.info(
                "Found user_profile.json and empty beliefs table. Starting"
                " migration..."
            )
            with open(self.profile_path, "r", encoding="utf-8") as f:
                old_profile = json.load(f)

            beliefs_to_add = []
            for belief_type in ["key_beliefs", "extended_beliefs"]:
                for topic, topic_beliefs in old_profile.get(
                    belief_type, {}
                ).items():
                    for belief in topic_beliefs:
                        beliefs_to_add.append(
                            (
                                belief.get("id", str(uuid.uuid4())),
                                belief_type,
                                belief.get("topic", topic),
                                belief.get("belief"),
                                belief.get("relevance", 1.0),
                                belief.get(
                                    "last_updated",
                                    datetime.now(timezone.utc).isoformat(),
                                ),
                                json.dumps(belief.get("source_message_ids")),
                                belief.get("confidence"),
                                json.dumps(belief.get("metadata")),
                            )
                        )

            if beliefs_to_add:
                with self.storage.conn:
                    self.storage.conn.executemany(
                        """
                        INSERT INTO user_beliefs (id, belief_type, topic, belief, relevance, last_updated, source_message_ids, confidence, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        beliefs_to_add,
                    )
                logger.info(
                    f"Successfully migrated {len(beliefs_to_add)} beliefs from"
                    " JSON to SQLite."
                )

            # Rename the old file to prevent re-migration
            os.rename(self.profile_path, f"{self.profile_path}.migrated")
            logger.info(f"Renamed {self.profile_path} to avoid re-migration.")
            self.storage.set_metadata("vector_db_needs_reset", "true")
            logger.info(
                "Flagged vector DB for reset on next startup due to migration."
            )

        except Exception as e:
            logger.error(f"Error during profile migration from JSON: {e}")

    def _dict_from_row(self, row: Any) -> Dict:
        """Converts a sqlite3.Row to a dictionary and parses JSON fields."""
        if not row:
            return {}
        belief = dict(row)
        for key in ["source_message_ids", "metadata"]:
            if belief.get(key) and isinstance(belief[key], str):
                try:
                    belief[key] = json.loads(belief[key])
                except json.JSONDecodeError:
                    logger.warning(
                        f"Could not decode JSON for key '{key}' in belief ID"
                        f" {belief.get('id')}"
                    )
                    belief[key] = None
        return belief

    def _sync_profile_to_vector_store(self):
        import time

        """Clears and rebuilds the belief vector index from the profile."""
        if not self.vector_storage:
            logger.debug(
                "Vector storage not available, skipping profile sync."
            )
            return

        start_time = time.time()
        logger.info("Syncing user profile beliefs to vector store...")
        self.vector_storage.reset()  # Clear the collection

        cursor = self.storage.conn.cursor()
        cursor.execute(
            "SELECT * FROM user_beliefs WHERE belief_type = 'extended_beliefs'"
        )
        all_beliefs = [self._dict_from_row(row) for row in cursor.fetchall()]

        if not all_beliefs:
            logger.info("No extended beliefs found in profile to index.")
            return

        documents_to_add = []
        for belief in all_beliefs:
            content = belief.get("belief", "")
            if not content:
                continue
            metadata = belief.copy()
            documents_to_add.append(
                {"page_content": content, "metadata": metadata}
            )

        if documents_to_add:
            self.vector_storage.add_documents(documents_to_add)
            duration = time.time() - start_time
            logger.info(
                f"Successfully indexed {len(documents_to_add)} extended"
                " beliefs in vector store. Operation took"
                f" {duration:.2f} seconds."
            )

        # After a successful sync, clear the flag
        self.storage.set_metadata("vector_db_needs_reset", "false")
        logger.info("Vector DB sync complete. Cleared reset flag.")

    def get_key_beliefs(self) -> List[Dict]:
        """Returns a flat list of all key beliefs from the database."""
        cursor = self.storage.conn.cursor()
        cursor.execute(
            "SELECT * FROM user_beliefs WHERE belief_type = 'key_beliefs'"
            " ORDER BY relevance DESC"
        )
        return [self._dict_from_row(row) for row in cursor.fetchall()]

    def is_empty(self) -> bool:
        """Checks if the user profile contains any beliefs."""
        try:
            cursor = self.storage.conn.cursor()
            # We just need to know if at least one row exists.
            cursor.execute("SELECT 1 FROM user_beliefs LIMIT 1")
            return cursor.fetchone() is None
        except Exception as e:
            logger.error(f"Failed to check if profile is empty: {e}")
            return False  # Safer to assume not empty on error

    def get_relevant_beliefs(
        self, query: str, top_k: int = 3, relevance_weight: float = 0.3
    ) -> List[Dict]:
        """
        Finds beliefs relevant to the user's query using semantic vector
        search, re-ranking results based on the belief's relevance score.
        """
        if not self.vector_storage:
            raise RuntimeError(
                "Vector storage is required for belief retrieval."
            )

        try:
            # Fetch more results initially to allow for re-ranking
            initial_results_count = top_k * 3
            logger.info(
                "Performing semantic search for extended beliefs with"
                f" query: '{query}'"
            )
            # The search result from Chroma includes distances (lower is better)
            results_with_distances = self.vector_storage.search_with_scores(
                query, limit=initial_results_count
            )

            if not results_with_distances:
                return []

            ranked_beliefs = []
            for doc, score in results_with_distances:
                belief = doc.get("metadata", {})
                relevance = belief.get("relevance", 1.0)
                # Normalize semantic score (distance) to be higher-is-better
                # Assuming distance is between 0 and ~2. A simple inversion works.
                semantic_score = 1 / (1 + score)

                # Combine scores
                combined_score = (semantic_score * (1 - relevance_weight)) + (
                    relevance * relevance_weight
                )
                ranked_beliefs.append((belief, combined_score))

            # Sort by the new combined score, descending
            ranked_beliefs.sort(key=lambda x: x[1], reverse=True)

            # Return the top_k beliefs
            return [belief for belief, score in ranked_beliefs[:top_k]]

        except Exception as e:
            logger.error(
                f"Vector search for beliefs failed: {e}. Returning empty list."
            )
            return []

    def process_new_messages_for_update(self):
        """
        Fetches all new messages since the last update, processes them in
        conversation turns, and updates the user profile.
        """
        last_timestamp = self.storage.get_metadata(
            "profile_last_processed_timestamp"
        )
        # First, apply decay to all existing beliefs
        self._decay_belief_relevance()

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
            self.storage.set_metadata(
                "profile_last_processed_timestamp",
                new_messages[-1].get("timestamp"),
            )
            return

        logger.info(
            f"Processing {len(conversation_turns)} new conversation turns."
        )
        for user_msg, assistant_msg in conversation_turns:
            self._extract_and_assimilate_belief(user_msg, assistant_msg)

        # After processing all turns, update the timestamp to the last message processed
        latest_timestamp = new_messages[-1].get("timestamp")
        self.storage.set_metadata(
            "profile_last_processed_timestamp", latest_timestamp
        )
        logger.info(
            f"Profile update complete. New timestamp: {latest_timestamp}"
        )

    def _decay_belief_relevance(self, decay_factor: float = 0.95):
        """Applies a decay factor to the relevance of all beliefs."""
        logger.info(f"Applying relevance decay (factor: {decay_factor})...")
        try:
            with self.storage.conn:
                cursor = self.storage.conn.execute(
                    "UPDATE user_beliefs SET relevance = relevance * ?",
                    (decay_factor,),
                )
            if cursor.rowcount > 0:
                logger.info(
                    f"Decayed relevance for {cursor.rowcount} beliefs."
                )
        except Exception as e:
            logger.error(f"Failed to decay belief relevance: {e}")

    def _reinforce_belief(
        self, belief_id: str, increment: float = 1.0
    ) -> bool:
        """Finds a belief by ID and increases its relevance."""
        try:
            with self.storage.conn:
                cursor = self.storage.conn.execute(
                    "UPDATE user_beliefs SET relevance = relevance + ?,"
                    " last_updated = ? WHERE id = ?",
                    (
                        increment,
                        datetime.now(timezone.utc).isoformat(),
                        belief_id,
                    ),
                )
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to reinforce belief {belief_id}: {e}")
            return False

    def _create_new_belief(
        self, belief_data: Dict, user_message: Dict, assistant_message: Dict
    ):
        """Adds a new belief to the profile and vector store."""
        target_section = belief_data.get("target", "extended_beliefs")
        new_belief = belief_data.get("belief_data", {})
        topic = new_belief.get("topic", "general")
        belief_text = new_belief.get("belief")

        if not belief_text:
            logger.warning(
                "Attempted to create a belief with no text. Skipping."
            )
            return

        if target_section not in ["key_beliefs", "extended_beliefs"]:
            logger.warning(
                f"LLM returned invalid target section: '{target_section}'."
                " Defaulting to extended_beliefs."
            )
            target_section = "extended_beliefs"

        belief_id = str(uuid.uuid4())
        last_updated = datetime.now(timezone.utc).isoformat()
        source_ids = json.dumps(
            [
                uid
                for uid in [
                    user_message.get("id"),
                    assistant_message.get("id"),
                ]
                if uid
            ]
        )

        try:
            with self.storage.conn:
                self.storage.conn.execute(
                    """
                    INSERT INTO user_beliefs (id, belief_type, topic, belief, relevance, last_updated, source_message_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        belief_id,
                        target_section,
                        topic,
                        belief_text,
                        1.0,
                        last_updated,
                        source_ids,
                    ),
                )
            logger.info(
                f"Added new belief to '{target_section}' under topic: {topic}"
            )

            # Add to vector store if it's an extended belief
            if target_section == "extended_beliefs" and self.vector_storage:
                # We need the full belief object for metadata
                full_belief_obj = {
                    "id": belief_id,
                    "belief_type": target_section,
                    "topic": topic,
                    "belief": belief_text,
                    "relevance": 1.0,
                    "last_updated": last_updated,
                    "source_message_ids": json.loads(source_ids),
                }
                document_to_add = {
                    "page_content": belief_text,
                    "metadata": full_belief_obj,
                }
                self.vector_storage.add_documents([document_to_add])
                logger.info(
                    f"Indexed new belief (ID: {belief_id}) in vector store."
                )
        except Exception as e:
            logger.error(f"Failed to create new belief in database: {e}")

    def _extract_and_assimilate_belief(
        self, user_message: Dict, assistant_message: Dict
    ):
        """
        Extracts a potential belief from a conversation turn, compares it
        to existing beliefs, and decides whether to create a new belief,
        reinforce an existing one, or discard it.
        """
        decision_str = ""
        try:
            # Step 1: Search for semantically similar existing beliefs using the user's message
            similar_beliefs = []
            if self.vector_storage:
                search_results = self.vector_storage.search_with_scores(
                    user_message["content"], limit=5
                )

                # Defensive check: Ensure beliefs from vector store exist in our DB (source of truth)
                belief_ids_from_search = [
                    doc.get("metadata", {}).get("id")
                    for doc, score in search_results
                ]
                if belief_ids_from_search:
                    placeholders = ",".join(
                        "?" for _ in belief_ids_from_search
                    )
                    cursor = self.storage.conn.cursor()
                    cursor.execute(
                        "SELECT * FROM user_beliefs WHERE id IN"
                        f" ({placeholders})",
                        belief_ids_from_search,
                    )
                    verified_beliefs = [
                        self._dict_from_row(row) for row in cursor.fetchall()
                    ]
                    if len(verified_beliefs) != len(belief_ids_from_search):
                        logger.warning(
                            "Vector store returned beliefs that are not in the"
                            " database. The index might be stale. Stale"
                            " results have been filtered out."
                        )
                        self.storage.set_metadata(
                            "vector_db_needs_reset", "true"
                        )
                    similar_beliefs = verified_beliefs

            # Step 2: Single LLM call for consolidated processing
            conversation_snippet = (
                f"User: {user_message['content']}\n"
                f"Assistant: {assistant_message['content']}"
            )
            processing_prompt = self.template_manager.render(
                "framework.user_profile_manager.consolidated_belief_processing",
                {
                    "conversation_snippet": conversation_snippet,
                    "existing_beliefs": similar_beliefs,
                },
            )
            processing_history = [
                {
                    "role": "system",
                    "content": (
                        "You are an intelligent belief assimilation system."
                        " Your task is to analyze a conversation, compare it"
                        " against existing knowledge, and decide whether to"
                        " create new beliefs, reinforce existing ones, or"
                        " ignore the information. Respond in JSON format."
                    ),
                },
                {"role": "user", "content": processing_prompt},
            ]
            decision_str = self.llm.chat(
                chat_history=processing_history, stream=False
            )
            decision = json.loads(decision_str)

            # Step 3: Act on the decision
            action = decision.get("action")
            if action == "reinforce":
                belief_id = decision.get("belief_id")
                if self._reinforce_belief(belief_id):
                    logger.info(
                        f"Reinforced existing belief (ID: {belief_id}) with"
                        " relevance +1.0"
                    )
                else:
                    logger.warning(
                        f"LLM chose to reinforce a belief (ID: {belief_id})"
                        " that could not be found."
                    )

            elif action == "create":
                logger.info("Decision: Create a new belief.")
                candidate_data = decision
                self._create_new_belief(
                    candidate_data, user_message, assistant_message
                )

            elif action == "ignore":
                logger.info(
                    "Decision: Ignore candidate belief as it is redundant or"
                    " irrelevant."
                )
            else:
                logger.warning(
                    f"Unknown action '{action}' from assimilation model."
                    " Ignoring."
                )

        except json.JSONDecodeError:
            logger.warning(
                "LLM returned invalid JSON for belief processing:"
                f" {decision_str}"
            )
        except Exception as e:
            logger.error(f"Failed to assimilate belief from conversation: {e}")
