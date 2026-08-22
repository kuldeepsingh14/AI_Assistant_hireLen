"""CORS origin rules: convenient locally, closed everywhere else."""
from __future__ import annotations

import re

import pytest

from app.config import Settings


def _matches(settings: Settings, origin: str) -> bool:
    pattern = settings.local_origin_regex
    return bool(pattern) and re.fullmatch(pattern, origin) is not None


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:4300",
        "http://localhost:51463",  # VS Code preview picks a new port each session
        "http://127.0.0.1:8080",
        "http://localhost",
        "https://localhost:4300",
    ],
)
def test_any_localhost_port_allowed_in_dev(origin: str) -> None:
    assert _matches(Settings(allow_local_origins=True), origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example.com",
        "http://localhost.evil.com",       # suffix trick
        "http://notlocalhost:4300",
        "http://127.0.0.1.evil.com",
        "http://192.168.1.5:4300",         # LAN is not loopback
    ],
)
def test_external_origins_never_match(origin: str) -> None:
    assert not _matches(Settings(allow_local_origins=True), origin)


def test_disabled_in_production() -> None:
    settings = Settings(allow_local_origins=False)
    assert settings.local_origin_regex is None
    assert not _matches(settings, "http://localhost:4300")


def test_explicit_origins_still_parsed() -> None:
    settings = Settings(allowed_origins="https://a.com, https://b.com ,")
    assert settings.origins == ["https://a.com", "https://b.com"]


# ---------- allow_methods must cover every route ----------
def test_cors_allows_every_method_the_app_actually_uses() -> None:
    """Catch "added an endpoint, forgot CORS".

    A method missing from allow_methods passes every server-side test and fails
    only in a real browser, where it looks like the backend is unreachable.
    """
    from starlette.middleware.cors import CORSMiddleware

    from app.main import app

    configured = None
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            configured = {m.upper() for m in mw.kwargs["allow_methods"]}
    assert configured is not None, "CORSMiddleware is not installed"

    used = set()
    for route in app.routes:
        for method in getattr(route, "methods", set()) or set():
            if method not in ("HEAD", "OPTIONS"):
                used.add(method)

    missing = used - configured
    assert not missing, f"routes use {sorted(missing)} but CORS does not allow them"
