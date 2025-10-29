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
import uuid
from typing import Any, Dict, List, Optional

from .vector_base import VectorStorageBackend

from ainara.framework.config import config

try:
    import chromadb
    from sentence_transformers import SentenceTransformer

    VECTOR_DB_AVAILABLE = True
except ImportError:
    VECTOR_DB_AVAILABLE = False

logger = logging.getLogger(__name__)


class ChromaVectorStorage(VectorStorageBackend):
    """Direct ChromaDB implementation for semantic search"""

    def __init__(
        self,
        vector_db_path: str = None,
        embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
        collection_name: str = "persona-default",
        **kwargs,
    ):
        """
        Initialize ChromaDB vector storage

        Args:
            vector_db_path: Path to vector database
            embedding_model: Model to use for embeddings
            collection_name: Name of the collection
        """
        if not VECTOR_DB_AVAILABLE:
            raise ImportError(
                "Vector storage dependencies not installed. Run: pip install"
                " chromadb sentence-transformers"
            )

        self.vector_db_path = vector_db_path
        os.makedirs(vector_db_path, exist_ok=True)

        self.collection_name = collection_name

        # Initialize embeddings
        self.embedding_model = SentenceTransformer(
            embedding_model,
            cache_folder=config.get("cache.directory")
        )

        # Initialize ChromaDB client and collection
        self.client = chromadb.PersistentClient(
            path=vector_db_path,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name
        )

        logger.info(
            f"Vector storage initialized at {vector_db_path} with collection"
            f" {collection_name}"
        )

    def add_text(self, text: str, metadata: Dict[str, Any]) -> str:
        """Add a single text to vector database"""
        doc = {"page_content": text, "metadata": metadata}
        ids = self.add_documents([doc])
        return ids[0] if ids else None

    def add_documents(self, documents: List[Dict[str, Any]]) -> List[str]:
        """
        Add multiple documents to vector database

        Args:
            documents: List of document dictionaries, each with 'page_content' and 'metadata'

        Returns:
            List of document IDs
        """
        if not documents:
            return []

        texts = [doc["page_content"] for doc in documents]
        metadatas = [doc["metadata"] for doc in documents]
        # ChromaDB requires string IDs
        ids = [meta.get("id", str(uuid.uuid4())) for meta in metadatas]

        # ChromaDB can't handle non-primitive types in metadata, so we stringify complex values
        for meta in metadatas:
            for key, value in meta.items():
                if not isinstance(value, (str, int, float, bool)):
                    meta[key] = str(value)

        self.collection.add(
            embeddings=self.embedding_model.encode(texts).tolist(),
            documents=texts,
            metadatas=metadatas,
            ids=ids,
        )

        return ids

    def search(
        self,
        query: str,
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar texts

        Args:
            query: Search query
            limit: Maximum number of results
            filter_dict: Optional metadata filters for ChromaDB's 'where' clause

        Returns:
            List of search results
        """
        query_embedding = self.embedding_model.encode([query]).tolist()

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=limit,
            where=filter_dict if filter_dict else None,
        )

        # Convert to standard format
        formatted_results = []
        # The result structure from chromadb is a dict of lists
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i]
                formatted_results.append(
                    {
                        "id": doc_id,
                        "timestamp": metadata.get("timestamp", "unknown"),
                        "role": metadata.get("role", "unknown"),
                        "content": results["documents"][0][i],
                        "metadata": metadata,
                        "similarity": (
                            1 - (results["distances"][0][i] / 2)
                        ),  # Convert squared L2 distance to cosine similarity
                    }
                )
        return formatted_results

    def search_with_scores(
        self,
        query: str,
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[tuple[Dict[str, Any], float]]:
        """
        Search for similar texts and return documents with their distance scores.

        Args:
            query: Search query
            limit: Maximum number of results
            filter_dict: Optional metadata filters for ChromaDB's 'where' clause

        Returns:
            List of tuples, where each tuple contains a result dictionary and its distance score.
        """
        query_embedding = self.embedding_model.encode([query]).tolist()

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=limit,
            where=filter_dict if filter_dict else None,
        )

        # Convert to standard format
        formatted_results_with_scores = []
        # The result structure from chromadb is a dict of lists
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i]
                distance = results["distances"][0][i]
                result_doc = {"metadata": metadata}
                formatted_results_with_scores.append((result_doc, distance))
        return formatted_results_with_scores

    def delete(self, ids: List[str]) -> None:
        """
        Delete documents by ID

        Args:
            ids: List of IDs to delete
        """
        if not ids:
            return
        self.collection.delete(ids=ids)

    def reset(self) -> None:
        """Delete and recreate the collection."""
        logger.info(f"Resetting Chroma collection: {self.collection_name}")
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name
        )
        logger.info(f"Collection {self.collection_name} has been reset.")

    def count(self) -> int:
        """Returns the total number of documents in the collection."""
        return self.collection.count()

    def close(self):
        """Close vector database"""
        # The PersistentClient in ChromaDB handles persistence automatically.
        # No explicit close or persist method is typically needed.
        pass
