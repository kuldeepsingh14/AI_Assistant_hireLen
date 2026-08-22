"""Recruiter contact capture.

Public on write, owner-only on read: a recruiter can leave their details, but
only the owner can see who has been asking.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, status

from ..models.schemas import LeadPayload
from ..services import analytics

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/leads", tags=["leads"])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
# Digits, spaces, and the usual separators. Deliberately loose - phone formats
# vary by country and rejecting a valid number costs a lead.
_PHONE = re.compile(r"^[+()\d][\d\s().-]{5,}$")


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(payload: LeadPayload) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please enter a name.")

    email = _clean(payload.email)
    phone = _clean(payload.phone)

    if email and not _EMAIL.match(email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That email doesn't look right.")
    if phone and not _PHONE.match(phone):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That phone number doesn't look right."
        )
    if not email and not phone:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Add an email or a phone number so they can reach you back.",
        )

    lead_id = analytics.save_lead(
        session_id=payload.session_id or "unknown",
        name=name,
        company=_clean(payload.company),
        email=email,
        phone=phone,
        role=_clean(payload.role),
        note=_clean(payload.note),
    )
    log.info("New lead #%s from %s", lead_id, payload.company or name)
    return {"ok": True, "id": lead_id}
