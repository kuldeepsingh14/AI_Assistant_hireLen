"""Shared route dependencies."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


async def require_owner(x_admin_token: str = Header(default="")) -> None:
    """Guard owner-only routes (uploading the resume, reading analytics).

    Without this, any visitor to a public portfolio could replace the resume the
    assistant answers from.
    """
    settings = get_settings()
    expected = settings.admin_token.strip()
    if not expected or expected == "change-me":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Owner actions are locked. Set ADMIN_TOKEN in backend/.env to something private.",
        )
    # compare_digest keeps the check constant-time against token guessing.
    if not hmac.compare_digest(x_admin_token.strip(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin token.")
