from __future__ import annotations

from typing import List, Sequence
import json
import os

import httpx


class EmbeddingServiceError(RuntimeError):
    """Raised when the embedding service returns an error response."""


class EmbeddingServiceClient:
    """Synchronous client for an embedding microservice.

    The microservice must expose a POST /embed endpoint that accepts:
        {"inputs": ["text a", "text b", ...]}

    and responds with:
        {"embeddings": [[...], [...], ...]}
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        url = base_url or os.getenv("EMBEDDING_SERVICE_URL")
        if not url:
            raise ValueError("Embedding service URL is not configured")

        self.base_url = url.rstrip("/")
        self.client = httpx.Client(timeout=timeout, headers=headers)

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []

        payload = {"inputs": list(texts)}
        try:
            response = self.client.post(f"{self.base_url}/embed", json=payload)
        except Exception as exc:  # pragma: no cover - network failure guard
            raise EmbeddingServiceError(f"Failed to reach embedding service: {exc}") from exc

        if response.status_code >= 400:
            detail = _safe_extract_error(response)
            raise EmbeddingServiceError(
                f"Embedding service returned {response.status_code}: {detail}"
            )

        data = response.json()
        embeddings = data.get("embeddings") or data.get("data")
        if embeddings is None:
            raise EmbeddingServiceError("Embedding service response missing 'embeddings'")

        return [
            [float(value) for value in vector]
            for vector in embeddings
        ]

    def get_dimension(self) -> int:
        """Infer embedding dimensionality by encoding a dummy string."""
        vectors = self.encode(["dimension probe"])
        if not vectors or not vectors[0]:
            raise EmbeddingServiceError("Embedding service returned empty vector")
        return len(vectors[0])

    def close(self) -> None:
        self.client.close()


def _safe_extract_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            return data.get("error") or data.get("detail") or json.dumps(data)
    except Exception:
        pass
    return response.text
