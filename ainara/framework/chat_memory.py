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
from typing import Any, Dict, List, Optional

# Import our storage backends
from ainara.framework.storage.base import StorageBackend
from ainara.framework.storage import get_text_backend, get_vector_backend

logger = logging.getLogger(__name__)


class ChatMemory:
    """Stores interaction history with optional semantic search capabilities"""

    def __init__(
        self,
        context: Optional[Dict[str, str]] = None,
        storage_backend: Optional[StorageBackend] = None,
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
            # Get text storage configuration
            text_type = config.get("memory.text_storage.type", "sqlite")
            text_path = config.get(
                "memory.text_storage.storage_path",
                os.path.join(config.get("data.directory"), "chat_memory.db")
            )

            # Ensure path is expanded
            text_path = os.path.expanduser(text_path)

            # Create text backend
            try:
                self.storage = get_text_backend(
                    text_type,
                    db_path=text_path,
                    context_id=context_id
                )
                logger.info(
                    f"Using {text_type} storage backend with context {context_id}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize {text_type} backend: {e}")
                raise

        # Initialize vector storage if configured
        vector_type = config.get("memory.vector_storage.type", "chroma")
        vector_path = config.get(
            "memory.vector_db_path",
            os.path.join(config.get("data.directory"), "vector_db")
        )
        embedding_model = config.get(
            "memory.vector_storage.embedding_model",
            "sentence-transformers/all-mpnet-base-v2"
        )

        # Ensure path is expanded
        vector_path = os.path.expanduser(vector_path)
        self.vector_storage = get_vector_backend(
            vector_type,
            vector_db_path=vector_path,
            embedding_model=embedding_model,
            collection_name=context_id
        )
        logger.info(
            f"Using {vector_type} vector backend with context {context_id}"
        )

    def add_entry(
        self,
        content: str,
        role: str = "user",
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a new entry to both storage backends

        Args:
            content: The message content
            role: The role of the sender (user, assistant, system)
            user_id: Optional user identifier (overrides context user)
            metadata: Additional metadata

        Returns:
            Message ID
        """
        # Create metadata with context information
        entry_metadata = metadata.copy() if metadata else {}

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
                vector_metadata.update(
                    {"message_id": message_id, "role": role}
                )

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
        self, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get paginated chat history"""
        return self.storage.get_messages(limit=limit, offset=offset)

    def search_entries(
        self, query: str, limit: int = 5, use_vector: bool = True
    ) -> List[Dict[str, Any]]:
        """Search entries using vector search if available, fallback to text search"""
        # Try vector search first if requested and available
        if use_vector and self.vector_storage:
            try:
                return self.vector_storage.search(query, limit=limit)
            except Exception as e:
                logger.error(
                    f"Vector search failed, falling back to text search: {e}"
                )

        # Fallback to basic text search
        return self.storage.search_text(query, limit)

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
                os.path.join(config.get("data.directory"), "chat_memory.db")
            )

            # Create new text backend with new context
            self.storage = get_text_backend(
                text_type,
                db_path=os.path.expanduser(text_path),
                context_id=new_context_id
            )

            vector_type = config.get("memory.vector_storage.type", "chroma")
            vector_path = config.get(
                "memory.vector_storage.storage_path",
                os.path.join(config.get("data.directory"), "chat_memory.db")
            )
            embedding_model = config.get(
                "memory.vector_storage.embedding_model",
                "sentence-transformers/all-mpnet-base-v2"
            )

            # Create new vector backend with new context
            self.vector_storage = get_vector_backend(
                vector_type,
                vector_db_path=os.path.expanduser(vector_path),
                embedding_model=embedding_model,
                collection_name=new_context_id
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
