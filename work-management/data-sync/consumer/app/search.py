import argparse
import os
from typing import Dict

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from embedding.service_client import EmbeddingServiceClient, EmbeddingServiceError

from qdrant.encoder import get_splade_encoder


def _load_embedder() -> EmbeddingServiceClient:
    try:
        return EmbeddingServiceClient(os.getenv("EMBEDDING_SERVICE_URL"))
    except ValueError as exc:
        raise RuntimeError("EMBEDDING_SERVICE_URL must be set to use embedding search") from exc


EMBEDDER = _load_embedder()
SPLADE_ENCODER = get_splade_encoder()

def build_query_vector(text: str) -> Dict[str, qmodels.NamedVectorStruct]:
    vectors = EMBEDDER.encode([text])
    if not vectors:
        raise EmbeddingServiceError("Embedding service returned empty embedding")
    dense_vector = vectors[0]
    sparse_raw = SPLADE_ENCODER.encode_text(text)
    query: Dict[str, qmodels.NamedVectorStruct] = {
        "dense": qmodels.NamedVectorStruct(name="dense", vector=dense_vector)
    }
    if sparse_raw.get("indices"):
        query["sparse"] = qmodels.NamedSparseVectorStruct(
            name="sparse",
            vector=qmodels.SparseVector(indices=sparse_raw["indices"], values=sparse_raw["values"]),
        )
    return query


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid search against Qdrant")
    parser.add_argument("--query", required=True, help="Query text")
    parser.add_argument("--limit", type=int, default=5, help="Number of results")
    args = parser.parse_args()

    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    collection = os.getenv("QDRANT_COLLECTION", "ProjectManagement")

    client = QdrantClient(url=qdrant_url)

    query_vectors = build_query_vector(args.query)
    named_vectors = list(query_vectors.values())

    result = client.search(
        collection_name=collection,
        query_vector=named_vectors,
        limit=args.limit,
        with_payload=True,
    )

if __name__ == "__main__":
    main()
