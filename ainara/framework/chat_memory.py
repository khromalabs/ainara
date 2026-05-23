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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ainara.framework.storage import get_text_backend, get_vector_backend
# Import our storage backends
from ainara.framework.storage.base import StorageBackend

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
        except ImportError:
            logger.warning(
                f"Vector storage backend '{vector_type}' dependencies not"
                " found. Semantic search will be disabled."
            )
            self.vector_storage = None
        except Exception as e:
            logger.error(f"Failed to initialize vector storage: {e}")
            self.vector_storage = None

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
    ) -> List[Dict[str, Any]]:
        """
        Search entries using text search with syntax support, or vector search if prefixed with ~.
        Syntax:
          "phrase" : Exact match
          -word    : Exclude word
          word     : Include word
          ~query   : Semantic search (ignores syntax)
        """
        if not query:
            return []

        # 1. Vector Search Route (Semantic)
        if query.startswith("~"):
            search_query = query[1:].strip()
            if self.vector_storage:
                # Note: Vector storage typically doesn't support offset pagination efficiently
                # We pass the limit.
                return self.vector_storage.search(
                    search_query,
                    limit=limit,
                    # We could add date filters here if the vector backend supports it
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
            users=users
        )

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
