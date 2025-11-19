from __future__ import annotations

"""SPLADE encoder client wrapper."""

from typing import Dict, List
import threading

from splade import SpladeServiceClient


_encoder_singleton_lock = threading.Lock()
_encoder_singleton: "SpladeEncoder | None" = None


class SpladeEncoder:
    """Adapter around the SPLADE service client with a familiar interface."""

    def __init__(self, *, max_terms: int = 200) -> None:
        self.client = SpladeServiceClient()
        self.max_terms = max_terms

    def encode_text(self, text: str, max_terms: int = 200) -> Dict[str, List[float]]:
        if not text or not text.strip():
            return {"indices": [], "values": []}

        effective_max_terms = max_terms or self.max_terms
        vectors = self.client.encode([text], max_terms=effective_max_terms)
        if not vectors:
            return {"indices": [], "values": []}
        return vectors[0]


def get_splade_encoder() -> SpladeEncoder:
    global _encoder_singleton
    if _encoder_singleton is not None:
        return _encoder_singleton
    with _encoder_singleton_lock:
        if _encoder_singleton is None:
            _encoder_singleton = SpladeEncoder()
        return _encoder_singleton

