"""The resume index: chunks + BM25 + optional vectors, persisted to disk.

Small enough to live in memory (a resume is a few KB), so there is no vector DB
and nothing to pay for. It reloads itself on boot so a restart keeps the profile.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from ..config import INDEX_DIR, get_settings
from . import embed
from .bm25 import BM25
from .chunk import Chunk, chunk_notes, chunk_resume
from .expand import expand
from .identity import extract_name, resolve_owner_name

log = logging.getLogger(__name__)

META_PATH = INDEX_DIR / "index.json"
VECTOR_PATH = INDEX_DIR / "vectors.npy"
TEXT_PATH = INDEX_DIR / "resume.txt"
NOTES_PATH = INDEX_DIR / "notes.txt"


@dataclass
class Hit:
    chunk: Chunk
    score: float


@dataclass
class ResumeIndex:
    chunks: list[Chunk] = field(default_factory=list)
    filename: str | None = None
    full_text: str = ""
    indexed_at: str | None = None
    embedder: str = "lexical:bm25"
    detected_name: str | None = None
    notes: str = ""
    _bm25: BM25 | None = None
    _vectors: np.ndarray | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------- lifecycle ----------
    @property
    def ready(self) -> bool:
        return bool(self.chunks)

    @property
    def owner_name(self) -> str:
        """The name to show, preferring the resume over the configured override."""
        return resolve_owner_name(get_settings().owner_name, self.detected_name)

    @property
    def sections(self) -> list[str]:
        seen: list[str] = []
        for c in self.chunks:
            if c.section not in seen:
                seen.append(c.section)
        return seen

    @property
    def note_sections(self) -> list[str]:
        seen: list[str] = []
        for c in self.chunks:
            if c.source == "notes" and c.section not in seen:
                seen.append(c.section)
        return seen

    def build(self, text: str, filename: str) -> None:
        """Index a new resume, keeping any notes the owner has already written."""
        with self._lock:
            probe = chunk_resume(text, get_settings().chunk_chars, get_settings().chunk_overlap)
            if not probe:
                raise ValueError(
                    "No readable text found in that file. If it is a scanned/image PDF, "
                    "export a text-based PDF or upload a .docx/.txt instead."
                )
            self.filename = filename
            self.full_text = text
            self.detected_name = extract_name(text)
            self._reindex()
        log.info(
            "Indexed %s for %s: %d chunks via %s",
            filename,
            self.detected_name or "(name not detected)",
            len(self.chunks),
            self.embedder,
        )

    def set_notes(self, notes: str) -> None:
        """Replace the owner's free-form context notes and re-index."""
        with self._lock:
            self.notes = notes.strip()
            self._reindex()
        log.info("Notes updated: %d chars, %d chunks total", len(self.notes), len(self.chunks))

    def _reindex(self) -> None:
        """Rebuild chunks, search structures, and the on-disk copy.

        Resume and notes live in one index so a single query can draw on both -
        a recruiter asking "are they open to a switch?" needs the notes, while
        "what did they build?" needs the resume, and neither should miss.
        Callers must already hold the lock.
        """
        settings = get_settings()
        self.chunks = chunk_resume(self.full_text, settings.chunk_chars, settings.chunk_overlap)
        if self.notes:
            self.chunks += chunk_notes(
                self.notes, settings.chunk_chars, settings.chunk_overlap, start=len(self.chunks)
            )
        self.indexed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        texts = [c.text for c in self.chunks]
        self._bm25 = BM25(texts) if texts else None
        self._vectors = embed.encode(texts, settings.embedder)
        self.embedder = embed.backend_name(settings.embedder)
        self._persist()

    def clear(self) -> None:
        with self._lock:
            self.chunks, self.filename, self.full_text = [], None, ""
            self.indexed_at, self._bm25, self._vectors = None, None, None
            self.detected_name = None
            self.notes = ""
            for path in (META_PATH, VECTOR_PATH, TEXT_PATH, NOTES_PATH):
                path.unlink(missing_ok=True)

    # ---------- search ----------
    def search(self, query: str, top_k: int = 6) -> list[Hit]:
        """Hybrid retrieval: BM25 fused with vector similarity via reciprocal rank fusion.

        RRF is used instead of score averaging because BM25 and cosine scores are on
        incomparable scales; ranks are all we can safely combine.
        """
        if not self.ready or not query.strip():
            return []

        rankings: list[list[int]] = []

        if self._bm25:
            # Expanded only for BM25: embeddings already capture the synonyms, and
            # padding a vector query with extra terms blurs it.
            lex = self._bm25.search(expand(query))
            if any(s > 0 for s in lex):
                rankings.append(sorted(range(len(lex)), key=lambda i: lex[i], reverse=True))

        if self._vectors is not None:
            qv = embed.encode([query], get_settings().embedder)
            if qv is not None:
                sims = (self._vectors @ qv[0]).tolist()
                rankings.append(sorted(range(len(sims)), key=lambda i: sims[i], reverse=True))

        if not rankings:
            return self._fallback(top_k)

        k = 60.0  # standard RRF damping
        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)

        best = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        if not best:
            return self._fallback(top_k)
        ceiling = best[0][1] or 1.0
        # Normalize to 0-1 so the UI can show a meaningful relevance bar.
        return [Hit(chunk=self.chunks[i], score=round(s / ceiling, 4)) for i, s in best]

    def _fallback(self, top_k: int) -> list[Hit]:
        """Nothing matched. Return a spread of the resume rather than nothing.

        An empty context makes the model answer from thin air, which is the one
        outcome this app must avoid; a generic excerpt lets it say "not covered".
        """
        preferred = ("Summary", "Experience", "Skills", "Projects")
        ordered = sorted(
            self.chunks,
            key=lambda c: (preferred.index(c.section) if c.section in preferred else 99, c.order),
        )
        return [Hit(chunk=c, score=0.0) for c in ordered[:top_k]]

    # ---------- persistence ----------
    def _persist(self) -> None:
        META_PATH.write_text(
            json.dumps(
                {
                    "filename": self.filename,
                    "indexed_at": self.indexed_at,
                    "embedder": self.embedder,
                    "detected_name": self.detected_name,
                    "chunks": [c.to_dict() for c in self.chunks],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        TEXT_PATH.write_text(self.full_text, encoding="utf-8")
        if self.notes:
            NOTES_PATH.write_text(self.notes, encoding="utf-8")
        else:
            NOTES_PATH.unlink(missing_ok=True)
        if self._vectors is not None:
            np.save(VECTOR_PATH, self._vectors)
        else:
            VECTOR_PATH.unlink(missing_ok=True)

    def load(self) -> bool:
        if not META_PATH.exists():
            return False
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            self.chunks = [Chunk(**c) for c in meta.get("chunks", [])]
            if not self.chunks:
                return False
            self.filename = meta.get("filename")
            self.indexed_at = meta.get("indexed_at")
            self.embedder = meta.get("embedder", "lexical:bm25")
            self.detected_name = meta.get("detected_name")
            self.full_text = TEXT_PATH.read_text(encoding="utf-8") if TEXT_PATH.exists() else ""
            self.notes = NOTES_PATH.read_text(encoding="utf-8") if NOTES_PATH.exists() else ""
            self._bm25 = BM25([c.text for c in self.chunks])
            if VECTOR_PATH.exists():
                vectors = np.load(VECTOR_PATH)
                # A stale vector file (resume re-indexed under a different embedder) is worse
                # than none, so only trust it when the shape still lines up.
                self._vectors = vectors if len(vectors) == len(self.chunks) else None

            # Backfill for indexes written before name detection existed, so an
            # upgrade doesn't require re-uploading the resume.
            if not self.detected_name and self.full_text:
                self.detected_name = extract_name(self.full_text)
                if self.detected_name:
                    log.info("Backfilled detected name: %s", self.detected_name)
                    self._persist()
            log.info("Restored index for %s (%d chunks)", self.filename, len(self.chunks))
            return True
        except Exception as exc:
            log.warning("Could not restore index, starting empty: %s", exc)
            self.clear()
            return False


index = ResumeIndex()
