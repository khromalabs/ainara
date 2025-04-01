# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez - khromalabs.org

import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from framework.config import ConfigManager
from framework.storage.langchain_vector import LangChainVectorStorage

from .document_loaders import get_document_loader
from .file_watcher import FileSystemWatcher

logger = logging.getLogger(__name__)


class DocumentIndexManager:
    """
    Manages document indexing and searching capabilities for the Ainara framework.
    Provides automatic indexing of user documents and semantic search functionality.
    """

    def __init__(self):
        """Initialize the document indexing system"""
        self.config = ConfigManager()
        self._initialize_storage()
        self._initialize_index_db()
        self._initialize_watcher()

    def _initialize_storage(self):
        """Initialize the vector storage backend"""
        vector_db_path = self.config.get(
            "document_index.vector_db_path",
            os.path.join(self.config.get_data_dir(), "document_vectors"),
        )

        self.vector_storage = LangChainVectorStorage(
            vector_db_path=vector_db_path,
            collection_name="user_documents",
            embedding_model=self.config.get(
                "document_index.embedding_model",
                "sentence-transformers/all-mpnet-base-v2",
            ),
        )
        logger.info(f"Document vector storage initialized at {vector_db_path}")

    def _initialize_index_db(self):
        """Set up SQLite database to track indexed files"""
        db_path = os.path.join(self.config.get_data_dir(), "document_index.db")
        self.index_db = db_path

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS indexed_files (
            path TEXT PRIMARY KEY,
            size INTEGER,
            modified_time REAL,
            indexed_time REAL,
            vector_id TEXT,
            file_type TEXT,
            chunks INTEGER
        )
        """
        )
        conn.commit()
        conn.close()
        logger.info(f"Document index database initialized at {db_path}")

    def _initialize_watcher(self):
        """Initialize the file system watcher"""
        watched_dirs = self.config.get(
            "document_index.directories",
            [
                os.path.expanduser("~/Documents"),
                os.path.expanduser("~/Downloads"),
            ],
        )

        file_extensions = self.config.get(
            "document_index.file_types",
            [
                ".pdf",
                ".docx",
                ".txt",
                ".md",
                ".pptx",
                ".xlsx",
                ".csv",
                ".json",
            ],
        )

        self.watcher = FileSystemWatcher(
            directories=watched_dirs,
            file_extensions=file_extensions,
            on_file_created=self.index_document,
            on_file_modified=self.index_document,
            on_file_deleted=self.remove_document,
            on_file_moved=self.handle_file_moved,
        )
        logger.info(
            f"File watcher initialized for {len(watched_dirs)} directories"
        )

    def start(self):
        """Start the document indexing system"""
        logger.info("Starting document indexing system")
        self.watcher.start()
        self.scan_directories()

    def stop(self):
        """Stop the document indexing system"""
        logger.info("Stopping document indexing system")
        self.watcher.stop()
        # Ensure everything is saved
        if hasattr(self.vector_storage, "close"):
            self.vector_storage.close()

    def scan_directories(self):
        """Scan all monitored directories to find changes since last run"""
        logger.info("Performing initial scan of monitored directories")

        # Get all files from the database
        conn = sqlite3.connect(self.index_db)
        cursor = conn.cursor()
        cursor.execute("SELECT path, size, modified_time FROM indexed_files")
        indexed_files = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        conn.close()

        # Scan directories for current files
        current_files = {}
        for directory in self.watcher.directories:
            for root, _, files in os.walk(directory):
                for file in files:
                    if any(
                        file.endswith(ext)
                        for ext in self.watcher.file_extensions
                    ):
                        path = os.path.join(root, file)
                        try:
                            stat = os.stat(path)
                            current_files[path] = (stat.st_size, stat.st_mtime)
                        except (FileNotFoundError, PermissionError):
                            continue

        # Identify changes
        new_files = [
            path for path in current_files if path not in indexed_files
        ]
        modified_files = [
            path
            for path in current_files
            if path in indexed_files
            and current_files[path] != indexed_files[path]
        ]
        deleted_files = [
            path for path in indexed_files if path not in current_files
        ]

        logger.info(
            f"Found {len(new_files)} new files, {len(modified_files)} modified"
            f" files, and {len(deleted_files)} deleted files"
        )

        # Process changes
        for path in new_files + modified_files:
            self.index_document(path)

        for path in deleted_files:
            self.remove_document(path)

    def index_document(self, path: str) -> bool:
        """
        Index a single document

        Args:
            path: Path to the document

        Returns:
            bool: True if indexing was successful, False otherwise
        """
        logger.info(f"Indexing document: {path}")
        try:
            # Get appropriate document loader
            loader = get_document_loader(path)
            if not loader:
                logger.warning(f"No suitable loader found for {path}")
                return False

            # Load and process the document
            documents = loader.load()

            # Get file stats
            stat = os.stat(path)
            file_type = os.path.splitext(path)[1]

            # Add to vector store with metadata
            vector_ids = []
            for i, doc in enumerate(documents):
                # Add metadata
                doc.metadata.update(
                    {
                        "source": path,
                        "file_type": file_type,
                        "last_modified": (
                            datetime.fromtimestamp(stat.st_mtime).isoformat()
                        ),
                        "chunk_index": i,
                        "total_chunks": len(documents),
                    }
                )

                # Add to vector store
                vector_id = self.vector_storage.add_text(
                    text=doc.page_content, metadata=doc.metadata
                )
                vector_ids.append(vector_id)

            # Update index database
            conn = sqlite3.connect(self.index_db)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO indexed_files VALUES (?, ?, ?, ?, ?,"
                " ?, ?)",
                (
                    path,
                    stat.st_size,
                    stat.st_mtime,
                    time.time(),
                    ",".join(vector_ids) if vector_ids else "",
                    file_type,
                    len(documents),
                ),
            )
            conn.commit()
            conn.close()

            logger.info(
                f"Successfully indexed {path} with {len(documents)} chunks"
            )
            return True

        except Exception as e:
            logger.error(f"Error indexing {path}: {e}", exc_info=True)
            return False

    def remove_document(self, path: str) -> bool:
        """
        Remove a document from the index

        Args:
            path: Path to the document

        Returns:
            bool: True if removal was successful, False otherwise
        """
        logger.info(f"Removing document from index: {path}")
        try:
            # Get vector IDs from database
            conn = sqlite3.connect(self.index_db)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT vector_id FROM indexed_files WHERE path = ?", (path,)
            )
            # result = cursor.fetchone()

            # if result and result[0]:
            #    vector_ids = result[0].split(",")
            # TODO: Implement removal from vector store when supported
            # Currently, Chroma doesn't have a clean API for removing specific documents

            # Remove from index database
            cursor.execute("DELETE FROM indexed_files WHERE path = ?", (path,))
            conn.commit()
            conn.close()

            logger.info(f"Successfully removed {path} from index")
            return True

        except Exception as e:
            logger.error(
                f"Error removing {path} from index: {e}", exc_info=True
            )
            return False

    def handle_file_moved(self, src_path: str, dest_path: str) -> bool:
        """
        Handle a file being moved

        Args:
            src_path: Original path
            dest_path: New path

        Returns:
            bool: True if handling was successful, False otherwise
        """
        logger.info(f"Handling moved file: {src_path} -> {dest_path}")
        self.remove_document(src_path)
        return self.index_document(dest_path)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for documents matching the query

        Args:
            query: Search query
            limit: Maximum number of results
            filters: Optional filters (file_type, recency, etc.)

        Returns:
            List of search results with document information
        """
        logger.info(f"Searching documents with query: {query}")

        # Perform vector search
        results = self.vector_storage.search(query, limit=limit)

        # Process results to make them more user-friendly
        processed_results = []
        for result in results:
            metadata = result.get("metadata", {})
            filepath = metadata.get("source", "Unknown source")
            filename = os.path.basename(filepath)
            content = result.get("content", "")

            processed_results.append(
                {
                    "filename": filename,
                    "filepath": filepath,
                    "content_snippet": (
                        content[:200] + "..."
                        if len(content) > 200
                        else content
                    ),
                    "last_modified": metadata.get("last_modified", "Unknown"),
                    "file_type": metadata.get("file_type", "Unknown"),
                    "chunk_index": metadata.get("chunk_index", 0),
                    "total_chunks": metadata.get("total_chunks", 1),
                }
            )

        logger.info(
            f"Found {len(processed_results)} results for query: {query}"
        )
        return processed_results
