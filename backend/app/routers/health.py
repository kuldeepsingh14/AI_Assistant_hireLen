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
    }
