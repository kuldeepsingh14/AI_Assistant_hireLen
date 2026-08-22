"""Job-description matching: paste or upload a JD, get a scored fit report."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from ..models.schemas import MatchRequest, MatchResponse
from ..services import analytics, jd_match
from ..services.extract import UnsupportedFile, extract_text
from ..services.llm import LLMUnavailable

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/match", tags=["match"])

MAX_BYTES = 2 * 1024 * 1024


async def _run(job_description: str, job_title: str | None, company: str | None) -> MatchResponse:
    try:
        report = await jd_match.match(job_description, job_title, company)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except LLMUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    analytics.log_match(report.job_title, report.company, report.score)
    return report


@router.post("", response_model=MatchResponse)
async def match_pasted(payload: MatchRequest) -> MatchResponse:
    return await _run(payload.job_description, payload.job_title, payload.company)


@router.post("/upload", response_model=MatchResponse)
async def match_uploaded(
    file: UploadFile = File(...),
    job_title: str | None = Form(default=None),
    company: str | None = Form(default=None),
) -> MatchResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is larger than {MAX_BYTES // (1024 * 1024)}MB.",
        )
    try:
        text = extract_text(file.filename or "jd", raw)
    except UnsupportedFile as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except Exception as exc:
        log.exception("JD extraction failed")
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not read that file: {exc}"
        ) from exc

    if len(text.strip()) < 30:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That file did not contain enough readable text to analyse.",
        )
    return await _run(text, job_title, company)
