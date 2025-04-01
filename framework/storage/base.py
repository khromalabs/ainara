# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez - khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class StorageBackend(ABC):
    """Abstract base class for chat storage backends"""

    @abstractmethod
    def add_message(self, content: str, role: str, metadata: Optional[Dict] = None) -> str:
        """
        Add a message to storage

        Args:
            content: The message content
            role: The role of the sender (user, assistant, system)
            metadata: Additional metadata for the message

        Returns:
            Message ID
        """
        pass

    @abstractmethod
    def get_messages(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Retrieve messages with pagination

        Args:
            limit: Maximum number of messages to retrieve
            offset: Number of messages to skip

        Returns:
            List of message dictionaries
        """
        pass

    @abstractmethod
    def get_message_count(self) -> int:
        """
        Get total number of messages

        Returns:
            Total message count
        """
        pass

    @abstractmethod
    def search_text(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search for messages containing text

        Args:
            query: Text to search for
            limit: Maximum number of results

        Returns:
            List of matching message dictionaries
        """
        pass

    @abstractmethod
    def close(self):
        """Close any open resources"""
        pass


"""
Example configuration for ChatMemory backends.
This file is for reference only and is not imported by the framework.

# Example configuration dictionary
CHAT_MEMORY_CONFIG = {
    "text_backend": {
        "type": "sqlite",  # or a custom backend like "my_package.redis_backend.RedisStorage"
        "config": {
            "db_path": "~/.config/ainara/chat_memory.db",
            "session_id": "default_session"
        }
    },
    "vector_backend": {
        "type": "chroma",  # or a custom backend
        "config": {
            "vector_db_path": "~/.config/ainara/vector_db",
            "embedding_model": "sentence-transformers/all-mpnet-base-v2",
            "collection_name": "chat_memory"
        }
    }
}

# Example usage:
from framework.chat_memory import ChatMemory

# Create ChatMemory with configuration
memory = ChatMemory(config=CHAT_MEMORY_CONFIG)

# Add an entry
memory.add_entry("Hello, world!", role="user")

# Search entries
results = memory.search_entries("world")

CUSTOM_BACKEND_CONFIG = {
    "text_backend": {
        "type": "my_package.redis_backend.RedisStorage",
        "config": {
            "host": "localhost",
            "port": 6379,
            "db": 0
        }
    }
}

memory = ChatMemory(config=CUSTOM_BACKEND_CONFIG)
"""
