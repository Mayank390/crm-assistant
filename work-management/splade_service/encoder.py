from __future__ import annotations

from functools import lru_cache
from typing import Dict, List
import os

from transformers import AutoModelForMaskedLM, AutoTokenizer  # type: ignore
from huggingface_hub import login
import torch  # type: ignore


DEFAULT_MODEL_NAME = "naver/splade-cocondenser-ensembledistil"


class SpladeEncoder:
    """Local SPLADE encoder that produces sparse vectors."""

    def __init__(self, model_name: str | None = None) -> None:
        name = model_name or DEFAULT_MODEL_NAME
        self.model_name = name

        # Authenticate with Hugging Face if token is available
        hf_token = (
            os.getenv("HF_TOKEN")
            or os.getenv("HF_API_TOKEN")
            or os.getenv("HF_HUB_TOKEN")
            or os.getenv("HUGGING_FACE_HUB_TOKEN")
            or os.getenv("HUGGINGFACEHUB_API_TOKEN")
            or os.getenv("HuggingFace_API_KEY")
        )
        if hf_token:
            try:
                os.environ.setdefault("HF_TOKEN", hf_token)
                os.environ.setdefault("HF_API_TOKEN", hf_token)
                os.environ.setdefault("HF_HUB_TOKEN", hf_token)
                os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)
                os.environ.setdefault("HUGGINGFACEHUB_API_TOKEN", hf_token)
                try:
                    login(token=hf_token, add_to_git_credential=False)
                except TypeError:
                    login(hf_token)
            except Exception as e:
                print(f"Warning: Hugging Face login failed: {e}")

        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForMaskedLM.from_pretrained(name)
        self.model.eval()

    @torch.inference_mode()
    def encode(self, text: str, max_terms: int = 200) -> Dict[str, List[float]]:
        if not text or not text.strip():
            return {"indices": [], "values": []}

        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )

        logits = self.model(**inputs).logits.squeeze(0)
        activated = torch.relu(logits)
        aggregated = torch.log1p(torch.sum(activated, dim=0))

        k = min(max_terms, aggregated.numel())
        values, indices = torch.topk(aggregated, k)

        mask = values > 0
        values = values[mask]
        indices = indices[mask]

        return {
            "indices": [int(i) for i in indices.tolist()],
            "values": [float(v) for v in values.tolist()],
        }


@lru_cache(maxsize=1)
def get_encoder() -> SpladeEncoder:
    model_name = os.getenv("SPLADE_MODEL_NAME", DEFAULT_MODEL_NAME)
    return SpladeEncoder(model_name=model_name)
