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


import os
import logging
from typing import Dict, Any, List, Optional, Union

# LangChain imports
try:
    from langchain.vectorstores import Chroma
    from langchain.embeddings import HuggingFaceEmbeddings
    from langchain.schema import Document
    VECTOR_DB_AVAILABLE = True
except ImportError:
    VECTOR_DB_AVAILABLE = False

logger = logging.getLogger(__name__)


class LangChainVectorStorage:
    """LangChain Vector DB implementation for semantic search"""

    def __init__(
        self,
        vector_db_path: str = None,
        embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
        collection_name: str = "persona:default",
        **kwargs
    ):
        """
        Initialize LangChain vector storage

        Args:
            vector_db_path: Path to vector database
            embedding_model: Model to use for embeddings
            collection_name: Name of the collection
        """
        if not VECTOR_DB_AVAILABLE:
            raise ImportError(
                "Vector storage dependencies not installed. Run: pip install "
                "langchain chromadb sentence-transformers"
            )

        self.vector_db_path = vector_db_path

        # Create directory if it doesn't exist
        os.makedirs(vector_db_path, exist_ok=True)

        # Initialize embeddings
        self.embeddings = HuggingFaceEmbeddings(
            model_name=embedding_model
        )

        # Initialize Chroma vector store
        self.vector_db = Chroma(
            persist_directory=vector_db_path,
            embedding_function=self.embeddings,
            collection_name=collection_name
        )

        logger.info(f"Vector storage initialized at {vector_db_path} with collection {collection_name}")

    def add_text(self, text: str, metadata: Dict[str, Any]) -> str:
        """Add text to vector database"""
        ids = self.vector_db.add_texts(
            texts=[text],
            metadatas=[metadata]
        )

        # Persist to disk
        if hasattr(self.vector_db, "persist"):
            self.vector_db.persist()

        return ids[0] if ids else None

    def add_documents(self, documents: List[Document]) -> List[str]:
        """
        Add multiple documents to vector database

        Args:
            documents: List of LangChain Document objects

        Returns:
            List of document IDs
        """
        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        ids = self.vector_db.add_texts(
            texts=texts,
            metadatas=metadatas
        )

        # Persist to disk
        if hasattr(self.vector_db, "persist"):
            self.vector_db.persist()

        return ids

    def search(self, query: str, limit: int = 5, filter_dict: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Search for similar texts

        Args:
            query: Search query
            limit: Maximum number of results
            filter_dict: Optional metadata filters

        Returns:
            List of search results
        """
        results = self.vector_db.similarity_search(
            query,
            k=limit,
            filter=filter_dict
        )

        # Convert to standard format
        return [
            {
                "id": doc.metadata.get("message_id", doc.metadata.get("id", "unknown")),
                "timestamp": doc.metadata.get("timestamp", "unknown"),
                "role": doc.metadata.get("role", "unknown"),
                "content": doc.page_content,
                "metadata": doc.metadata,
                "similarity": "vector_match"
            }
            for doc in results
        ]

    def delete(self, ids: Union[str, List[str]]) -> None:
        """
        Delete documents by ID

        Args:
            ids: Single ID or list of IDs to delete
        """
        if isinstance(ids, str):
            ids = [ids]

        if hasattr(self.vector_db, "_collection"):
            self.vector_db._collection.delete(ids=ids)

            # Persist changes
            if hasattr(self.vector_db, "persist"):
                self.vector_db.persist()
        else:
            logger.warning("Delete operation not supported by this vector store implementation")

    def close(self):
        """Close vector database"""
        # Ensure everything is persisted
        if hasattr(self.vector_db, "persist"):
            self.vector_db.persist()