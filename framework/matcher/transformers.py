import logging
from typing import Dict, List, Optional

import numpy as np
import re
import torch
# import pprint
from typing import Any
from transformers import AutoModel, AutoTokenizer

from .base import OrakleMatcherBase

logger = logging.getLogger(__name__)


class OrakleMatcherTransformers(OrakleMatcherBase):
    """
    Advanced matching system using transformer models for semantic
    understanding and intelligent skill matching.
    """

    def __init__(
        self, model_name: str = "sentence-transformers/all-mpnet-base-v2"
    ):
        """
        Initialize the matcher with a specified transformer model.

        Args:
            model_name: The name of the transformer model to use
        """
        super().__init__()
        self.embeddings_cache = {}

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModel.from_pretrained(model_name)
            if torch.cuda.is_available():
                self.model = self.model.cuda()
            self.model.eval()
            logger.info(
                "Initialized OrakleMatcherTransformers with model:"
                f" {model_name}"
            )
        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {e}")
            raise

    def register_skill(
        self, skill_id: str, description: str, metadata: Optional[Dict] = None
    ):
        """
        Register a new skill with enhanced domain context from its module path.

        Args:
            skill_id: Unique identifier for the skill
            description: Natural language description of the skill
            metadata: Additional skill metadata
        """
        # Extract domain context from module path
        domain_parts = skill_id.replace('/', ' ').replace('_', ' ').split()
        domain_context = (" ".join(domain_parts) + " ") * 2
        # Extract boost keywords if present using **keyword** markup (bold in markdown)
        boost_pattern = r'\*\*(.*?)\*\*'
        boost_keywords = re.findall(boost_pattern, description)
        boost_text = ""
        if boost_keywords:
            boost_text = " ".join((" " + kw) * 6 for kw in boost_keywords) + " "
        # Clean description by removing ** markers
        clean_description = re.sub(boost_pattern, r'\1', description)
        # Combine domain context with description for better semantic matching
        enhanced_description = f"{domain_context}: {boost_text}{clean_description}"

        # logger.info(f"ENHANCED_DESCRIPTION: {enhanced_description}")

        self.skills_registry[skill_id] = {
            "description": enhanced_description,
            "metadata": metadata or {},
            "boost_keywords": boost_keywords,
            "embedding": self._get_embedding(enhanced_description),
        }
        logger.debug(f"Registered skill: {skill_id}")

    def _get_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for text using the transformer model.

        Args:
            text: Input text to embed

        Returns:
            Numpy array containing the text embedding
        """
        if text in self.embeddings_cache:
            return self.embeddings_cache[text]

        # Tokenize and prepare input
        inputs = self.tokenizer(
            text,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        if torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        # Generate embedding
        with torch.no_grad():
            outputs = self.model(**inputs)
            # Use mean pooling of last hidden state
            embedding = outputs.last_hidden_state.mean(dim=1)

        embedding_np = embedding.cpu().numpy()
        self.embeddings_cache[text] = embedding_np
        return embedding_np

    def _calculate_similarity(
        self, query_embedding: np.ndarray, skill_embedding: np.ndarray
    ) -> float:
        """
        Calculate cosine similarity between query and skill embeddings
        """
        return float(
            np.dot(query_embedding, skill_embedding.T)
            / (
                np.linalg.norm(query_embedding)
                * np.linalg.norm(skill_embedding)
            )
        )

    def match(
        self, query: str, threshold: float = 0.1, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find the best matching skills for a given query.

        Args:
            query: The user's query text
            threshold: Minimum similarity score threshold
            top_k: Maximum number of matches to return

        Returns:
            List of matching skills with scores
        """
        query_embedding = self._get_embedding(query)
        matches = []

        logger.info("MATCH query:" + query)
        logger.info("MATCH threshold:" + str(threshold))
        logger.info("MATCH top_k:" + str(top_k))

        for skill_id, skill_data in self.skills_registry.items():
            similarity = self._calculate_similarity(
                query_embedding, skill_data["embedding"]
            )

            if similarity >= threshold:
                matches.append(
                    {
                        "skill_id": skill_id,
                        "score": similarity,
                        "usage_count": self.usage_stats[skill_id],
                        "description": skill_data["description"],
                    }
                )

        # Sort by score and usage count
        matches.sort(
            key=lambda x: (x["score"], x["usage_count"]), reverse=True
        )

        # logger.info("MATCH MATCHES: " + pprint.pformat(matches))
        return matches[:top_k]
