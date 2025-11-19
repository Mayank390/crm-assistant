from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, List, Sequence

import torch
import transformers
from huggingface_hub import login
from transformers import AutoModel, AutoTokenizer
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL_NAME = "google/embeddinggemma-300m"
logger = logging.getLogger(__name__)


def _resolve_token() -> str | None:
    """Return the first available Hugging Face token from known env vars."""
    for name in (
        "HF_TOKEN",
        "HF_API_TOKEN",
        "HF_HUB_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACEHUB_API_TOKEN",
        "HuggingFace_API_KEY",
    ):
        value = os.getenv(name)
        if value:
            return value
    return None


class EmbeddingEncoder:
    """Load a Hugging Face embedding model and expose a simple encode API."""

    def __init__(self, model_name: str | None = None, *, normalize: bool = False) -> None:
        name = model_name or os.getenv("EMBEDDING_MODEL_NAME") or DEFAULT_MODEL_NAME
        self.model_name = name
        self.normalize = normalize or os.getenv("EMBEDDING_NORMALIZE", "false").lower() in {
            "1",
            "true",
            "yes",
        }

        token = _resolve_token()
        if token:
            for env_name in (
                "HF_TOKEN",
                "HF_API_TOKEN",
                "HF_HUB_TOKEN",
                "HUGGING_FACE_HUB_TOKEN",
                "HUGGINGFACEHUB_API_TOKEN",
                "HuggingFace_API_KEY",
            ):
                os.environ.setdefault(env_name, token)
            try:
                login(token=token, add_to_git_credential=False)
            except TypeError:
                login(token)

        trust_remote = os.getenv("EMBEDDING_TRUST_REMOTE_CODE", "true").lower() not in {
            "0",
            "false",
            "no",
        }

        self.device = torch.device(os.getenv("EMBEDDING_DEVICE", "cpu"))
        try:
            requested_threads = int(os.getenv("EMBEDDING_NUM_THREADS", "0"))
        except ValueError:
            requested_threads = 0
        torch.set_num_threads(max(requested_threads, 1))

        backend_preference = os.getenv("EMBEDDING_BACKEND", "auto").lower()
        self.backend = "transformers"
        self.sentence_transformer: SentenceTransformer | None = None

        tokenizer_kwargs: dict[str, Any] = {
            "use_fast": True,
            "trust_remote_code": trust_remote,
        }
        tokenizer_revision = os.getenv("EMBEDDING_TOKENIZER_REVISION")
        if tokenizer_revision:
            tokenizer_kwargs["revision"] = tokenizer_revision

        if backend_preference in {"sentence-transformers", "auto"}:
            try:
                sentence_transformer_kwargs: dict[str, Any] = {
                    "trust_remote_code": trust_remote,
                    "device": str(self.device),
                }
                if tokenizer_revision:
                    sentence_transformer_kwargs["revision"] = tokenizer_revision
                self.sentence_transformer = SentenceTransformer(name, **sentence_transformer_kwargs)
                self.backend = "sentence-transformers"
                self.dimension = int(self.sentence_transformer.get_sentence_embedding_dimension())
                return
            except Exception as sentence_transformer_exc:
                logger.warning(
                    "SentenceTransformer backend initialisation failed for %s: %s",
                    name,
                    sentence_transformer_exc,
                )
                self.sentence_transformer = None
                if backend_preference == "sentence-transformers":
                    raise

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(name, **tokenizer_kwargs)
        except Exception as tokenizer_exc:
            if tokenizer_kwargs.get("use_fast", True):
                tokenizer_kwargs["use_fast"] = False
                self.tokenizer = AutoTokenizer.from_pretrained(name, **tokenizer_kwargs)
            else:
                raise RuntimeError(
                    f"Failed to load tokenizer for model '{name}': {tokenizer_exc}"
                ) from tokenizer_exc

        model_kwargs: dict[str, Any] = {
            "trust_remote_code": trust_remote,
            "torch_dtype": torch.float32,
            "low_cpu_mem_usage": True,
        }
        model_revision = os.getenv("EMBEDDING_MODEL_REVISION")
        if model_revision:
            model_kwargs["revision"] = model_revision
        attn_impl = os.getenv("EMBEDDING_ATTN_IMPLEMENTATION")
        if attn_impl:
            model_kwargs["attn_implementation"] = attn_impl

        try:
            self.model = AutoModel.from_pretrained(name, **model_kwargs)
        except ValueError as model_exc:
            message = str(model_exc)
            if "model type" in message and "not recognize" in message:
                raise RuntimeError(
                    "The installed transformers version "
                    f"({getattr(transformers, '__version__', 'unknown')}) "
                    f"does not support the model type required by '{name}'. "
                    "Upgrade transformers to >=4.57.1 (see embedding_service/requirements.txt)."
                ) from model_exc
            raise
        self.model.eval()
        self.model.to(self.device)

        try:
            probe = self.encode(["dimension probe"], normalize=False, batch_size=1)
        except Exception as exc:
            raise RuntimeError(f"Failed to warm up embedding model '{name}': {exc}") from exc
        if not probe or not probe[0]:
            raise RuntimeError("Failed to determine embedding dimension from model output")
        self.dimension = len(probe[0])

    def encode(
        self,
        texts: Sequence[str],
        *,
        normalize: bool | None = None,
        batch_size: int | None = None,
    ) -> List[List[float]]:
        if not texts:
            return []

        normalize_flag = self.normalize if normalize is None else normalize
        max_length = int(os.getenv("EMBEDDING_MAX_LENGTH", "512"))
        eff_batch_size = batch_size or int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))

        if self.backend == "sentence-transformers" and self.sentence_transformer is not None:
            embeddings = self.sentence_transformer.encode(
                list(texts),
                batch_size=eff_batch_size,
                normalize_embeddings=normalize_flag,
                convert_to_numpy=False,
            )
            return [embedding.tolist() if hasattr(embedding, "tolist") else list(embedding) for embedding in embeddings]

        outputs: List[List[float]] = []
        with torch.inference_mode():
            for start in range(0, len(texts), eff_batch_size):
                batch = texts[start : start + eff_batch_size]
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                encoded = {k: v.to(self.device) for k, v in encoded.items()}

                model_outputs = self.model(**encoded)

                embeddings = self._pool_embeddings(model_outputs, encoded["attention_mask"])

                if normalize_flag:
                    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

                outputs.extend(embeddings.cpu().float().tolist())

        return outputs

    def _pool_embeddings(self, outputs: Any, attention_mask: torch.Tensor) -> torch.Tensor:
        """Pool the raw model outputs into fixed-size sentence embeddings."""
        if hasattr(outputs, "sentence_embeddings"):
            return outputs.sentence_embeddings

        if hasattr(outputs, "pooler_output"):
            return outputs.pooler_output

        last_hidden_state = None
        if hasattr(outputs, "last_hidden_state"):
            last_hidden_state = outputs.last_hidden_state
        elif isinstance(outputs, (list, tuple)) and outputs:
            last_hidden_state = outputs[0]

        if last_hidden_state is None:
            raise RuntimeError("Model outputs do not contain embeddings or last hidden state")

        if attention_mask is None:
            return last_hidden_state[:, 0, :]

        mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        summed = torch.sum(last_hidden_state * mask, dim=1)
        counts = torch.clamp(mask.sum(dim=1), min=1e-9)
        return summed / counts


@lru_cache(maxsize=1)
def get_encoder() -> EmbeddingEncoder:
    return EmbeddingEncoder()
