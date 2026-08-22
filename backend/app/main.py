"""HireLens - a portfolio AI assistant that also screens itself against a job description."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import admin, chat, health, leads, match, profile
from .services import analytics, seed
from .services.store import index

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
log = logging.getLogger("hirelens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    analytics.init()
    if index.load():
        log.info("Resume index restored: %s (%d chunks)", index.filename, len(index.chunks))
    elif seed.load_if_empty():
        # Ephemeral-disk hosts land here after every restart.
        log.info("Profile seeded from backend/data/seed/")
    else:
        log.info("No resume indexed yet. Upload one via POST /api/profile/upload.")
    if not settings.llm_enabled:
        log.warning("GROQ_API_KEY is not set - chat and matching will return 503 until it is.")
    yield


settings = get_settings()

app = FastAPI(
    title="HireLens API",
    description=(
        "A resume-grounded AI assistant with two personas (portfolio visitor and HR "
        "screener) plus job-description fit scoring."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_origin_regex=settings.local_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)

app.include_router(health.router)
app.include_router(profile.router)
app.include_router(chat.router)
app.include_router(match.router)
app.include_router(leads.router)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"name": "HireLens API", "docs": "/docs", "health": "/api/health"}
