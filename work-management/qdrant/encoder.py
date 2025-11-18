# from __future__ import annotations

# """SPLADE encoder client wrapper."""

# from typing import Dict, List
# import threading

# from splade import SpladeServiceClient


# _encoder_singleton_lock = threading.Lock()
# _encoder_singleton: "SpladeEncoder | None" = None


# class SpladeEncoder:
#     """Adapter around the SPLADE service client with a familiar interface."""

#     def __init__(self, *, max_terms: int = 200) -> None:
#         self.client = SpladeServiceClient()
#         self.max_terms = max_terms

#     def encode_text(self, text: str, max_terms: int = 200) -> Dict[str, List[float]]:
#         if not text or not text.strip():
#             return {"indices": [], "values": []}

#         effective_max_terms = max_terms or self.max_terms
#         vectors = self.client.encode([text], max_terms=effective_max_terms)
#         if not vectors:
#             return {"indices": [], "values": []}
#         return vectors[0]


# def get_splade_encoder() -> SpladeEncoder:
#     global _encoder_singleton
#     if _encoder_singleton is not None:
#         return _encoder_singleton
#     with _encoder_singleton_lock:
#         if _encoder_singleton is None:
#             _encoder_singleton = SpladeEncoder()
#         return _encoder_singleton


from __future__ import annotations

"""
Minimal SPLADE encoder utility.

Provides a lightweight, cached interface to compute sparse vectors
usable with Qdrant's sparse vectors API.

Dependencies: transformers, torch
Model: naver/splade-cocondenser-ensembledistil (masked LM head)
"""

from typing import Dict, List, Tuple
import threading


_encoder_singleton_lock = threading.Lock()
_encoder_singleton: "SpladeEncoder | None" = None


class SpladeEncoder:
    """SPLADE encoder producing sparse (indices, values) vectors."""

    def __init__(self, model_name: str = "naver/splade-cocondenser-ensembledistil") -> None:
        # Lazy imports keep startup fast when SPLADE isn't used
        from transformers import AutoTokenizer, AutoModelForMaskedLM  # type: ignore
        import torch  # type: ignore

        self.model_name = model_name
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForMaskedLM.from_pretrained(model_name)
        self.model.eval()
        self.torch = torch

    def encode_text(self, text: str, max_terms: int = 200) -> Dict[str, List[float]]:
        """Encode text to SPLADE sparse representation.

        Returns:
            {"indices": List[int], "values": List[float]}
        """
        if not text or not text.strip():
            return {"indices": [], "values": []}

        torch = self.torch
        # Tokenize and cap to model max length
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )

        with torch.no_grad():
            logits = self.model(**inputs).logits.squeeze(0)  # [seq_len, vocab]
            # SPLADE activation: log(1 + sum(ReLU(logits), dim=seq))
            activated = torch.relu(logits)
            aggregated = torch.log1p(torch.sum(activated, dim=0))  # [vocab]

        # Select top-k terms to keep vector compact
        k = min(max_terms, aggregated.numel())
        values, indices = torch.topk(aggregated, k)

        # Filter out zero or near-zero weights
        mask = values > 0
        values = values[mask]
        indices = indices[mask]

        # Convert to python lists
        indices_list = [int(i) for i in indices.tolist()]
        values_list = [float(v) for v in values.tolist()]

        return {"indices": indices_list, "values": values_list}


def get_splade_encoder() -> SpladeEncoder:
    global _encoder_singleton
    if _encoder_singleton is not None:
        return _encoder_singleton
    with _encoder_singleton_lock:
        if _encoder_singleton is None:
            _encoder_singleton = SpladeEncoder()
        return _encoder_singleton