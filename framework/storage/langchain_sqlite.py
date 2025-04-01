# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez - khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ainara.framework.storage.base import StorageBackend

from langchain.memory.chat_message_histories import SQLChatMessageHistory
from langchain.schema import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


class LangChainSQLiteStorage(StorageBackend):
    """LangChain SQLite implementation of chat storage"""

    def __init__(
        self,
        db_path: str = None,
        context_id: str = "persona:default",
        **kwargs,
    ):
        """
        Initialize LangChain SQLite storage

        Args:
            db_path: Path to SQLite database file
            context_id: Context identifier for the conversation
            **kwargs: Additional parameters
        """

        self.db_path = db_path
        self.context_id = context_id

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        # Create SQLite connection string
        sqlite_uri = f"sqlite:///{db_path}"

        # Initialize LangChain's SQLChatMessageHistory
        # LangChain still uses session_id terminology
        self.history = SQLChatMessageHistory(
            session_id=context_id, connection_string=sqlite_uri
        )

    def add_message(
        self,
        content: str,
        role: str = "user",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a message to the conversation"""
        # Generate a unique ID
        message_id = str(uuid.uuid4())

        # Convert to LangChain message format
        if role == "user":
            lc_message = HumanMessage(content=content)
        elif role == "assistant":
            lc_message = AIMessage(content=content)
        else:
            lc_message = SystemMessage(content=content)

        # Add metadata if provided
        if metadata:
            # Store our message ID in the metadata
            metadata_with_id = metadata.copy()
            metadata_with_id["message_id"] = message_id
            lc_message.additional_kwargs = metadata_with_id
        else:
            lc_message.additional_kwargs = {"message_id": message_id}

        # Add to LangChain history
        self.history.add_message(lc_message)

        return message_id

    def get_messages(
        self, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get messages with pagination"""
        # Get all messages from LangChain
        all_messages = self.history.messages

        # Apply pagination
        paginated_messages = (
            all_messages[-limit - offset: -offset]
            if offset > 0
            else all_messages[-limit:]
        )

        # Convert to our format
        result = []
        for msg in paginated_messages:
            # Determine role
            if isinstance(msg, HumanMessage):
                role = "user"
            elif isinstance(msg, AIMessage):
                role = "assistant"
            else:
                role = "system"

            # Extract metadata and message_id
            metadata = (
                msg.additional_kwargs.copy()
                if hasattr(msg, "additional_kwargs")
                else {}
            )
            message_id = metadata.pop("message_id", str(uuid.uuid4()))

            # Create our message format
            result.append(
                {
                    "id": message_id,
                    "timestamp": metadata.pop(
                        "timestamp", datetime.now().isoformat()
                    ),
                    "role": role,
                    "content": msg.content,
                    "metadata": metadata,
                }
            )

        return result

    def get_message_count(self) -> int:
        """Get total number of messages"""
        return len(self.history.messages)

    def search_text(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Basic text search"""
        # Get all messages
        all_messages = self.get_messages(limit=1000)  # Practical limit

        # Filter by query
        results = []
        for msg in all_messages:
            if query.lower() in msg["content"].lower():
                results.append(msg)
                if len(results) >= limit:
                    break

        return results

    def close(self):
        """Close any resources"""
        # LangChain's SQLChatMessageHistory doesn't need explicit closing
        pass
