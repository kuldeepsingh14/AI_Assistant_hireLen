"""Resume upload, status, and reset."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from ..config import RESUME_DIR, get_settings
from ..deps import require_owner
from ..models.schemas import IngestResponse, NotesPayload, ProfileStatus
from ..services.extract import SUPPORTED, UnsupportedFile, extract_text, safe_filename
from ..services.store import index

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profile", tags=["profile"])

MAX_BYTES = 5 * 1024 * 1024  # a resume that isn't a few hundred KB is not a resume

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


@router.get("", response_model=ProfileStatus)
async def get_status() -> ProfileStatus:
    settings = get_settings()
    return ProfileStatus(
        ready=index.ready,
        filename=index.filename,
        chunks=len(index.chunks),
        sections=index.sections,
        note_sections=index.note_sections,
        has_notes=bool(index.notes),
        resume_downloadable=_resume_file() is not None,
        embedder=index.embedder,
        llm_enabled=settings.llm_enabled,
        owner_name=index.owner_name,
        indexed_at=index.indexed_at,
    )


def _resume_file() -> Path | None:
    """The archived original, if it survived (Render's free disk is ephemeral)."""
    if not index.filename:
        return None
    path = RESUME_DIR / index.filename
    return path if path.is_file() else None


@router.get("/resume")
async def download_resume() -> FileResponse:
    """Serve the original resume file.

    Deliberately public: the whole point is that a recruiter who likes what the
    assistant said can take the actual document away with them.
    """
    path = _resume_file()
    if path is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "The original resume file is not available for download on this server.",
        )
    # A safe download name: the owner's name, keeping the original extension.
    suffix = path.suffix or ".pdf"
    stem = re.sub(r"[^A-Za-z0-9]+", "-", index.owner_name).strip("-") or "resume"
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(suffix.lower(), "application/octet-stream"),
        filename=f"{stem}-resume{suffix}",
    )


@router.get("/notes", response_model=NotesPayload, dependencies=[Depends(require_owner)])
async def get_notes() -> NotesPayload:
    return NotesPayload(notes=index.notes)


@router.put("/notes", response_model=ProfileStatus, dependencies=[Depends(require_owner)])
async def put_notes(payload: NotesPayload) -> ProfileStatus:
    if not index.ready and not payload.notes.strip():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Upload a resume before adding context notes."
        )
    index.set_notes(payload.notes)
    return await get_status()


@router.post("/upload", response_model=IngestResponse, dependencies=[Depends(require_owner)])
async def upload_resume(file: UploadFile = File(...)) -> IngestResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is larger than {MAX_BYTES // (1024 * 1024)}MB.",
        )

    # Sanitized before it is ever joined onto a path - see safe_filename.
    filename = safe_filename(file.filename or "resume")
    try:
        text = extract_text(filename, raw)
    except UnsupportedFile as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except Exception as exc:
        log.exception("Resume extraction failed")
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not read that file: {exc}"
        ) from exc

    if len(text) < 200:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only a few characters of text came out of that file. If it is a scanned "
            f"or image-based PDF, upload a text-based export instead ({', '.join(sorted(SUPPORTED))}).",
        )

    try:
        index.build(text, filename)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Keep the original so the owner can re-index after changing chunking settings.
    try:
        (RESUME_DIR / filename).write_bytes(raw)
    except OSError as exc:
        log.warning("Could not archive the uploaded resume: %s", exc)

    return IngestResponse(
        filename=filename,
        characters=len(text),
        chunks=len(index.chunks),
        sections=index.sections,
        embedder=index.embedder,
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,  # 204 must not carry a JSON body
    dependencies=[Depends(require_owner)],
)
async def reset_profile() -> Response:
    index.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
