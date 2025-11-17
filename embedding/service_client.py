"""
Embedding service client wrapper for SentenceTransformer.
Provides compatibility with the EmbeddingServiceClient interface.
"""

import os
import logging
from typing import List
from sentence_transformers import SentenceTransformer
from huggingface_hub import login
import mongo.constants

logger = logging.getLogger(__name__)


class EmbeddingServiceError(Exception):
    """Exception raised by embedding service operations."""
    pass


class EmbeddingServiceClient:
    """
    Wrapper around SentenceTransformer that provides the EmbeddingServiceClient interface.
    This allows the codebase to use SentenceTransformer directly without requiring
    an external embedding service.
    """
    
    def __init__(self, service_url: str = None):
        """
        Initialize the embedding client.
        
        Args:
            service_url: Ignored (kept for compatibility), uses SentenceTransformer instead
        """
        # Authenticate with HuggingFace if token is available (required for gated models)
        hf_token = os.getenv("HuggingFace_API_KEY")
        if hf_token:
            try:
                login(token=hf_token, add_to_git_credential=False)
                logger.info("✓ Authenticated with HuggingFace")
            except Exception as auth_exc:
                logger.warning(f"⚠ HuggingFace authentication failed: {auth_exc}")
        
        # Load the embedding model
        model_name = mongo.constants.EMBEDDING_MODEL or "sentence-transformers/all-mpnet-base-v2"
        try:
            self.model = SentenceTransformer(model_name)
            logger.info(f"✓ Loaded embedding model: {model_name}")
        except Exception as e:
            logger.warning(f"⚠ Failed to load embedding model '{model_name}': {e}")
            logger.info("Falling back to 'sentence-transformers/all-MiniLM-L6-v2'")
            self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        
        # Cache the dimension
        self._dimension = self.model.get_sentence_embedding_dimension()
    
    def get_dimension(self) -> int:
        """
        Get the dimension of the embedding vectors.
        
        Returns:
            The embedding dimension (e.g., 384, 768, etc.)
        """
        return self._dimension
    
    def encode(self, texts: List[str], **kwargs) -> List[List[float]]:
        """
        Encode a list of texts into embedding vectors.
        
        Args:
            texts: List of text strings to encode
            **kwargs: Additional arguments passed to SentenceTransformer.encode()
        
        Returns:
            List of embedding vectors (each vector is a list of floats)
        
        Raises:
            EmbeddingServiceError: If encoding fails
        """
        if not texts:
            return []
        
        try:
            # SentenceTransformer.encode() returns a numpy array
            embeddings = self.model.encode(texts, **kwargs)
            
            # Convert numpy array to list of lists
            if len(embeddings.shape) == 1:
                # Single text case
                return [embeddings.tolist()]
            else:
                # Multiple texts case
                return embeddings.tolist()
        except Exception as e:
            raise EmbeddingServiceError(f"Failed to encode texts: {e}") from e

