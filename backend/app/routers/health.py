"""Liveness + capability probe."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..services.store import index

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "resume_indexed": index.ready,
        "chunks": len(index.chunks),
        "embedder": index.embedder,
        "llm_enabled": settings.llm_enabled,
        "model": settings.groq_model if settings.llm_enabled else None,
        # Not secret - a browser can discover these by trial - and being able to
        # read them back is the difference between "CORS is broken" and "the
        # value on the host has a typo".
        "allowed_origins": settings.origins,
        "allow_local_origins": settings.allow_local_origins,
    }
