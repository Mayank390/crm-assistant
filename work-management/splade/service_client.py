from __future__ import annotations

from typing import List, Sequence
import json
import os

import httpx


class SpladeServiceError(RuntimeError):
    """Raised when the SPLADE service returns an error response."""


class SpladeServiceClient:
    """Client for the SPLADE encoding microservice."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        url = base_url or os.getenv("SPLADE_SERVICE_URL")
        if not url:
            raise ValueError("SPLADE service URL is not configured (SPLADE_SERVICE_URL)")

        self.base_url = url.rstrip("/")
        self.client = httpx.Client(timeout=timeout, headers=headers)

    def encode(
        self,
        texts: Sequence[str],
        *,
        max_terms: int | None = None,
    ) -> List[dict[str, List[float]]]:
        """Encode a batch of texts to sparse vectors."""
        if not texts:
            return []

        payload: dict[str, object] = {"inputs": list(texts)}
        if max_terms is not None:
            payload["max_terms"] = int(max_terms)

        try:
            response = self.client.post(f"{self.base_url}/encode", json=payload)
        except Exception as exc:  # pragma: no cover - network failure guard
            raise SpladeServiceError(f"Failed to reach SPLADE service: {exc}") from exc

        if response.status_code >= 400:
            raise SpladeServiceError(
                f"SPLADE service returned {response.status_code}: {self._safe_extract_error(response)}"
            )

        data = response.json()
        vectors = data.get("sparse_vectors")
        if not isinstance(vectors, list):
            raise SpladeServiceError("SPLADE service response missing 'sparse_vectors'")

        return [
            {
                "indices": [int(i) for i in (vector.get("indices") or [])],
                "values": [float(v) for v in (vector.get("values") or [])],
            }
            for vector in vectors
        ]

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _safe_extract_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                return data.get("error") or data.get("detail") or json.dumps(data)
        except Exception:
            pass
        return response.text
