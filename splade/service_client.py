from __future__ import annotations

from typing import List, Dict, Sequence
import json
import os

import httpx


class SpladeServiceError(RuntimeError):
    """Raised when the SPLADE service returns an error response."""


class SpladeServiceClient:
    """Synchronous client for a SPLADE microservice.

    The microservice must expose a POST /encode endpoint that accepts:
        {"inputs": ["text a", "text b", ...], "max_terms": 200}

    and responds with:
        {"sparse_vectors": [{"indices": [...], "values": [...]}, ...]}
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        url = base_url or os.getenv("SPLADE_SERVICE_URL")
        if not url:
            raise ValueError("SPLADE service URL is not configured")

        self.base_url = url.rstrip("/")
        self.client = httpx.Client(timeout=timeout, headers=headers)

    def encode(
        self,
        texts: Sequence[str],
        max_terms: int = 200,
    ) -> List[Dict[str, List[float]]]:
        """Encode texts to SPLADE sparse vectors.

        Args:
            texts: List of text strings to encode
            max_terms: Maximum number of terms to keep in sparse vector

        Returns:
            List of dictionaries with "indices" and "values" keys
        """
        if not texts:
            return []

        payload = {"inputs": list(texts), "max_terms": max_terms}
        try:
            response = self.client.post(f"{self.base_url}/encode", json=payload)
        except Exception as exc:  # pragma: no cover - network failure guard
            raise SpladeServiceError(f"Failed to reach SPLADE service: {exc}") from exc

        if response.status_code >= 400:
            detail = _safe_extract_error(response)
            raise SpladeServiceError(
                f"SPLADE service returned {response.status_code}: {detail}"
            )

        data = response.json()
        vectors = data.get("sparse_vectors")
        if vectors is None:
            raise SpladeServiceError("SPLADE service response missing 'sparse_vectors'")

        # Convert to expected format: List[Dict[str, List[float]]]
        result = []
        for vec in vectors:
            if not isinstance(vec, dict):
                raise SpladeServiceError("Invalid vector format in response")
            indices = vec.get("indices", [])
            values = vec.get("values", [])
            result.append({
                "indices": [int(i) for i in indices],
                "values": [float(v) for v in values],
            })

        return result

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

