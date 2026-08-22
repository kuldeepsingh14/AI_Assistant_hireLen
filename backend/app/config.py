"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESUME_DIR = DATA_DIR / "resume"
INDEX_DIR = DATA_DIR / "index"
# Committed starting content. Hosts with ephemeral disks (Render free tier)
# wipe DATA_DIR on every restart, so the profile is re-seeded from here.
SEED_DIR = DATA_DIR / "seed"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    # Free-tier token budgets are per model, so running the easy extraction step
    # on a smaller model keeps it off the main model's budget entirely.
    groq_model_fast: str = "openai/gpt-oss-20b"

    embedder: str = "auto"  # auto | fastembed | lexical
    allowed_origins: str = "http://localhost:4300,http://127.0.0.1:4300"
    # Allow any localhost port during development. IDE preview panes and
    # `ng serve --port 0` pick an ephemeral port that changes every session,
    # so pinning one in allowed_origins guarantees a CORS failure sooner or later.
    # Turn this off in production, where the origin is a known domain.
    allow_local_origins: bool = True
    admin_token: str = "change-me"
    # Left blank on purpose: the name is read from the resume. Set this only to
    # override what detection found.
    owner_name: str = ""
    owner_pronouns: str = "they/them"  # they/them | she/her | he/him

    # Retrieval tuning
    top_k: int = 6
    chunk_chars: int = 900
    chunk_overlap: int = 150

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def local_origin_regex(self) -> str | None:
        """Regex matching http(s)://localhost:<any port> and the 127.0.0.1 form."""
        if not self.allow_local_origins:
            return None
        return r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    for d in (DATA_DIR, RESUME_DIR, INDEX_DIR, SEED_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return Settings()
