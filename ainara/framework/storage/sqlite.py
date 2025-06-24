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
        db_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(db_dir, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
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
