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
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ainara.framework.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class SQLiteStorage(StorageBackend):
    """LangChain SQLite implementation of chat storage"""

    def __init__(
        self,
        db_path: str = None,
        context_id: str = "persona-default",
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
        db_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(db_dir, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._create_table()

        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM db_metadata WHERE key = 'memory_id'")
        row = cursor.fetchone()
        if row is None:
            memory_id = str(uuid.uuid4())
            with self.conn:
                self.conn.execute(
                    "INSERT INTO db_metadata (key, value) VALUES (?, ?)",
                    ("memory_id", memory_id),
                )
            self.memory_id = memory_id
        else:
            self.memory_id = row[0]

    def _create_table(self):
        """Create tables and set schema version if they don't exist."""
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    context_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    user TEXT,
                    metadata TEXT
                )
                """
            )
            # Add indexes for faster queries
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_context_timestamp ON messages"
                " (context_id, timestamp);"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_context_user ON messages"
                " (context_id, user);"
            )

            # Add a metadata table for versioning
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS db_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            # Initialize the schema version
            self.conn.execute(
                "INSERT OR IGNORE INTO db_metadata (key, value) VALUES (?, ?)",
                ("schema_version", "1.0"),
            )

            # Add a generic cache table
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    cache_value TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_provider ON api_cache (provider);"
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

        meta = metadata.copy() if metadata else {}
        timestamp = meta.pop("timestamp", datetime.now().isoformat())
        user = meta.get("user")

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO messages (id, context_id, timestamp, role, content, user, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    self.context_id,
                    timestamp,
                    role,
                    content,
                    user,
                    json.dumps(meta),
                ),
            )

        return message_id

    def get_messages(
        self,
        limit: int = 100,
        offset: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        users: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get messages with pagination and filtering."""
        query = "SELECT * FROM messages WHERE context_id = ?"
        params = [self.context_id]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)
        if users:
            query += f" AND user IN ({','.join('?' for _ in users)})"
            params.extend(users)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Convert rows to dictionaries and parse metadata
        results = []
        for row in rows:
            msg = dict(row)
            if msg.get("metadata"):
                msg["metadata"] = json.loads(msg["metadata"])
            results.append(msg)
        return results

    def get_message_count(self) -> int:
        """Get total number of messages"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(id) FROM messages WHERE context_id = ?",
            (self.context_id,),
        )
        return cursor.fetchone()[0]

    def search_text(
        self,
        query: str,
        limit: int = 10,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        users: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Basic text search with filtering."""
        sql_query = (
            "SELECT * FROM messages WHERE context_id = ? AND content LIKE ?"
        )
        params = [self.context_id, f"%{query}%"]

        if start_date:
            sql_query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            sql_query += " AND timestamp <= ?"
            params.append(end_date)
        if users:
            sql_query += f" AND user IN ({','.join('?' for _ in users)})"
            params.extend(users)

        sql_query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(sql_query, params)
        rows = cursor.fetchall()

        # Convert rows to dictionaries and parse metadata
        results = []
        for row in rows:
            msg = dict(row)
            if msg.get("metadata"):
                msg["metadata"] = json.loads(msg["metadata"])
            results.append(msg)
        return results

    def get_message_by_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get a single message by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()

        if not row:
            return None

        msg = dict(row)
        if msg.get("metadata"):
            msg["metadata"] = json.loads(msg["metadata"])
        return msg

    def get_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cache entry by key.

        Args:
            key: The cache key.

        Returns:
            A dictionary representing the cache row, or None if not found.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM api_cache WHERE cache_key = ?", (key,))
        row = cursor.fetchone()

        if not row:
            return None

        return dict(row)

    def set_cache(self, key: str, value: str, provider: str):
        """
        Insert or replace a key-value pair in the cache.

        Args:
            key: The cache key.
            value: The value to store (should be a JSON string).
            provider: The name of the provider storing the data.
        """
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO api_cache (cache_key, provider, timestamp, cache_value)
                VALUES (?, ?, ?, ?)
                """,
                (key, provider, int(time.time()), value),
            )

    def clear_expired_cache(self, ttl_seconds: int):
        """
        Removes expired entries from the cache table.

        Args:
            ttl_seconds: The time-to-live for cache entries in seconds.
        """
        expiration_time = int(time.time()) - ttl_seconds
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                "DELETE FROM api_cache WHERE timestamp < ?", (expiration_time,)
            )
            logger.info(f"Cleared {cursor.rowcount} expired cache entries.")

    def get_metadata(self, key: str) -> Optional[str]:
        """Get a value from the metadata table."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM db_metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def set_metadata(self, key: str, value: str):
        """Set a value in the metadata table."""
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO db_metadata (key, value) VALUES (?, ?)",
                (key, value),
            )

    def delete_metadata(self, keys: List[str]):
        """Delete one or more keys from the metadata table."""
        if not keys:
            return
        placeholders = ",".join("?" for _ in keys)
        with self.conn:
            self.conn.execute(
                f"DELETE FROM db_metadata WHERE key IN ({placeholders})",
                keys,
            )

    def get_messages_since(
        self, timestamp: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all messages since a given timestamp."""
        query = "SELECT * FROM messages WHERE context_id = ?"
        params = [self.context_id]

        if timestamp:
            query += " AND timestamp > ?"
            params.append(timestamp)

        query += " ORDER BY timestamp ASC"

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Convert rows to dictionaries and parse metadata
        results = []
        for row in rows:
            msg = dict(row)
            if msg.get("metadata"):
                msg["metadata"] = json.loads(msg["metadata"])
            results.append(msg)
        return results

    def close(self):
        """Close any resources"""
        if self.conn:
            self.conn.close()

    def add_historical_messages(self, messages: List[Dict[str, Any]]):
        """
        Adds a batch of historical messages to the database.
        Each message in the list should be a dictionary with 'role', 'content',
        'timestamp', and 'metadata'.
        """
        if not messages:
            return

        messages_to_insert = []
        for msg in messages:
            message_id = str(uuid.uuid4())
            # Per requirements, context_id is fixed and user is None
            context_id = self.context_id
            user = None
            timestamp = msg.get("timestamp")
            role = msg.get("role")
            content = msg.get("content")
            metadata = msg.get("metadata", {})

            if not all([timestamp, role, content]):
                logger.warning(
                    f"Skipping historical message due to missing data: {msg}"
                )
                continue

            json_metadata = json.dumps(metadata) if metadata else "{}"

            messages_to_insert.append(
                (message_id, context_id, timestamp, role, content, user, json_metadata)
            )

        if messages_to_insert:
            with self.conn:
                self.conn.executemany(
                    "INSERT INTO messages (id, context_id, timestamp, role, content, user, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    messages_to_insert,
                )
            logger.info(
                f"Inserted {len(messages_to_insert)} historical messages into the database."
            )
