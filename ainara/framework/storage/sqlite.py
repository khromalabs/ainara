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
        if not db_path or not db_path.strip():
            raise ValueError(
                "SQLiteStorage initialized with invalid db_path (None or empty)."
                " Check ConfigManager or initialization arguments."
            )

        self.db_path = db_path
        self.context_id = context_id

        try:
            db_dir = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(db_dir, exist_ok=True)

            self.conn = sqlite3.connect(
                db_path, check_same_thread=False, isolation_level=None
            )
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=FULL;")
            # Force WAL sync
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self._create_table()

            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT value FROM db_metadata WHERE key = 'memory_id'"
            )
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

        except (OSError, sqlite3.Error) as e:
            raise ValueError(
                f"Failed to initialize SQLite storage at '{db_path}': {str(e)}"
            ) from e

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
                "CREATE INDEX IF NOT EXISTS idx_cache_provider ON api_cache"
                " (provider);"
            )

            # Add table for background events (Notification System)
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS background_events (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_id TEXT,
                    content_hash TEXT,
                    data TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_source_extid ON"
                " background_events (source, external_id);"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_hash ON"
                " background_events (content_hash);"
            )

            # Check if 'processed' column exists in background_events (Migration)
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA table_info(background_events)")
            columns = [info[1] for info in cursor.fetchall()]
            if "processed" not in columns:
                self.conn.execute(
                    "ALTER TABLE background_events ADD COLUMN processed"
                    " INTEGER DEFAULT 0"
                )

            # Add table for User-Facing Notifications (Consolidated)
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    injected INTEGER DEFAULT 0
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notif_injected ON"
                " notifications (injected);"
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
        sort: str = "DESC",
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

        query += f" ORDER BY timestamp {sort} LIMIT ? OFFSET ?"
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
        query: str = None,
        limit: int = 10,
        offset: int = 0,
        include_terms: List[str] = None,
        exclude_terms: List[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        users: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search text with advanced filtering.

        Args:
            query: Legacy simple query string (treated as an include term)
            limit: Max results
            offset: Pagination offset
            include_terms: List of substrings that MUST be present (AND logic)
            exclude_terms: List of substrings that MUST NOT be present (NOT logic)
        """
        sql_query = "SELECT * FROM messages WHERE context_id = ?"
        params = [self.context_id]

        # Handle legacy query param or simple usage
        if query and not include_terms:
            include_terms = [query]

        # Add inclusions (AND LIKE)
        if include_terms:
            for term in include_terms:
                sql_query += " AND content LIKE ?"
                params.append(f"%{term}%")

        # Add exclusions (AND NOT LIKE)
        if exclude_terms:
            for term in exclude_terms:
                sql_query += " AND content NOT LIKE ?"
                params.append(f"%{term}%")

        if start_date:
            sql_query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            sql_query += " AND timestamp <= ?"
            params.append(end_date)
        if users:
            sql_query += f" AND user IN ({','.join('?' for _ in users)})"
            params.extend(users)

        sql_query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

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
                "INSERT OR REPLACE INTO db_metadata (key, value) VALUES"
                " (?, ?)",
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
                (
                    message_id,
                    context_id,
                    timestamp,
                    role,
                    content,
                    user,
                    json_metadata,
                )
            )

        if messages_to_insert:
            with self.conn:
                self.conn.executemany(
                    "INSERT INTO messages (id, context_id, timestamp, role,"
                    " content, user, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    messages_to_insert,
                )
            logger.info(
                f"Inserted {len(messages_to_insert)} historical messages into"
                " the database."
            )

    def is_event_processed(
        self, source: str, external_id: str = None, content_hash: str = None
    ) -> bool:
        """Check if a background event has already been processed."""
        cursor = self.conn.cursor()
        if external_id:
            cursor.execute(
                "SELECT 1 FROM background_events WHERE source = ? AND"
                " external_id = ?",
                (source, external_id),
            )
        elif content_hash:
            cursor.execute(
                "SELECT 1 FROM background_events WHERE source = ? AND"
                " content_hash = ?",
                (source, content_hash),
            )
        else:
            return False

        return cursor.fetchone() is not None

    def add_event(
        self,
        source: str,
        data: Any,
        external_id: str = None,
        content_hash: str = None,
    ):
        """Record a raw background event."""
        event_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        json_data = json.dumps(data) if not isinstance(data, str) else data

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO background_events (id, source, external_id, content_hash, data, timestamp, processed)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    event_id,
                    source,
                    external_id,
                    content_hash,
                    json_data,
                    timestamp,
                ),
            )

    def get_unprocessed_events(self) -> List[Dict[str, Any]]:
        """Get all raw events that haven't been consolidated yet."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM background_events WHERE processed = 0 ORDER BY"
            " timestamp ASC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def mark_events_processed(self, event_ids: List[str]):
        """
        Mark events as processed and PRUNE the data to save space.
        We keep the row (id/hash) for deduplication but remove the heavy JSON payload.
        """
        if not event_ids:
            return

        placeholders = ",".join("?" for _ in event_ids)
        with self.conn:
            # Set processed=1 AND wipe the data column (Pruning)
            self.conn.execute(
                "UPDATE background_events SET processed = 1, data = NULL"
                f" WHERE id IN ({placeholders})",
                event_ids,
            )

    def add_notification(self, source: str, content: str):
        """Add a consolidated user-facing notification."""
        notif_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO notifications (id, source, content, timestamp, injected)
                VALUES (?, ?, ?, ?, 0)
                """,
                (notif_id, source, content, timestamp),
            )

    def get_pending_notifications(self) -> List[Dict[str, Any]]:
        """Get notifications that haven't been shown to the user yet."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM notifications WHERE injected = 0 ORDER BY"
            " timestamp ASC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def mark_notifications_injected(self, notification_ids: List[str]):
        """Mark notifications as injected into the chat context."""
        if not notification_ids:
            return

        placeholders = ",".join("?" for _ in notification_ids)
        with self.conn:
            self.conn.execute(
                "UPDATE notifications SET injected = 1 WHERE id IN"
                f" ({placeholders})",
                notification_ids,
            )
