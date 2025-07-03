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

# Implementation of the "Generatively Reinforced Evolving Embeddings Network"
# (GREEN) Memories Algorithm

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ainara.framework.chat_memory import ChatMemory
from ainara.framework.config import config
from ainara.framework.llm.base import LLMBackend
from ainara.framework.storage import get_vector_backend
from ainara.framework.template_manager import TemplateManager
from ainara.framework.utils import load_spacy_model

logger = logging.getLogger(__name__)

# The minimum relevance score a memory must have to be retrieved for live conversation.
# This acts as a low-pass filter to prune irrelevant memories from active recall.
MIN_RELEVANCE_THRESHOLD = 0.2


class UserMemoriesManager:
    """Manages the user's semantic memories (beliefs, preferences, facts)."""

    def __init__(self, llm: LLMBackend, chat_memory: ChatMemory):
        self.llm = llm
        self.chat_memory = chat_memory
        self.storage = chat_memory.storage
        self.template_manager = TemplateManager()
        self.nlp = load_spacy_model()
        if not self.nlp:
            # spaCy is a critical dependency for substantive query analysis.
            raise RuntimeError(
                "Failed to load spaCy model, which is essential for UserMemoriesManager."
            )

        # This path is only needed for the one-time migration
        self.profile_path = os.path.join(
            config.get("data.directory"), "user_profile.json"
        )

        # Setup database table for memories
        self._create_memories_table()

        # Check if we need to force a full rescan of chat history
        self._check_and_force_rescan()

        # Run a one-time migration from the old JSON file if it exists
        self._run_migration()

        # Initialize vector storage for memories
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
                collection_name="user_profile_memories",
            )
            logger.info(
                f"Using {vector_type} vector backend for user profile memories"
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

    def _create_memories_table(self):
        """Creates the user_memories table in the database if it doesn't exist."""
        try:
            with self.storage.conn:
                self.storage.conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_memories (
                        id TEXT PRIMARY KEY,
                        memory_type TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        memory TEXT NOT NULL,
                        relevance REAL NOT NULL DEFAULT 1.0,
                        last_updated TEXT NOT NULL,
                        source_message_ids TEXT,
                        metadata TEXT
                    )
                    """
                )
                self.storage.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_topic ON"
                    " user_memories(topic);"
                )
                self.storage.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_type ON"
                    " user_memories(memory_type);"
                )
            logger.debug("user_memories table checked/created successfully.")
        except Exception as e:
            logger.error(f"Failed to create user_memories table: {e}")
            raise

    def _run_migration(self):
        """Migrates data from user_profile.json to the database if needed."""
        if not os.path.exists(self.profile_path):
            return  # No old file to migrate

        try:
            # Check if the memories table is empty
            cursor = self.storage.conn.cursor()
            cursor.execute("SELECT COUNT(id) FROM user_memories")
            if cursor.fetchone()[0] > 0:
                logger.info(
                    "memories table is not empty. Skipping migration from JSON."
                )
                return

            logger.info(
                "Found user_profile.json and empty memories table. Starting"
                " migration..."
            )
            with open(self.profile_path, "r", encoding="utf-8") as f:
                old_profile = json.load(f)

            memories_to_add = []
            for memory_type in ["key_memories", "extended_memories"]:
                for topic, topic_memories in old_profile.get(
                    memory_type, {}
                ).items():
                    for memory in topic_memories:
                        memories_to_add.append(
                            (
                                memory.get("id", str(uuid.uuid4())),
                                memory_type,
                                memory.get("topic", topic),
                                memory.get("memory"),
                                memory.get("relevance", 1.0),
                                memory.get(
                                    "last_updated",
                                    datetime.now(timezone.utc).isoformat(),
                                ),
                                json.dumps(memory.get("source_message_ids")),
                                json.dumps(memory.get("metadata")),
                            )
                        )

            if memories_to_add:
                with self.storage.conn:
                    self.storage.conn.executemany(
                        """
                        INSERT INTO user_memories (id, memory_type, topic, memory, relevance, last_updated, source_message_ids, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        memories_to_add,
                    )
                logger.info(
                    f"Successfully migrated {len(memories_to_add)} memories from"
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

    def _check_and_force_rescan(self):
        """
        Checks if the memories table is empty but a processing timestamp
        exists. This indicates a manual reset, so we clear the timestamp
        to force a full rescan of chat history.
        """
        try:
            # The table is guaranteed to exist at this point because
            # _create_memories_table() has been called.
            is_empty = self.is_empty()
            last_timestamp = self.storage.get_metadata(
                "profile_last_processed_timestamp"
            )

            if is_empty and last_timestamp:
                logger.warning(
                    "The 'user_memories' table is empty, but a last processed"
                    " timestamp was found. This indicates a manual reset."
                    " Forcing a full rescan of chat history."
                )
                # Instead of setting to None which violates the NOT NULL constraint,
                # we delete the metadata key directly.
                with self.storage.conn:
                    self.storage.conn.execute(
                        "DELETE FROM db_metadata WHERE key = ?",
                        ("profile_last_processed_timestamp",),
                    )
                # Also flag the vector DB for a reset since it will be out of sync.
                self.storage.set_metadata("vector_db_needs_reset", "true")
        except Exception as e:
            # If this check fails, it's safer to do nothing and log the error.
            logger.error(f"Failed to check for forced rescan condition: {e}")

    def _dict_from_row(self, row: Any) -> Dict:
        """Converts a sqlite3.Row to a dictionary and parses JSON fields."""
        if not row:
            return {}
        memory = dict(row)
        for key in ["source_message_ids", "metadata"]:
            if memory.get(key) and isinstance(memory[key], str):
                try:
                    memory[key] = json.loads(memory[key])
                except json.JSONDecodeError:
                    logger.warning(
                        f"Could not decode JSON for key '{key}' in memory ID"
                        f" {memory.get('id')}"
                    )
                    memory[key] = None
        return memory

    def _sync_profile_to_vector_store(self):
        import time

        """Clears and rebuilds the memory vector index from the profile."""
        if not self.vector_storage:
            logger.debug(
                "Vector storage not available, skipping profile sync."
            )
            return

        start_time = time.time()
        logger.info("Syncing user profile memories to vector store...")
        self.vector_storage.reset()  # Clear the collection

        cursor = self.storage.conn.cursor()
        cursor.execute(
            "SELECT * FROM user_memories"
        )
        all_memories = [self._dict_from_row(row) for row in cursor.fetchall()]

        if not all_memories:
            logger.info("No memories found in profile to index.")
            return

        documents_to_add = []
        for memory in all_memories:
            content = memory.get("memory", "")
            if not content:
                continue
            metadata = memory.copy()
            documents_to_add.append(
                {"page_content": content, "metadata": metadata}
            )

        if documents_to_add:
            self.vector_storage.add_documents(documents_to_add)
            duration = time.time() - start_time
            logger.info(
                f"Successfully indexed {len(documents_to_add)}"
                " memories in vector store. Operation took"
                f" {duration:.2f} seconds."
            )

        # After a successful sync, clear the flag
        self.storage.set_metadata("vector_db_needs_reset", "false")
        logger.info("Vector DB sync complete. Cleared reset flag.")

    def _is_query_substantive(self, query: str) -> bool:
        """
        Uses spaCy to determine if a query is substantive enough for semantic search.
        A query is substantive if it contains at least one token that is not a
        stopword, punctuation, or space.
        """
        doc = self.nlp(query)
        for token in doc:
            if not token.is_stop and not token.is_punct and not token.is_space:
                return True
        # If no such token was found, the query is not substantive
        return False

    def get_key_memories(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Returns a flat list of key memories from the database, optionally limited.
        Key memories are sorted by relevance in descending order.
        """
        query = (
            "SELECT * FROM user_memories WHERE memory_type = 'key_memories' AND relevance >= ?"
            " ORDER BY relevance DESC"
        )
        params = (MIN_RELEVANCE_THRESHOLD,)

        if limit is not None:
            query += " LIMIT ?"
            params += (limit,)

        cursor = self.storage.conn.cursor()
        cursor.execute(query, params)
        return [self._dict_from_row(row) for row in cursor.fetchall()]

    def is_empty(self) -> bool:
        """Checks if the user profile contains any memories."""
        try:
            cursor = self.storage.conn.cursor()
            # We just need to know if at least one row exists.
            cursor.execute("SELECT 1 FROM user_memories LIMIT 1")
            return cursor.fetchone() is None
        except Exception as e:
            logger.error(f"Failed to check if profile is empty: {e}")
            return False  # Safer to assume not empty on error

    def get_relevant_memories(
        self,
        query: str,
        top_k: int = 3,
        relevance_weight: float = 0.3,
        exclude_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Finds memories relevant to the user's query using semantic vector
        search, re-ranking results based on the memory's relevance score.
        """
        if not self.vector_storage:
            raise RuntimeError(
                "Vector storage is required for memory retrieval."
            )

        # Guard clause: Don't search for non-substantive queries.
        if not self._is_query_substantive(query):
            logger.info("Skipping memory retrieval for non-substantive query.")
            return []

        try:
            # Fetch more results initially to allow for re-ranking
            initial_results_count = top_k * 3
            logger.info(
                "Performing semantic search for extended memories with"
                f" query: '{query}'"
            )
            # Build the filter dynamically.
            # This now searches both key_memories and extended_memories.
            filter_dict = {"relevance": {"$gte": MIN_RELEVANCE_THRESHOLD}}

            # Exclude IDs of memories that are already in the context.
            if exclude_ids:
                filter_dict["id"] = {"$nin": exclude_ids}

            results_with_distances = self.vector_storage.search_with_scores(
                query,
                limit=initial_results_count,
                filter_dict=filter_dict,
            )

            if not results_with_distances:
                return []

            ranked_memories = []
            for doc, score in results_with_distances:
                memory = doc.get("metadata", {})
                relevance = memory.get("relevance", 1.0)
                # Normalize semantic score (distance) to be higher-is-better
                # Assuming distance is between 0 and ~2. A simple inversion works.
                semantic_score = 1 / (1 + score)

                # Combine scores
                combined_score = (semantic_score * (1 - relevance_weight)) + (
                    relevance * relevance_weight
                )
                ranked_memories.append((memory, combined_score))

            # Sort by the new combined score, descending
            ranked_memories.sort(key=lambda x: x[1], reverse=True)

            # Return the top_k memories
            return [memory for memory, score in ranked_memories[:top_k]]

        except Exception as e:
            logger.error(
                f"Vector search for memories failed: {e}. Returning empty list."
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
        # First, apply decay to all existing memories
        self._decay_memory_relevance()

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
            self._extract_and_assimilate_memory(user_msg, assistant_msg)

        # After processing all turns, update the timestamp to the last message processed
        latest_timestamp = new_messages[-1].get("timestamp")
        self.storage.set_metadata(
            "profile_last_processed_timestamp", latest_timestamp
        )
        logger.info(
            f"Profile update complete. New timestamp: {latest_timestamp}"
        )

    def _decay_memory_relevance(self, decay_factor: float = 0.995):
        """Applies a decay factor to the relevance of all memories."""
        logger.info(f"Applying relevance decay (factor: {decay_factor})...")
        try:
            with self.storage.conn:
                cursor = self.storage.conn.execute(
                    "UPDATE user_memories SET relevance = relevance * ?",
                    (decay_factor,),
                )
            if cursor.rowcount > 0:
                logger.info(
                    f"Decayed relevance for {cursor.rowcount} memories."
                )
        except Exception as e:
            logger.error(f"Failed to decay memory relevance: {e}")

    def _reinforce_memory(
        self, memory_id: str, increment: float = 1.0
    ) -> bool:
        """Finds a memory by ID and increases its relevance."""
        try:
            with self.storage.conn:
                cursor = self.storage.conn.execute(
                    "UPDATE user_memories SET relevance = relevance + ?,"
                    " last_updated = ? WHERE id = ?",
                    (
                        increment,
                        datetime.now(timezone.utc).isoformat(),
                        memory_id,
                    ),
                )
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to reinforce memory {memory_id}: {e}")
            return False

    def _create_new_memory(
        self, memory_data: Dict, user_message: Dict, assistant_message: Dict
    ):
        """Adds a new memory to the profile and vector store."""
        target_section = memory_data.get("target", "extended_memories")
        new_memory = memory_data.get("memory_data", {})
        topic = new_memory.get("topic", "general")
        memory_text = new_memory.get("memory")

        if not memory_text:
            logger.warning(
                "Attempted to create a memory with no text. Skipping."
            )
            return

        if target_section not in ["key_memories", "extended_memories"]:
            logger.warning(
                f"LLM returned invalid target section: '{target_section}'."
                " Defaulting to extended_memories."
            )
            target_section = "extended_memories"

        memory_id = str(uuid.uuid4())
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
                    INSERT INTO user_memories (id, memory_type, topic, memory, relevance, last_updated, source_message_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        target_section,
                        topic,
                        memory_text,
                        1.0,
                        last_updated,
                        source_ids,
                    ),
                )
            logger.info(
                f"Added new memory to '{target_section}' under topic: {topic}"
            )

            # Add to vector store regardless of type for de-duplication
            if self.vector_storage:
                # We need the full memory object for metadata
                full_memory_obj = {
                    "id": memory_id,
                    "memory_type": target_section,
                    "topic": topic,
                    "memory": memory_text,
                    "relevance": 1.0,
                    "last_updated": last_updated,
                    "source_message_ids": json.loads(source_ids),
                }
                document_to_add = {
                    "page_content": memory_text,
                    "metadata": full_memory_obj,
                }
                self.vector_storage.add_documents([document_to_add])
                logger.info(
                    f"Indexed new memory (ID: {memory_id}) in vector store."
                )
        except Exception as e:
            logger.error(f"Failed to create new memory in database: {e}")

    def _extract_and_assimilate_memory(
        self, user_message: Dict, assistant_message: Dict
    ):
        """
        Extracts a potential memory from a conversation turn. If a candidate
        memory is extracted, it is checked against existing memories for
        duplicates before being created or used to reinforce an existing memory.
        """
        # A high threshold to ensure we only reinforce true duplicates.
        candidate_str = ""

        # Define different thresholds for different memory types.
        # Key memories are foundational, so we use a more lenient threshold to encourage consolidation.
        # Extended memories are more specific, so we use a stricter threshold.
        KEY_MEMORY_SIMILARITY_THRESHOLD = 0.85
        EXTENDED_MEMORY_SIMILARITY_THRESHOLD = 0.95

        try:
            # Step 1: Use the LLM to extract a potential memory candidate.
            conversation_snippet = (
                f"User: {user_message['content']}\n"
                f"Assistant: {assistant_message['content']}"
            )
            extraction_prompt = self.template_manager.render(
                "framework.user_memories_manager.extract_memory_candidate",
                {"conversation_snippet": conversation_snippet},
            )
            system_prompt = self.template_manager.render(
                "framework.user_memories_manager.extract_memory_candidate_system"
            )
            processing_history = [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": extraction_prompt},
            ]
            candidate_str = self.llm.chat(
                chat_history=processing_history, stream=False
            )
            candidate_memory = json.loads(candidate_str)

            # Step 2: Validate the candidate memory.
            if not candidate_memory or "memory" not in candidate_memory:
                logger.info(
                    "LLM extracted no new memory from the conversation."
                )
                return

            candidate_text = candidate_memory["memory"]
            candidate_type = candidate_memory.get(
                "memory_type", "extended_memories"
            )
            logger.info(
                f"LLM proposed a new {candidate_type} candidate: {candidate_text}"
            )

            # Step 3: Check for duplicates before creating.
            if self.vector_storage:
                similarity_threshold = (
                    KEY_MEMORY_SIMILARITY_THRESHOLD
                    if candidate_type == "key_memories"
                    else EXTENDED_MEMORY_SIMILARITY_THRESHOLD
                )
                # Search for memories semantically similar to the *candidate* memory.
                search_results = self.vector_storage.search_with_scores(
                    candidate_text, limit=1
                )

                if search_results:
                    # The score is distance, so lower is more similar.
                    # We convert it to a 0-1 similarity score.
                    most_similar_doc, distance = search_results[0]
                    similarity_score = 1 / (1 + distance)

                    if similarity_score > similarity_threshold:
                        existing_memory_id = most_similar_doc.get(
                            "metadata", {}
                        ).get("id")
                        if existing_memory_id:
                            logger.info(
                                f"Candidate is a duplicate of memory"
                                f" {existing_memory_id} (Threshold:"
                                f" {similarity_threshold}, Similarity:"
                                f" {similarity_score:.2f}). Reinforcing."
                            )
                            self._reinforce_memory(existing_memory_id)
                            return  # Stop processing

            # Step 4: If it's not a duplicate, create the new memory.
            logger.info(
                "Candidate is not a duplicate. Creating a new memory."
            )
            # The LLM now proposes the memory type. We read it and pass it on.
            memory_data_for_creation = {
                "target": candidate_type,
                "memory_data": candidate_memory,
            }
            self._create_new_memory(
                memory_data_for_creation, user_message, assistant_message
            )

        except json.JSONDecodeError:
            logger.warning(
                "LLM returned invalid JSON for memory extraction:"
                f" {candidate_str}"
            )
        except Exception as e:
            logger.error(f"Failed to assimilate memory from conversation: {e}")
