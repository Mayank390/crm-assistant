from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from encoder import get_encoder


class EmbedRequest(BaseModel):
    inputs: List[str] = Field(default_factory=list)
    normalize: Optional[bool] = None


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]


app = FastAPI(title="Embedding Service", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    # Ensure encoder is loaded and ready
    try:
        encoder = get_encoder()
        # Verify the model is actually loaded by checking dimension
        _ = encoder.dimension
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service not ready: {e}")


@app.get("/dimension")
async def dimension() -> dict[str, int]:
    encoder = get_encoder()
    return {"dimension": encoder.dimension}


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest) -> EmbedResponse:
    encoder = get_encoder()
    if not request.inputs:
        return EmbedResponse(embeddings=[])

    try:
        vectors = encoder.encode(request.inputs, normalize=request.normalize)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to compute embeddings: {exc}") from exc
    if any(not isinstance(vec, list) for vec in vectors):
        raise HTTPException(status_code=500, detail="Invalid embedding output format")
    return EmbedResponse(embeddings=vectors)


def create_app() -> FastAPI:
    return app
