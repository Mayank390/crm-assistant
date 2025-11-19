# Local Development Setup Guide

This guide explains how to configure the application to run locally without microservices (embedding service and SPLADE service). The codebase currently uses microservices by default, but includes commented code for local execution.

## Overview

The application uses two microservices in production:
- **Embedding Service**: Generates dense embeddings using SentenceTransformer models
- **SPLADE Service**: Generates sparse vectors for hybrid search

For local development, you can revert to using these libraries directly in-process.

## Files to Modify

> **Note**: The main application files are listed below. If you also need to run indexing scripts locally (e.g., `qdrant/insertdocs.py`), you'll need to make similar changes there to use `SentenceTransformer` instead of `EmbeddingServiceClient`.

### 1. `qdrant/initializer.py`

#### Step 1: Uncomment imports (lines 24-25)

Replace:
```python
from embedding.service_client import EmbeddingServiceClient, EmbeddingServiceError
# from sentence_transformers import SentenceTransformer
# from huggingface_hub import login
```

With:
```python
# from embedding.service_client import EmbeddingServiceClient, EmbeddingServiceError
from sentence_transformers import SentenceTransformer
from huggingface_hub import login
```

#### Step 2: Replace the `connect()` method (lines 64-87)

Comment out the current `connect()` method (lines 64-87) and uncomment the alternative implementation (lines 89-123).

**Current (microservice) version to comment out:**
```python
async def connect(self):
    # This method's internal logic remains the same
    if self.connected:
        return
    try:
        self.qdrant_client = QdrantClient(
            url=mongo.constants.QDRANT_URL,
            api_key=mongo.constants.QDRANT_API_KEY,
        )
        self.embedding_client = EmbeddingServiceClient(os.getenv("EMBEDDING_SERVICE_URL"))
        try:
            dimension = self.embedding_client.get_dimension()
        except EmbeddingServiceError as exc:
            raise RuntimeError(f"Failed to initialize embedding service: {exc}") from exc
        self.connected = True
        # ... rest of the method
```

**Local version to uncomment:**
```python
async def connect(self):
    # This method's internal logic remains the same
    if self.connected:
        return
    try:
        self.qdrant_client = QdrantClient(url=mongo.constants.QDRANT_URL, api_key=mongo.constants.QDRANT_API_KEY)
        
        # Authenticate with HuggingFace if token is available (required for gated models)
        hf_token = (
            os.getenv("HuggingFace_API_KEY")
        )
        if hf_token:
            try:
                login(token=hf_token, add_to_git_credential=False)
                print("✓ Authenticated with HuggingFace")
            except Exception as auth_exc:
                logger.warning(f"⚠ HuggingFace authentication failed: {auth_exc}")
        
        model_name = mongo.constants.EMBEDDING_MODEL
        try:
            self.embedding_client = SentenceTransformer(mongo.constants.EMBEDDING_MODEL)
        except Exception as e:
            print(f"⚠ Failed to load embedding model '{mongo.constants.EMBEDDING_MODEL}': {e}\nFalling back to 'sentence-transformers/all-MiniLM-L6-v2'")
        self.connected = True
        print(f"Successfully connected to Qdrant at {mongo.constants.QDRANT_URL}")
        # ... rest of the method
```

### 2. `qdrant/encoder.py`

#### Step 1: Comment out the microservice implementation (lines 1-41)

Comment out:
```python
from __future__ import annotations

"""SPLADE encoder client wrapper."""

from typing import Dict, List
import threading

from splade import SpladeServiceClient

# ... rest of the microservice implementation
```

#### Step 2: Uncomment the local implementation (lines 43-124)

Uncomment the entire block from line 43 to 124, which includes:
- The local SPLADE encoder using `transformers` and `torch`
- The `SpladeEncoder` class with direct model loading
- The `get_splade_encoder()` function

**Note:** There's a typo in the commented code - `_init_` should be `__init__` (line 66). Make sure to fix this when uncommenting.

