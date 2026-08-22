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
