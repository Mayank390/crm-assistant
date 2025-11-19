from __future__ import annotations

from typing import List, Optional
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from encoder import get_encoder


MAX_TERMS_DEFAULT = int(os.getenv("SPLADE_MAX_TERMS", "200"))


class EncodeRequest(BaseModel):
    inputs: List[str] = Field(default_factory=list)
    max_terms: Optional[int] = None


class EncodeResponse(BaseModel):
    sparse_vectors: List[dict[str, List[float]]]


app = FastAPI(title="SPLADE Service", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    # Ensure encoder is loaded and ready
    try:
        encoder = get_encoder()
        # Verify the model is actually loaded
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service not ready: {e}")


@app.post("/encode", response_model=EncodeResponse)
async def encode(request: EncodeRequest) -> EncodeResponse:
    encoder = get_encoder()
    if not request.inputs:
        return EncodeResponse(sparse_vectors=[])

    max_terms = request.max_terms or MAX_TERMS_DEFAULT
    if max_terms <= 0:
        raise HTTPException(status_code=400, detail="max_terms must be > 0")

    vectors = [encoder.encode(text, max_terms=max_terms) for text in request.inputs]
    return EncodeResponse(sparse_vectors=vectors)


def create_app() -> FastAPI:
    return app