## Required Dependencies

Add these to your `requirements.txt` or install them separately:

```bash
sentence-transformers>=2.2.0
torch>=2.0.0  # Required by transformers
```

The following are already in `requirements.txt`:
- `transformers==4.57.1`
- `huggingface-hub==0.36.0`

## Environment Variables

For local development, you'll need:

```bash
# Qdrant configuration
QDRANT_URL=http://localhost:6333  # or your Qdrant instance URL
QDRANT_API_KEY=your_api_key_if_needed

# Embedding model (optional, defaults to 'sentence-transformers/all-MiniLM-L6-v2')
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# HuggingFace authentication (required for gated models)
HuggingFace_API_KEY=your_hf_token_here

# MongoDB configuration
MONGODB_URI=your_mongodb_connection_string
MONGODB_DATABASE=ProjectManagement
```

## Important Notes

1. **Model Download**: The first time you run with local models, they will be downloaded from HuggingFace. This can take several minutes and requires internet connectivity.

2. **Memory Requirements**: Running models locally requires significant RAM:
   - SentenceTransformer models: ~500MB - 2GB depending on model
   - SPLADE model (`naver/splade-cocondenser-ensembledistil`): ~500MB - 1GB

3. **Performance**: Local execution may be slower than microservices, especially on CPU-only machines. Consider using GPU if available.

4. **API Compatibility**: The `EmbeddingServiceClient.encode()` method returns `List[List[float]]`, while `SentenceTransformer.encode()` returns numpy arrays by default. The code should work as-is since numpy arrays are iterable, but if you encounter type issues, you can convert the result:
   ```python
   # In search_content() and other methods using embedding_client.encode()
   query_vectors = self.embedding_client.encode([query])
   # If needed, convert numpy array to list:
   if hasattr(query_vectors, 'tolist'):
       query_vectors = query_vectors.tolist()
   ```
   Note: `SentenceTransformer.encode()` already returns a list-like structure that works with the existing code, but be aware of this difference.

5. **Typo Fix**: Fixed! The typo (`_init_` → `__init__`) in `encoder.py` line 66 has been corrected in the commented code.

## Additional Files That May Need Updates

If you're running indexing or other utility scripts locally:

- **`qdrant/insertdocs.py`**: This file also uses `EmbeddingServiceClient`. To run it locally, you'll need to:
  1. Comment out line 18: `from embedding.service_client import EmbeddingServiceClient, EmbeddingServiceError`
  2. Add: `from sentence_transformers import SentenceTransformer`
  3. Replace lines 57-60 to use `SentenceTransformer` directly instead of `EmbeddingServiceClient`
  4. Update any calls to `embedder.encode()` to work with `SentenceTransformer` API

## Docker Compose Considerations

If you're using `docker-compose.yml` and want to run without microservices:

1. Comment out or remove the `embedding` and `splade` services from `docker-compose.yml`
2. Remove the `depends_on` conditions for these services in the `backend` service
3. Remove the `EMBEDDING_SERVICE_URL` and `SPLADE_SERVICE_URL` environment variables from the backend service
4. Ensure the backend container has the necessary dependencies (`sentence-transformers`, `torch`, `transformers`) installed

## Reverting to Microservices

To switch back to microservices:
1. Reverse the changes above (comment local code, uncomment microservice code)
2. Ensure `EMBEDDING_SERVICE_URL` and `SPLADE_SERVICE_URL` environment variables are set
3. Make sure the microservices are running and accessible
4. Restore any changes made to `docker-compose.yml` if applicable

## Troubleshooting

- **Import errors**: Ensure all dependencies are installed (`pip install -r requirements.txt` and additional packages mentioned above)
- **Model loading failures**: Check your HuggingFace token and internet connectivity
- **Memory errors**: Try using a smaller model or increase system RAM
- **Qdrant connection errors**: Verify Qdrant is running and accessible at the configured URL

