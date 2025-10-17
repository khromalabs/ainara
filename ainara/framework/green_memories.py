# Ainara  AI Companion Framework Project
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
import math
# import re
import uuid
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.util import cos_sim

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

from spacy.lang.en.stop_words import STOP_WORDS as SPACY_STOP_WORDS

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

# Define a set of stopwords for normalization.
# We use spaCy's list and can extend it if needed.
STOPWORDS = set(SPACY_STOP_WORDS)


class GREENMemories:
    """Manages the user's semantic memories (beliefs, preferences, facts)."""

    def __init__(
        self,
        llm: LLMBackend,
        chat_memory: ChatMemory,
    ):
        self.llm = llm
        self.chat_memory = chat_memory
        self.storage = chat_memory.storage
        self.template_manager = TemplateManager()
        self.context_window = llm.get_context_window() or 4096  # default 4k
        self.scoring_config = {
            # A multiplier to boost the importance of key_memories during ranking.
            "key_memory_boost": 1.5,
            # The weight given to a memory's intrinsic relevance score versus its
            # semantic similarity to the query. 0.3 means 30% relevance, 70% semantic.
            "relevance_weight": 0.3,
            # The penalty applied to memories marked as 'past' to de-prioritize them.
            "past_memory_penalty": 0.5,
            # The maximum boost applied to a memory that was just updated.
            "max_recency_boost": 1.5,
            # Controls how quickly the recency boost fades over time (in hours).
            # A smaller value means the boost lasts longer.
            "recency_decay_rate": 0.01,
        }
        self.nlp = load_spacy_model()
        self._db_lock = threading.Lock()
        self.extraction_context_turns = config.get(
            "user_profile.green_memories.extraction_context_turns", 2
        )
        if not self.nlp:
            # spaCy is a critical dependency for substantive query analysis.
            raise RuntimeError(
                "Failed to load spaCy model, which is essential for"
                " GREENMemories."
            )

        # This path is only needed for the one-time migration
        self.profile_path = os.path.join(
            config.get("data.directory"), "user_profile.json"
        )

        # Setup database / load key memories
        self._create_memories_table()
        self._update_schema()
        self.all_key_memories = self.get_key_memories()
        # Cache all topics on initialization to avoid repeated DB queries
        self.all_topics = self.get_all_topics()
        logger.info(f"Cached {len(self.all_topics)} unique memory topics.")

        # Check if we need to force a full rescan of chat history
        self._check_and_force_rescan()

        # # Run a one-time migration from the old JSON file if it exists
        # self._run_migration()

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

        # Topic matching model for memory boosting
        self.topic_matcher_model = None
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.topic_matcher_model = SentenceTransformer(
                    embedding_model,
                    cache_folder=config.get("cache.directory")
                )
                logger.info(f"Loaded topic matcher model: {embedding_model}")
            except Exception as e:
                logger.error(f"Failed to load topic matcher model: {e}")
        elif not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning(
                "sentence_transformers library not found. Topic-based memory "
                "boosting will be disabled. Please run 'pip install "
                "sentence-transformers'."
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
            # Sync profile to vector store on startup if needed.
            # First, check the explicit flag.
            needs_reset = self.storage.get_metadata("vector_db_needs_reset")

            # Second, check for count mismatch to detect manual deletion or corruption.
            # This assumes a `count()` method is added to the vector storage backend.
            with self.storage.conn:
                sqlite_count = self.storage.conn.execute(
                    "SELECT COUNT(id) FROM user_memories"
                ).fetchone()[0]
            vector_count = self.vector_storage.count()

            if needs_reset == "true" or sqlite_count != vector_count:
                if needs_reset == "true":
                    logger.info(
                        "Vector DB needs reset due to explicit flag. Starting"
                        " full sync..."
                    )
                else:
                    logger.warning(
                        "Mismatch detected between SQLite"
                        f" ({sqlite_count} memories) and Vector DB"
                        f" ({vector_count} memories). This can happen after a"
                        " manual deletion. Triggering re-sync."
                    )
                self._sync_profile_to_vector_store()
            else:
                logger.info(
                    "Vector DB is consistent with SQLite"
                    f" ({sqlite_count} memories). Skipping startup sync."
                )
        except ImportError as e:
            import traceback

            logger.warning(
                f"Vector storage backend '{vector_type}' dependencies not"
                " found. User profile search will fall back to keyword"
                " matching."
            )
            logger.error(f"ImportError details: {e}")
            logger.error(traceback.format_exc())
            self.vector_storage = None
        except Exception as e:
            logger.error(
                f"Failed to initialize vector storage for profile: {e}"
            )
            self.vector_storage = None

    def update_llm(self, llm):
        self.llm = llm
        self.context_window = llm.get_context_window() or 4096  # default 4k

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
                        metadata TEXT,
                        status TEXT NOT NULL DEFAULT 'current'
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

    # def _run_migration(self):
    #     """Migrates data from user_profile.json to the database if needed."""
    #     if not os.path.exists(self.profile_path):
    #         return  # No old file to migrate
    #
    #     try:
    #         # Check if the memories table is empty
    #         cursor = self.storage.conn.cursor()
    #         cursor.execute("SELECT COUNT(id) FROM user_memories")
    #         if cursor.fetchone()[0] > 0:
    #             logger.info(
    #                 "memories table is not empty. Skipping migration from"
    #                 " JSON."
    #             )
    #             return
    #
    #         logger.info(
    #             "Found user_profile.json and empty memories table. Starting"
    #             " migration..."
    #         )
    #         with open(self.profile_path, "r", encoding="utf-8") as f:
    #             old_profile = json.load(f)
    #
    #         memories_to_add = []
    #         for memory_type in ["key_memories", "extended_memories"]:
    #             for topic, topic_memories in old_profile.get(
    #                 memory_type, {}
    #             ).items():
    #                 for memory in topic_memories:
    #                     memories_to_add.append(
    #                         (
    #                             memory.get("id", str(uuid.uuid4())),
    #                             memory_type,
    #                             memory.get("topic", topic),
    #                             memory.get("memory"),
    #                             memory.get("relevance", 1.0),
    #                             memory.get(
    #                                 "last_updated",
    #                                 datetime.now(timezone.utc).isoformat(),
    #                             ),
    #                             json.dumps(memory.get("source_message_ids")),
    #                             json.dumps(memory.get("metadata")),
    #                         )
    #                     )
    #
    #         if memories_to_add:
    #             with self.storage.conn:
    #                 self.storage.conn.executemany(
    #                     """
    #                     INSERT INTO user_memories (id, memory_type, topic, memory, relevance, last_updated, source_message_ids, metadata)
    #                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    #                     """,
    #                     memories_to_add,
    #                 )
    #             logger.info(
    #                 f"Successfully migrated {len(memories_to_add)} memories"
    #                 " from JSON to SQLite."
    #             )
    #
    #         # Rename the old file to prevent re-migration
    #         os.rename(self.profile_path, f"{self.profile_path}.migrated")
    #         logger.info(f"Renamed {self.profile_path} to avoid re-migration.")
    #         self.storage.set_metadata("vector_db_needs_reset", "true")
    #         logger.info(
    #             "Flagged vector DB for reset on next startup due to migration."
    #         )
    #
    #     except Exception as e:
    #         logger.error(f"Error during profile migration from JSON: {e}")

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

    def _update_schema(self):
        """Adds new columns to the user_memories table if they don't exist."""
        try:
            with self.storage.conn:
                # # !!!! Force reset !!!
                # self.storage.set_metadata("vector_db_needs_reset", "true")
                # logger.info(
                #     "Flagged vector DB for reset on next startup due to schema"
                #     " change."
                # )
                # # !!!!!!!!!!!!!!!!!!!
                cursor = self.storage.conn.cursor()
                cursor.execute("PRAGMA table_info(user_memories)")
                columns = [row[1] for row in cursor.fetchall()]

                if "status" not in columns:
                    logger.info(
                        "Adding 'status' column to user_memories table."
                    )
                    cursor.execute(
                        "ALTER TABLE user_memories ADD COLUMN status TEXT NOT"
                        " NULL DEFAULT 'current'"
                    )
                    self.storage.set_metadata("vector_db_needs_reset", "true")
                    logger.info(
                        "Flagged vector DB for reset on next startup due to"
                        " schema change."
                    )
                    logger.info("Schema update complete.")

                if "created_at" not in columns:
                    logger.info(
                        "Adding 'created_at' column to user_memories table."
                    )
                    # Add the column, allowing NULLs for now
                    cursor.execute(
                        "ALTER TABLE user_memories ADD COLUMN created_at TEXT"
                    )
                    # Populate with last_updated for existing records
                    cursor.execute(
                        "UPDATE user_memories SET created_at = last_updated"
                        " WHERE created_at IS NULL"
                    )
                    logger.info(
                        "Populated 'created_at' for existing memories."
                    )
                    # While we could add a NOT NULL constraint, it's complex in SQLite.
                    # The application logic will ensure it's always populated for new rows.
                    self.storage.set_metadata("vector_db_needs_reset", "true")
                    logger.info(
                        "Flagged vector DB for reset on next startup due to"
                        " schema change."
                    )
                    logger.info("Schema update complete.")

                # This is now safe to run in all cases, as the column is guaranteed to exist.
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_status ON"
                    " user_memories(status);"
                )
        except Exception as e:
            logger.error(f"Failed to update user_memories schema: {e}")

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
        cursor.execute("SELECT * FROM user_memories")
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
            normalized_content = self._normalize_memory_text(content)
            documents_to_add.append(
                {"page_content": normalized_content, "metadata": metadata}
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
        A query is substantive if it contains at least one token that is a noun,
        proper noun, verb, or adjective. This helps filter out simple greetings
        or conversational filler.
        """
        # The query can be a multi-line context string. We only care about the last line.
        last_line = query.strip().split("\n")[-1]
        # Strip any "role: " prefix (e.g., "user: ") from the last line.
        actual_query = last_line.split(":", 1)[-1].strip()

        doc = self.nlp(actual_query)
        logger.info(
            f"Substantive check on query: '{actual_query}' (from last line:"
            f" '{last_line}')"
        )

        # Define parts of speech that we consider substantive for a query.
        substantive_pos = {"NOUN", "PROPN", "VERB", "ADJ"}
        for token in doc:
            logger.debug(f"  - Token: '{token.text}', POS: {token.pos_}")
            if token.pos_ in substantive_pos:
                logger.info(
                    f"Found substantive token '{token.text}' ({token.pos_})."
                    " Returning True."
                )
                return True
        # If no such token was found, the query is not substantive.
        logger.info("No substantive tokens found. Returning False.")
        return False

    def generate_user_profile_summary(
        self, top_k: Optional[int] = None
    ) -> Optional[str]:
        """
        Generates a narrative summary of the user's profile using the LLM.

        This method fetches the most relevant key memories and asks the LLM to
        synthesize them into a coherent paragraph, prioritizing information
        based on relevance scores to resolve conflicts.

        Args:
            top_k: The number of top key memories to use for the summary.

        Returns:
            A string containing the narrative user profile, or None if no
            memories exist.
        """
        if top_k is None:
            # Dynamically set top_k for profile summary based on context window
            if self.context_window <= 8192:
                top_k = 25
            elif self.context_window <= 32768:
                top_k = 50
            else:
                top_k = 75
            logger.info(
                f"Context window is {self.context_window}, dynamically setting"
                f" top_k for profile summary to {top_k}"
            )
        logger.info(
            f"Generating narrative user profile from top {top_k} key"
            " memories..."
        )
        key_memories = self.get_key_memories(limit=top_k)

        if not key_memories:
            logger.info("No key memories found to generate a profile summary.")
            return None

        # Prepare the memories for the prompt, including relevance scores
        formatted_memories = [
            f"- {mem['memory']} (Relevance: {mem['relevance']:.2f})"
            for mem in key_memories
        ]
        memories_text = "\n".join(formatted_memories)

        user_prompt = self.template_manager.render(
            "framework.green_memories.generate_user_profile",
            {"memories_text": memories_text},
        )

        try:
            profile_summary = self.llm.chat(
                chat_history=[{"role": "user", "content": user_prompt}],
                stream=False,
            )
            logger.info(
                f"Generated user profile summary: {profile_summary[:150]}..."
            )
        except Exception:
            profile_summary = "User profile couldn't be generated"
            logger.error(profile_summary)

        return profile_summary

    def generate_recent_memories_summary(
        self, top_k: Optional[int] = None
    ) -> Optional[str]:
        """
        Generates a narrative summary of the most recently discussed topics.

        This method fetches the most recently updated memories and asks the LLM to
        synthesize them into a coherent paragraph.

        Args:
            top_k: The number of top recent memories to use for the summary.

        Returns:
            A string containing the narrative of recent memories, or None if no
            memories exist.
        """
        if top_k is None:
            # Dynamically set top_k for profile summary based on context window
            if self.context_window <= 8192:
                top_k = 25
            elif self.context_window <= 32768:
                top_k = 50
            else:
                top_k = 75
            logger.info(
                f"Context window is {self.context_window}, dynamically setting"
                f" top_k for recent memories summary to {top_k}"
            )
        logger.info(
            f"Generating narrative of recent memories from top {top_k} most"
            " recent memories..."
        )

        # Fetch recent memories
        query = (
            "SELECT * FROM user_memories WHERE status = 'current' ORDER BY"
            " last_updated DESC"
        )
        params = ()

        if top_k is not None:
            query += " LIMIT ?"
            params += (top_k,)

        cursor = self.storage.conn.cursor()
        cursor.execute(query, params)
        recent_memories = [self._dict_from_row(row) for row in cursor.fetchall()]

        if not recent_memories:
            logger.info("No recent memories found to generate a summary.")
            return None

        # Prepare the memories for the prompt
        formatted_memories = [f"- {mem['memory']}" for mem in recent_memories]
        memories_text = "\n".join(formatted_memories)

        user_prompt = self.template_manager.render(
            "framework.green_memories.generate_recent_memories",
            {"memories_text": memories_text},
        )

        try:
            recent_summary = self.llm.chat(
                chat_history=[{"role": "user", "content": user_prompt}],
                stream=False,
            )
            logger.info(
                f"Generated recent memories summary: {recent_summary[:150]}..."
            )
        except Exception:
            recent_summary = "Recent memories summary couldn't be generated"
            logger.error(recent_summary)

        return recent_summary

    def get_key_memories(
        self,
        limit: Optional[int] = None,
        low_pass_filter: Optional[bool] = True,
    ) -> List[Dict]:
        """
        Returns a flat list of key memories from the database, optionally limited.
        Key memories are sorted by relevance in descending order.
        """
        query = (
            "SELECT * FROM user_memories WHERE memory_type = 'key_memories'"
            " AND status = 'current' AND relevance >= ? ORDER BY relevance"
            " DESC"
        )
        if low_pass_filter:
            params = (MIN_RELEVANCE_THRESHOLD,)
        else:
            params = ()

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

    def get_all_topics(self) -> List[str]:
        """Retrieves a unique list of all topics from the user_memories table."""
        try:
            with self.storage.conn:
                cursor = self.storage.conn.cursor()
                cursor.execute(
                    "SELECT DISTINCT topic FROM user_memories WHERE status ="
                    " 'current'"
                )
                topics = [row[0] for row in cursor.fetchall()]
                return topics
        except Exception as e:
            logger.error(f"Failed to retrieve memory topics: {e}")
            return []

    def get_relevant_topics_for_context(
        self, context: str, threshold: float = 0.3
    ) -> List[str]:
        """
        Identifies relevant memory topics for a given conversation context using
        semantic similarity.
        """
        if not self.topic_matcher_model:
            return []

        all_topics = self.all_topics
        if not all_topics:
            return []

        logger.info("Checking relevant topics...")

        try:
            context_embedding = self.topic_matcher_model.encode(
                context, convert_to_tensor=True
            )
            topic_embeddings = self.topic_matcher_model.encode(
                all_topics, convert_to_tensor=True
            )

            similarities = cos_sim(context_embedding, topic_embeddings)

            relevant_indices = (
                (similarities[0] > threshold)
                .nonzero(as_tuple=True)[0]
                .tolist()
            )
            relevant_topics = [all_topics[i] for i in relevant_indices]

            return relevant_topics
        except Exception as e:
            logger.error(
                f"Failed to determine relevant topics via embeddings: {e}"
            )
            return []

    def _normalize_memory_text(self, text: str) -> str:
        """Cleans and normalizes memory text using spaCy for better duplicate detection."""
        text = text.lower()  # Lowercase first
        doc = self.nlp(text)
        normalized_tokens = []
        for token in doc:
            if (
                not token.is_stop
                and not token.is_punct
                and token.text.lower() not in STOPWORDS
            ):
                normalized_tokens.append(token.lemma_)  # Use lemma (base form)
        normalized_text = " ".join(normalized_tokens).strip()
        return (
            normalized_text if normalized_text else text
        )  # Fallback to original if empty

    def get_relevant_memories(
        self,
        query: str,
        top_k: Optional[int] = None,
        exclude_ids: Optional[List[str]] = None,
        topic_boost: bool = True,
    ) -> List[Dict]:
        """
        Finds memories relevant to the user's query using a hybrid approach.
        It combines the most important 'key memories' (reflex) with memories
        found via semantic search (contextual).
        """
        relevant_topics = []
        if topic_boost:
            relevant_topics = self.get_relevant_topics_for_context(query)
            if relevant_topics:
                logger.info(
                    "Identified relevant topics via semantic search:"
                    f" {relevant_topics}"
                )
        if not self.vector_storage:
            raise RuntimeError(
                "Vector storage is required for memory retrieval."
            )

        if not self._is_query_substantive(query):
            logger.info(
                "Query is not substantive, skipping contextual memory"
                " retrieval."
            )
            return []

        if top_k is None:
            # Dynamically determine top_k for memories based on context window
            if self.context_window <= 8192:
                top_k = 5
            elif self.context_window <= 32768:
                top_k = 10
            else:
                top_k = 20  # More for very large contexts
            logger.info(
                f"Context window is {self.context_window}, dynamically setting"
                f" top_k for memories to {top_k}"
            )

        try:
            # Fetch more results initially to allow for re-ranking
            initial_results_count = top_k * 3
            logger.info(
                f"Performing semantic search to find the best {top_k}"
                f" contextual memories (fetching {initial_results_count}"
                f" candidates) with query: '{query}'"
            )

            # Build the filter dynamically to support multiple conditions.
            filter_conditions = []

            # Exclude IDs from reflex memories and any initially passed IDs.
            if exclude_ids is not None and exclude_ids:
                filter_conditions.append({"id": {"$nin": exclude_ids}})

            # ChromaDB requires a logical operator ($and, $or) for multiple filters.
            if len(filter_conditions) > 1:
                filter_dict = {"$and": filter_conditions}
            elif filter_conditions:
                filter_dict = filter_conditions[0]
            else:
                filter_dict = None

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
                memory_type = memory.get("memory_type")
                memory_status = memory.get("status", "current")
                relevance = memory.get("relevance", 1.0)
                memory_topic = memory.get("topic")
                last_updated_str = memory.get("last_updated")

                if memory_type == "key_memories":
                    relevance *= self.scoring_config["key_memory_boost"]

                # Boost relevance if the memory's topic is currently active
                if relevant_topics and memory_topic in relevant_topics:
                    relevance *= self.scoring_config["key_memory_boost"]
                    logger.debug(
                        f"Boosting memory {memory.get('id')} due to relevant"
                        f" topic: {memory_topic}"
                    )

                # For normalized vectors, cosine similarity can be calculated from
                # squared L2 distance using: 1 - (distance / 2)
                semantic_score = 1 - (score / 2)

                base_score = (
                    semantic_score * (1 - self.scoring_config["relevance_weight"])
                ) + (relevance * self.scoring_config["relevance_weight"])

                # Calculate and apply recency boost
                recency_boost = 1.0
                if last_updated_str:
                    try:
                        last_updated_dt = datetime.fromisoformat(
                            last_updated_str
                        )
                        time_delta = datetime.now(
                            timezone.utc
                        ) - last_updated_dt
                        hours_since_update = time_delta.total_seconds() / 3600
                        recency_boost = 1 + (
                            self.scoring_config["max_recency_boost"] - 1
                        ) * math.exp(
                            -self.scoring_config["recency_decay_rate"]
                            * hours_since_update
                        )
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Could not parse last_updated timestamp: {last_updated_str}"
                        )

                combined_score = base_score * recency_boost

                # Demote past memories in ranking so current ones are preferred.
                if memory_status == "past":
                    combined_score *= self.scoring_config[
                        "past_memory_penalty"
                    ]  # Apply a penalty

                ranked_memories.append((memory, combined_score))

            ranked_memories.sort(key=lambda x: x[1], reverse=True)

            semantic_memories = [
                memory for memory, score in ranked_memories[:top_k]
            ]

            # Prefix past memories that make it into the top results for clarity.
            for memory in semantic_memories:
                if memory.get("status") == "past":
                    memory["memory"] = (
                        "PAST MEMORY DON'T CONSIDER THIS A CURRENT EVENT:"
                        f" \"{memory['memory']}\""
                    )

                # Format dates for display
                for key in ["created_at", "last_updated"]:
                    if memory.get(key):
                        try:
                            dt_obj = datetime.fromisoformat(memory[key])
                            memory[f"{key}_formatted"] = dt_obj.strftime(
                                "%Y-%m-%d %H:%M"
                            )
                        except (ValueError, TypeError):
                            logger.warning(
                                "Could not parse date string for"
                                f" {key}: {memory[key]}"
                            )
                            memory[f"{key}_formatted"] = None

            return semantic_memories

        except Exception as e:
            logger.error(
                f"Vector search for memories failed: {e}. Returning empty"
                " list."
            )
            return []

    def get_turn_counter(self) -> int:
        """Retrieves the persisted turn counter for memory decay."""
        with self._db_lock:
            value = self.storage.get_metadata("profile_decay_turn_counter")
        if value:
            logger.info(f"Loaded persisted turn counter: {value}")
            return int(value)
        return 0

    def save_turn_counter(self, count: int):
        """Saves the turn counter for memory decay."""
        with self._db_lock:
            self.storage.set_metadata("profile_decay_turn_counter", str(count))

    def reset_turn_counter(self):
        """Resets the persisted turn counter to 0."""
        with self._db_lock:
            self.storage.set_metadata("profile_decay_turn_counter", "0")

    def process_new_messages_for_update(
            self, progress_callback=None, max_progress=100):
        """
        Fetches all new messages since the last update, processes them in
        conversation turns, and updates the user profile.
        """
        last_timestamp = self.storage.get_metadata(
            "profile_last_processed_timestamp"
        )
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
        total_turns = len(conversation_turns)
        newly_created_or_updated_memories_in_batch = []
        for i, (user_msg, assistant_msg) in enumerate(conversation_turns):
            # Move timestamp forward BEFORE processing to avoid getting stuck.
            # If processing fails, this message will be skipped on the next run.
            current_timestamp = assistant_msg.get("timestamp")
            if current_timestamp:
                self.storage.set_metadata(
                    "profile_last_processed_timestamp", current_timestamp
                )

            try:
                # Create a sliding window of context. A value of 0 means no extra context.
                start_index = max(0, i - self.extraction_context_turns)
                context_turns = conversation_turns[start_index: i + 1]

                # The last turn in the window is the one we are primarily analyzing.
                # The preceding turns provide the context.
                processed_memory = self._extract_and_assimilate_memory(
                    context_turns, newly_created_or_updated_memories_in_batch
                )

                if processed_memory:
                    # If a memory was created or updated, update our batch context list
                    existing_index = next(
                        (
                            idx
                            for idx, mem in enumerate(
                                newly_created_or_updated_memories_in_batch
                            )
                            if mem["id"] == processed_memory["id"]
                        ),
                        -1,
                    )
                    if existing_index != -1:
                        # It was an update, replace the old version
                        newly_created_or_updated_memories_in_batch[
                            existing_index
                        ] = processed_memory
                    else:
                        # It was a creation, add it
                        newly_created_or_updated_memories_in_batch.append(
                            processed_memory
                        )

            except Exception as e:
                logger.error(
                    "Failed to process memory for turn ending with message at"
                    f" timestamp {current_timestamp}. This turn will be"
                    f" skipped. Error: {e}"
                )
                # The timestamp is already updated, so we just continue to the next turn.
                continue

            if progress_callback:
                progress = int(((i + 1) / total_turns) * max_progress)
                progress_callback(progress, i + 1, total_turns)

        logger.info(
            "Profile update processing loop complete. Final timestamp is set"
            " to the last message processed or attempted."
        )

    def decay_all_memories(self, decay_factor: float = 0.998):
        """Applies a decay factor to the relevance of all memories."""
        # This is a public wrapper for the decay functionality.
        with self._db_lock:
            self._decay_memory_relevance(decay_factor)

    def _decay_memory_relevance(self, decay_factor: float = 0.998):
        """Applies a decay factor to the relevance of all memories."""
        logger.info(f"Applying relevance decay (factor: {decay_factor})...")
        try:
            with self.storage.conn:
                cursor = self.storage.conn.cursor()
                cursor.execute(
                    "UPDATE user_memories SET relevance = relevance * ? WHERE"
                    " status = 'current'",
                    (decay_factor,),
                )
                current_updated_count = cursor.rowcount
                cursor.execute(
                    "UPDATE user_memories SET relevance = relevance * ? WHERE"
                    " status = 'past'",
                    (decay_factor**4,),
                )
                past_updated_count = cursor.rowcount
                total_updated = current_updated_count + past_updated_count
            if total_updated > 0:
                logger.info(
                    f"Decayed relevance for {total_updated} memories"
                    f" ({current_updated_count} current,"
                    f" {past_updated_count} past)."
                )
        except Exception as e:
            logger.error(f"Failed to decay memory relevance: {e}")

    def _reinforce_memory(
        self, memory_id: str, increment: float = 1
    ) -> bool:
        """Finds a memory by ID and increases its relevance."""
        try:
            with self.storage.conn:
                cursor = self.storage.conn.execute(
                    # Relevance limited up to 200
                    "UPDATE user_memories SET relevance = relevance + ?,"
                    " last_updated = ? WHERE id = ? AND relevance < 200",
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

    def _update_memory(
        self,
        memory_id: str,
        new_text: str,
        user_message: Dict,
        assistant_message: Dict,
    ) -> Optional[Dict]:
        """Updates an existing memory's text and boosts its relevance."""
        try:
            # First, get the existing memory to preserve other metadata
            cursor = self.storage.conn.cursor()
            cursor.execute(
                "SELECT * FROM user_memories WHERE id = ?", (memory_id,)
            )
            row = cursor.fetchone()
            if not row:
                logger.error(
                    f"Attempted to update non-existent memory: {memory_id}"
                )
                return None

            existing_memory = self._dict_from_row(row)
            new_last_updated = datetime.now(timezone.utc).isoformat()

            # Handle source_message_ids
            source_ids = existing_memory.get("source_message_ids") or []
            new_ids = [
                uid
                for uid in [
                    user_message.get("id"),
                    assistant_message.get("id"),
                ]
                if uid
            ]
            # Avoid duplicates
            for new_id in new_ids:
                if new_id not in source_ids:
                    source_ids.append(new_id)
            updated_source_ids_json = json.dumps(source_ids)

            # Update in SQLite, boosting relevance
            with self.storage.conn:
                cursor = self.storage.conn.execute(
                    """
                    UPDATE user_memories
                    SET memory = ?, relevance = relevance + 1.0, last_updated = ?, source_message_ids = ?
                    WHERE id = ?
                    """,
                    (
                        new_text,
                        new_last_updated,
                        updated_source_ids_json,
                        memory_id,
                    ),
                )

            if cursor.rowcount == 0:
                return None  # Should not happen if row was found

            logger.info(f"Updated memory {memory_id} in SQLite.")

            # Update in vector store
            if self.vector_storage:
                updated_memory_obj = existing_memory.copy()
                updated_memory_obj["memory"] = new_text
                updated_memory_obj["last_updated"] = new_last_updated
                updated_memory_obj["source_message_ids"] = source_ids
                # Fetch new relevance to keep vector store metadata in sync
                updated_memory_obj["status"] = "current"
                cursor.execute(
                    "SELECT relevance FROM user_memories WHERE id = ?",
                    (memory_id,),
                )
                updated_memory_obj["relevance"] = cursor.fetchone()[0]

                normalized_text_for_vector = self._normalize_memory_text(
                    new_text
                )
                document_to_update = {
                    "page_content": normalized_text_for_vector,
                    "metadata": updated_memory_obj,
                }
                self.vector_storage.add_documents([document_to_update])
                logger.info(f"Updated memory {memory_id} in vector store.")

            return updated_memory_obj
        except Exception as e:
            logger.error(f"Failed to update memory {memory_id}: {e}")
            return None

    def _create_new_memory(
        self, memory_data: Dict, user_message: Dict, assistant_message: Dict
    ) -> Optional[Dict]:
        """Adds a new memory to the profile and vector store."""
        target_section = memory_data.get("target", "extended_memories")
        new_memory = memory_data.get("memory_data", {})
        topic = new_memory.get("topic", "general")
        # Use the raw, unnormalized memory text for storage and display.
        memory_text = new_memory.get("memory", "").strip()

        if not memory_text:
            logger.warning(
                "Attempted to create a memory with no text. Skipping."
            )
            return None

        if target_section not in ["key_memories", "extended_memories"]:
            logger.warning(
                f"LLM returned invalid target section: '{target_section}'."
                " Defaulting to extended_memories."
            )
            target_section = "extended_memories"

        memory_id = str(uuid.uuid4())
        now_timestamp = datetime.now(timezone.utc).isoformat()
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
                    INSERT INTO user_memories (id, memory_type, topic, memory, relevance, created_at, last_updated, source_message_ids)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        target_section,
                        topic,
                        memory_text,
                        1.0,
                        now_timestamp,
                        now_timestamp,
                        source_ids,
                    ),
                )
            logger.info(
                f"Added new memory to '{target_section}' under topic: {topic}"
            )

            full_memory_obj = None
            # Add to vector store regardless of type for de-duplication
            if self.vector_storage:
                # We need the full memory object for metadata
                full_memory_obj = {
                    "id": memory_id,
                    "memory_type": target_section,
                    "topic": topic,
                    "memory": memory_text,
                    "relevance": 1.0,
                    "created_at": now_timestamp,
                    "last_updated": now_timestamp,
                    "source_message_ids": json.loads(source_ids),
                    "status": "current",
                }
                # Normalize the text ONLY for the vector embedding
                normalized_text_for_vector = self._normalize_memory_text(
                    memory_text
                )
                document_to_add = {
                    "page_content": normalized_text_for_vector,
                    "metadata": full_memory_obj,
                }
                self.vector_storage.add_documents([document_to_add])
                logger.info(
                    f"Indexed new memory (ID: {memory_id}) in vector store."
                )
            return full_memory_obj
        except Exception as e:
            logger.error(f"Failed to create new memory in database: {e}")
            return None

    def _mark_memories_as_past(self, memory_ids: List[str]):
        """Marks memories as 'past' in SQLite and updates them in the vector store."""
        if not memory_ids:
            return

        logger.info(f"Marking {len(memory_ids)} memories as past.")
        try:
            placeholders = ",".join("?" for _ in memory_ids)
            # Step 1: Update status in SQLite
            with self.storage.conn:
                cursor = self.storage.conn.execute(
                    "UPDATE user_memories SET status = 'past' WHERE id IN"
                    f" ({placeholders})",
                    memory_ids,
                )
                logger.info(
                    f"Marked {cursor.rowcount} memories as past in SQLite."
                )

            # Step 2: Update in vector store by re-adding (upserting) with new status
            if self.vector_storage:
                # Fetch the updated memories from SQLite to get all fields
                with self.storage.conn:
                    cursor = self.storage.conn.execute(
                        "SELECT * FROM user_memories WHERE id IN"
                        f" ({placeholders})",
                        memory_ids,
                    )
                    updated_memories = [
                        self._dict_from_row(row) for row in cursor.fetchall()
                    ]

                if updated_memories:
                    documents_to_update = [
                        {
                            "page_content": self._normalize_memory_text(
                                mem["memory"]
                            ),
                            "metadata": mem,
                        }
                        for mem in updated_memories
                    ]
                    self.vector_storage.add_documents(documents_to_update)
                    logger.info(
                        f"Updated {len(updated_memories)} memories in vector"
                        " store to 'past' status."
                    )
        except Exception as e:
            logger.error(f"Failed to mark memories as past: {e}")

    def _delete_memories(
        self, memory_ids: List[str], consolidate_into_id: Optional[str] = None
    ):
        """
        Deletes memories from SQLite and the vector store.
        Optionally consolidates their relevance into another memory before deletion.
        """
        if not memory_ids:
            return

        logger.info(f"Deleting {len(memory_ids)} duplicate memories.")
        try:
            placeholders = ",".join("?" for _ in memory_ids)
            with self.storage.conn:
                if consolidate_into_id:
                    cursor = self.storage.conn.cursor()
                    # Sum relevance from duplicates
                    cursor.execute(
                        "SELECT SUM(relevance) FROM user_memories WHERE id IN"
                        f" ({placeholders})",
                        memory_ids,
                    )
                    total_relevance_from_duplicates = cursor.fetchone()[0]

                    if total_relevance_from_duplicates:
                        # Add to the kept memory
                        cursor.execute(
                            "UPDATE user_memories SET relevance = relevance +"
                            " ? WHERE id = ?",
                            (
                                total_relevance_from_duplicates,
                                consolidate_into_id,
                            ),
                        )
                        logger.info(
                            f"Transferred {total_relevance_from_duplicates:.2f}"
                            " relevance from"
                            f" {len(memory_ids)} duplicates to memory"
                            f" {consolidate_into_id}."
                        )

                cursor = self.storage.conn.execute(
                    f"DELETE FROM user_memories WHERE id IN ({placeholders})",
                    memory_ids,
                )
                deleted_count = cursor.rowcount
                logger.info(
                    f"Deleted {deleted_count} memories from SQLite."
                )

            if deleted_count > 0 and self.vector_storage:
                self.vector_storage.delete(memory_ids)
                logger.info(
                    f"Deleted {len(memory_ids)} memories from vector store."
                )
        except Exception as e:
            logger.error(f"Failed to delete memories: {e}")

    def _extract_and_assimilate_memory(
        self,
        conversation_turns: List[tuple[Dict, Dict]],
        batch_context_memories: List[Dict] = None,
    ) -> Optional[Dict]:
        """
        Analyzes a conversation turn, compares it with existing memories, and
        decides whether to ignore, reinforce, update, or create a memory using an LLM.

        Returns:
            Optional[Dict]: The created or updated memory object, or None if no
                            change was made or a non-fatal error occurred.
        """
        if not conversation_turns:
            return None

        user_message, assistant_message = conversation_turns[-1]
        llm_response_str = ""

        try:
            # Step 1: Create conversation snippet for the LLM
            conversation_snippet = "\n".join(
                [
                    f"User: {u['content']}\nAssistant: {a['content']}"
                    for u, a in conversation_turns
                ]
            )

            # Step 2: Find potentially related memories via semantic search
            # We use the last user message as the query to find relevant context.
            query_text = user_message.get("content", "")
            # # !!! DEBUG
            # logger.info(f"Memory assimilation query: '{query_text}'")
            existing_memories = []
            is_substantive = self._is_query_substantive(query_text)
            # # !!! DEBUG
            # logger.info(f"Is query substantive? {is_substantive}")
            if self.vector_storage and is_substantive:
                # Fetch a few relevant memories to provide context to the LLM
                if self.context_window <= 8192:
                    search_limit = 20
                elif self.context_window <= 32768:
                    search_limit = 35
                else:
                    search_limit = 60
                logger.info(
                    f"Context window is {self.context_window}, dynamically"
                    " setting memory search limit for LLM context to"
                    f" {search_limit}"
                )

                search_results = self.vector_storage.search_with_scores(
                    query_text,
                    limit=search_limit,
                )
                # # !!! DEBUG
                # logger.info(
                #     f"Vector search raw results: {search_results}"
                # )
                if search_results:
                    existing_memories = [
                        doc.get("metadata", {})
                        for doc, score in search_results
                    ]
                    logger.info(
                        f"Found {len(existing_memories)} related memories for"
                        " context."
                    )

            # Merge memories created/updated earlier in this same batch run.
            # This gives the LLM immediate context to prevent duplicates.
            if batch_context_memories:
                existing_ids = {mem["id"] for mem in existing_memories}
                for mem in batch_context_memories:
                    if mem["id"] not in existing_ids:
                        existing_memories.append(mem)
                logger.info(
                    f"Added {len(batch_context_memories)} memories from"
                    " current batch to LLM context."
                )

            # Step 3: Use the LLM to decide on the action
            processing_prompt = self.template_manager.render(
                "framework.green_memories.consolidated_memory_processing",
                {
                    "conversation_snippet": conversation_snippet,
                    "existing_memories": existing_memories,
                },
            )
            system_prompt = self.template_manager.render(
                "framework.green_memories.extract_memory_candidate_system"
            )
            processing_history = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": processing_prompt},
            ]
            # # !!! DEBUG
            # logger.info(
            #     "Sending memory processing request to LLM with user prompt:\n---"
            #     f"-----\n{processing_prompt}\n--------"
            # )
            llm_response_str = self.llm.chat(
                chat_history=processing_history, stream=False
            )
            # !!! DEBUG
            logger.info(f"LLM raw response for memory processing:\n--------------\n{llm_response_str}\n-----------")
            decision = json.loads(llm_response_str)
            action = decision.get("action")

            # Check for memories to mark as past, regardless of action (except ignore)
            past_ids = decision.get("past_memory_ids", [])
            if past_ids:
                self._mark_memories_as_past(past_ids)

            # Step 4: Execute the decided action
            if action == "ignore":
                logger.info(
                    "LLM decided to ignore the conversation for memory."
                )
                return None

            elif action == "reinforce":
                memory_id = decision.get("memory_id")
                new_text = decision.get("new_memory_text")

                if not memory_id:
                    logger.warning(
                        "LLM chose 'reinforce' but provided no memory_id."
                    )
                elif new_text:
                    # This is a reinforcement that also updates the memory text.
                    logger.info(f"LLM decided to update memory: {memory_id}")
                    # The return from _update_memory is the updated memory object
                    # which needs to be passed back to the main loop.
                    return self._update_memory(
                        memory_id, new_text, user_message, assistant_message
                    )
                else:
                    # This is a simple reinforcement, just boosting the score.
                    logger.info(
                        f"LLM decided to reinforce memory: {memory_id}"
                    )
                    self._reinforce_memory(memory_id)

                # Handle duplicates for deletion
                duplicates_to_delete = decision.get("duplicates", [])
                if duplicates_to_delete:
                    self._delete_memories(
                        duplicates_to_delete, consolidate_into_id=memory_id
                    )

            elif action == "create":
                logger.info("LLM decided to create a new memory.")
                return self._create_new_memory(
                    decision, user_message, assistant_message
                )

            else:
                logger.warning(f"LLM returned an unknown action: '{action}'")

            return None
        except json.JSONDecodeError:
            logger.warning(
                "LLM returned invalid JSON for memory processing:"
                f" {llm_response_str}"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to assimilate memory from conversation: {e}")
            # Re-raise to be caught by the main loop for poison-pill handling
            raise
