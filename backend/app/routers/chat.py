"""Chat endpoints: the visitor/HR assistant and the one-click screening pack."""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from ..models.schemas import (
    ChatRequest,
    ChatResponse,
    ScreeningAnswer,
    ScreeningPackResponse,
)
from ..services import analytics, chat as chat_service
from ..services.llm import LLMUnavailable
from ..services.store import index

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def ask(payload: ChatRequest) -> ChatResponse:
    session_id = payload.session_id or uuid.uuid4().hex[:12]
    try:
        answer, citations, grounded = await chat_service.answer(
            payload.message, payload.mode, payload.history
        )
    except LLMUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    analytics.log_question(session_id, payload.mode, payload.message, grounded)

    return ChatResponse(
        answer=answer,
        citations=citations,
        grounded=grounded,
        mode=payload.mode,
        session_id=session_id,
        suggestions=chat_service.suggestions(payload.mode),
    )


@router.get("/suggestions", response_model=list[str])
async def get_suggestions(mode: str = "visitor") -> list[str]:
    return chat_service.suggestions("hr" if mode == "hr" else "visitor")


@router.post("/screening-pack", response_model=ScreeningPackResponse)
async def screening_pack() -> ScreeningPackResponse:
    """Answer the standard first-round screening questions in one shot."""
    if not index.ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Upload a resume before generating the screening pack."
        )

    questions = chat_service.SCREENING_QUESTIONS

    async def one(question: str) -> ScreeningAnswer:
        text, citations, _ = await chat_service.answer(question, "hr", [])
        return ScreeningAnswer(question=question, answer=text, citations=citations)

    # Sequential on purpose: the Groq free tier rate-limits parallel bursts, and a
    # half-failed pack is worse than one that takes a few extra seconds.
    answers: list[ScreeningAnswer] = []
    try:
        for question in questions:
            answers.append(await one(question))
            await asyncio.sleep(0.2)
    except LLMUnavailable as exc:
        if not answers:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        log.warning("Screening pack stopped early: %s", exc)

    return ScreeningPackResponse(owner_name=index.owner_name, answers=answers)
