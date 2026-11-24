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
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ainara.framework.storage import get_text_backend, get_vector_backend
# Import our storage backends
from ainara.framework.storage.base import StorageBackend
from ainara.framework.storage.time_bounds import (
    resolve_date_bound,
    timestamp_to_epoch,
)
from ainara.framework import vector_recipe

logger = logging.getLogger(__name__)


class ChatMemory:
    """Stores interaction history with optional semantic search capabilities"""

    def __init__(
        self,
        storage_backend: StorageBackend,
        context: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize memory with context-aware storage

        Args:
            context: Dictionary of context identifiers (persona, user, etc.)
            storage_backend: Custom storage backend (if provided)
        """
        # Import global config
        from ainara.framework.config import config

        # Process context parameter
        if context is None:
            # Default context is just the default persona
            context = config.get(
                "memory.default_context", {"persona": "default"}
            )

        # Generate context_id from the context dictionary
        self.context = context
        context_id = "_".join(f"{k}-{v}" for k, v in sorted(context.items()))

        # Use provided backend or create one from config
        if storage_backend:
            self.storage = storage_backend
            logger.info("Using provided storage backend")
        else:
            logger.error("Missing required storage backend")
            raise

        # Initialize vector storage if configured
        vector_type = config.get("memory.vector_storage.type", "chroma")
        vector_path = config.get(
            "memory.vector_db_path",
            os.path.join(config.get("data.directory"), "vector_db"),
        )
        embedding_model = config.get(
            "memory.vector_storage.embedding_model",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )

        # Ensure path is expanded
        vector_path = os.path.expanduser(vector_path)
        try:
            self.vector_storage = get_vector_backend(
                vector_type,
                vector_db_path=vector_path,
                embedding_model=embedding_model,
                collection_name=context_id,
            )
            logger.info(
                f"Using {vector_type} vector backend with context {context_id}"
            )

            # Recipe gate: the vector mirror is disposable derived data.
            # When it was built with a different derivation recipe
            # (metadata schema version or embedding model) it is stale
            # by definition — rebuild it in the background from the
            # relational source of truth instead of repairing it.
            if not vector_recipe.is_current(
                vector_path, "chat", embedding_model
            ):
                logger.info(
                    "Vector recipe changed (%s); rebuilding the vector"
                    " index in the background",
                    vector_recipe.stale_reason(
                        vector_path, "chat", embedding_model
                    ),
                )
                threading.Thread(
                    target=self._rebuild_vector_recipe,
                    args=(vector_path, embedding_model),
                    daemon=True,
                    name="vector-recipe-rebuild",
                ).start()
        except ImportError:
            logger.warning(
                f"Vector storage backend '{vector_type}' dependencies not"
                " found. Semantic search will be disabled."
            )
            self.vector_storage = None
        except Exception as e:
            logger.error(f"Failed to initialize vector storage: {e}")
            self.vector_storage = None

    def _rebuild_vector_recipe(
        self, vector_path: str, embedding_model: str
    ) -> None:
        """Background rebuild after a vector-recipe change.

        The vector store is a disposable mirror of the relational store;
        re_index_vectors() derives it anew. No backup of the old mirror
        is taken: it carries no information the relational store does
        not, and a failed rebuild is retried by fixing the code, not by
        restoring a blob.
        """
        try:
            self.re_index_vectors()
            vector_recipe.mark_current(vector_path, "chat", embedding_model)
        except Exception as e:
            logger.error(f"Background vector recipe rebuild failed: {e}")

    def add_entry(
        self,
        content: str,
        role: str = "user",
        source_type: str = "chat_history",
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a new entry to both storage backends

        Args:
            content: The message content
            role: The role of the sender (user, assistant, system)
            source_type: The origin of the content (e.g., 'chat_history', 'local_document')
            user_id: Optional user identifier (overrides context user)
            metadata: Additional metadata

        Returns:
            Message ID
        """
        # Create metadata with context information
        entry_metadata = metadata.copy() if metadata else {}

        # Add the source type to the metadata
        entry_metadata["source_type"] = source_type

        # Add role to metadata for consistency across backends
        entry_metadata["role"] = role

        # Add a timestamp if one isn't already present. This is the authoritative timestamp.
        if "timestamp" not in entry_metadata:
            entry_metadata["timestamp"] = datetime.now(
                timezone.utc
            ).isoformat()

        # Numeric epoch mirror of the timestamp for vector-store date
        # filtering (Chroma range operators only work on numeric
        # metadata). Recomputed even for caller-supplied timestamps so
        # it can never drift from the string form.
        ts_epoch = timestamp_to_epoch(entry_metadata["timestamp"])
        if ts_epoch is not None:
            entry_metadata["timestamp_ts"] = ts_epoch

        # Add context information to metadata
        for key, value in self.context.items():
            if key not in entry_metadata:
                entry_metadata[key] = value

        # Override with explicit user_id if provided
        if user_id is not None:
            entry_metadata["user"] = user_id

        # Add to text storage
        message_id = self.storage.add_message(
            content=content, role=role, metadata=entry_metadata
        )

        # Add to vector storage if available
        if self.vector_storage:
            try:
                vector_metadata = entry_metadata.copy()
                vector_metadata["message_id"] = message_id

                self.vector_storage.add_text(
                    text=content, metadata=vector_metadata
                )
            except Exception as e:
                logger.error(f"Error adding to vector storage: {e}")

        return message_id

    def get_recent_entries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recent entries"""
        return self.storage.get_messages(limit=limit)

    def get_chat_history(
        self,
        limit: int = 100,
        offset: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        users: Optional[List[str]] = None,
        sort: str = "ASC"
    ) -> List[Dict[str, Any]]:
        """Get paginated chat history"""
        return self.storage.get_messages(
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
            users=users,
            sort=sort
        )

    def format_messages_to_markdown(
        self, messages: List[Dict[str, Any]]
    ) -> str:
        """
        Formats a list of message dictionaries into a Markdown string.

        Args:
            messages: A list of message dictionaries.

        Returns:
            A formatted Markdown string.
        """
        markdown_lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            role_prefix = "U" if role == "user" else "A"
            content = msg.get("content", "")
            content = re.sub(r"\n+", "\n", content)
            timestamp = msg.get("timestamp")

            dt_object = datetime.fromisoformat(timestamp)
            if dt_object.tzinfo is None:
                dt_object = dt_object.replace(tzinfo=timezone.utc)

            time_str = dt_object.astimezone().strftime("%H:%M:%S")
            markdown_lines.append(
                f"`{time_str}` **{role_prefix}:** {content}"
            )
        return "\n".join(markdown_lines)

    def search_entries(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        users: Optional[List[str]] = None,
        all_contexts: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search entries using text search with syntax support, or vector search if prefixed with ~.
        Syntax:
          "phrase" : Exact match
          -word    : Exclude word
          word     : Include word
          ~query   : Semantic search (ignores syntax)

        all_contexts: search across every stored conversation context
        instead of only the active one (Deep Recall's corpus spans all
        threads). The semantic route is context-agnostic by design;
        the flag affects the exact/text route.
        """
        if not query:
            return []

        # 1. Vector Search Route (Semantic)
        if query.startswith("~"):
            search_query = query[1:].strip()
            if self.vector_storage:
                start_dt = resolve_date_bound(start_date, is_end=False)
                end_dt = resolve_date_bound(end_date, is_end=True)
                if (start_date and start_dt is None) or (
                    end_date and end_dt is None
                ):
                    # An explicit bound we cannot parse cannot scope the
                    # vector search; the text route still handles the
                    # raw string, so fall through to it.
                    query = search_query
                else:
                    # Note: Vector storage typically doesn't support offset
                    # pagination efficiently. We pass the limit. Date bounds
                    # are applied natively by the backend (numeric metadata
                    # filter), so results are ranked WITHIN the window, not
                    # globally and then filtered.
                    return self.vector_storage.search(
                        search_query,
                        limit=limit,
                        start_ts=(
                            start_dt.timestamp() if start_dt else None
                        ),
                        end_ts=end_dt.timestamp() if end_dt else None,
                    )
            # Fallback to text search if no vector storage, treating query as literal
            query = search_query

        # 2. Text Search Parsing (Relational)
        include_terms = []
        exclude_terms = []

        # Extract quoted phrases first
        phrase_pattern = re.compile(r'"([^"]*)"')
        phrases = phrase_pattern.findall(query)
        include_terms.extend(phrases)

        # Remove phrases from query to process individual words
        remaining_query = phrase_pattern.sub(' ', query)

        # Process words
        words = remaining_query.split()
        for word in words:
            if word.startswith("-") and len(word) > 1:
                exclude_terms.append(word[1:])
            else:
                include_terms.append(word)

        # 3. Execute Search
        return self.storage.search_text(
            limit=limit,
            offset=offset,
            include_terms=include_terms,
            exclude_terms=exclude_terms,
            start_date=start_date,
            end_date=end_date,
            users=users,
            all_contexts=all_contexts
        )

    def browse_window(
        self,
        start_date: str,
        end_date: str,
        offset: int = 0,
        limit: int = 25,
        all_contexts: bool = True,
    ) -> List[Dict[str, Any]]:
        """Chronological page of raw messages within a period. The
        coverage instrument behind Deep Recall's browse_logs tool:
        bare dates cover the whole day, results are ordered oldest
        first so a period can be read in sequence."""
        start_dt = resolve_date_bound(start_date, is_end=False)
        end_dt = resolve_date_bound(end_date, is_end=True)
        if start_dt is None or end_dt is None:
            return []
        return self.storage.get_messages(
            limit=limit,
            offset=offset,
            sort="ASC",
            start_date=start_dt.isoformat(),
            end_date=end_dt.isoformat(),
            all_contexts=all_contexts,
        )

    def window_overview(
        self,
        start_date: str,
        end_date: str,
        all_contexts: bool = True,
    ) -> Dict[str, Any]:
        """Mechanical density facts about a period (message counts,
        first/last activity, weekly distribution); date bounds
        normalized here so every caller shares the same semantics."""
        start_dt = resolve_date_bound(start_date, is_end=False)
        end_dt = resolve_date_bound(end_date, is_end=True)
        if start_dt is None or end_dt is None:
            return {"count": 0, "first": None, "last": None, "weekly": []}
        overview = self.storage.window_overview(
            start_dt.isoformat(),
            end_dt.isoformat(),
            all_contexts=all_contexts,
        )
        return overview if overview else {
            "count": 0, "first": None, "last": None, "weekly": []
        }

    def get_total_messages(self) -> int:
        """Get total number of messages in the history"""
        return self.storage.get_message_count()

    def switch_context(self, new_context: Dict[str, str]) -> bool:
        """
        Switch to a different context

        Args:
            new_context: New context dictionary

        Returns:
            Success status
        """
        # Generate new context_id
        new_context_id = "_".join(
            f"{k}-{v}" for k, v in sorted(new_context.items())
        )

        # Import global config
        from ainara.framework.config import config

        # Store current backends
        old_storage = self.storage
        old_vector = self.vector_storage

        try:
            # Get text storage configuration
            text_type = config.get("memory.text_storage.type", "sqlite")
            text_path = config.get(
                "memory.text_storage.storage_path",
                os.path.join(config.get("data.directory"), "chat_memory.db"),
            )

            # Create new text backend with new context
            self.storage = get_text_backend(
                text_type,
                db_path=os.path.expanduser(text_path),
                context_id=new_context_id,
            )

            vector_type = config.get("memory.vector_storage.type", "chroma")
            vector_path = config.get(
                "memory.vector_storage.storage_path",
                os.path.join(config.get("data.directory"), "chat_memory.db"),
            )
            embedding_model = config.get(
                "memory.vector_storage.embedding_model",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            )

            # Create new vector backend with new context
            self.vector_storage = get_vector_backend(
                vector_type,
                vector_db_path=os.path.expanduser(vector_path),
                embedding_model=embedding_model,
                collection_name=new_context_id,
            )

            # Update context
            self.context = new_context

            # Close old backends
            old_storage.close()
            if old_vector:
                old_vector.close()

            return True
        except Exception as e:
            logger.error(f"Failed to switch context: {e}")
            # Restore old backends
            self.storage = old_storage
            self.vector_storage = old_vector
            return False

    def get_available_contexts(self) -> List[Dict[str, str]]:
        """
        Get list of available contexts in the storage

        Returns:
            List of context dictionaries
        """
        # This would require backend support to list available contexts
        # For now, return just the current context
        return [self.context]

    def re_index_vectors(self, batch_size: int = 100):
        """
        Clears and rebuilds the entire vector index from the text storage.

        This is a utility for maintenance, such as when changing embedding models
        or ensuring consistency between the text and vector stores.
        """
        if not self.vector_storage:
            logger.warning("No vector storage configured. Cannot re-index.")
            return

        logger.info("Starting vector re-indexing process...")
        self.vector_storage.reset()

        total_messages = self.get_total_messages()
        if total_messages == 0:
            logger.info("No messages to index.")
            return

        logger.info(f"Found {total_messages} messages to index.")

        for offset in range(0, total_messages, batch_size):
            messages = self.storage.get_messages(
                limit=batch_size, offset=offset
            )
            if not messages:
                break

            documents_to_add = []
            for msg in messages:
                meta = msg.get("metadata") or {}
                meta["message_id"] = msg["id"]
                meta["role"] = msg["role"]
                meta["timestamp"] = msg["timestamp"]
                # Numeric epoch mirror for vector-store date filtering.
                ts_epoch = timestamp_to_epoch(msg["timestamp"])
                if ts_epoch is not None:
                    meta["timestamp_ts"] = ts_epoch
                if msg.get("user"):
                    meta["user"] = msg["user"]

                documents_to_add.append(
                    {"page_content": msg["content"], "metadata": meta}
                )

            if documents_to_add:
                self.vector_storage.add_documents(documents_to_add)

            logger.info(
                f"Indexed {offset + len(messages)} /"
                f" {total_messages} messages."
            )

        logger.info("Vector re-indexing complete.")

    def close(self):
        """Close all resources"""
        self.storage.close()
        if self.vector_storage:
            self.vector_storage.close()

    # def migrate_to_new_backend(self, new_backend: StorageBackend) -> bool:
    #     """
    #     Migrate to a new storage backend
    #
    #     Args:
    #         new_backend: The new storage backend to migrate to
    #
    #     Returns:
    #         Success status
    #     """
    #     try:
    #         # Get total message count
    #         total = self.storage.get_message_count()
    #
    #         # Process in chunks of 1000
    #         chunk_size = 1000
    #         for offset in range(0, total, chunk_size):
    #             # Get chunk of messages
    #             messages = self.storage.get_messages(
    #                 limit=chunk_size, offset=offset
    #             )
    #
    #             # Add each message to new backend
    #             for msg in messages:
    #                 new_backend.add_message(
    #                     content=msg["content"],
    #                     role=msg["role"],
    #                     metadata=msg["metadata"],
    #                 )
    #
    #             logger.info(
    #                 f"Migrated {offset + len(messages)}/{total} messages"
    #             )
    #
    #         # Backup old storage
    #         old_storage = self.storage
    #
    #         # Switch to new storage
    #         self.storage = new_backend
    #
    #         # Close old storage
    #         old_storage.close()
    #
    #         return True
    #     except Exception as e:
    #         logger.error(f"Migration failed: {e}")
    #         return False
