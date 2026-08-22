"""Split the resume, and the owner's free-form notes, into section-aware chunks.

Citations are only useful if they can say *where* an answer came from, so we
detect the classic resume headings first and chunk inside them. Notes are chunked
the same way but keyed off markdown headings, and carry source="notes" so the UI
can tell a recruiter whether a claim came from the resume or from context the
owner wrote by hand.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# Canonical section -> patterns that introduce it.
SECTION_PATTERNS: list[tuple[str, str]] = [
    ("Summary", r"(professional\s+)?(summary|profile|objective|about\s*me)"),
    ("Experience", r"(work\s+)?(experience|employment|professional\s+background|career)"),
    ("Projects", r"(personal\s+|key\s+|academic\s+)?projects?"),
    ("Skills", r"(technical\s+)?(skills|technologies|tech\s*stack|competencies)"),
    ("Education", r"education(al\s+background)?|academics?|qualifications?"),
    ("Certifications", r"certifications?|licenses?|courses?|training"),
    ("Achievements", r"achievements?|awards?|honou?rs?|accomplishments?"),
    ("Publications", r"publications?|papers?|research"),
    ("Contact", r"contact|personal\s+details|links?"),
    ("Languages", r"languages?"),
    ("Interests", r"interests?|hobbies|activities|volunteer(ing)?"),
]


@dataclass
class Chunk:
    chunk_id: str
    section: str
    text: str
    order: int
    source: str = "resume"  # "resume" | "notes"

    def to_dict(self) -> dict:
        return asdict(self)


def _match_heading(line: str) -> str | None:
    """Return the canonical section name if `line` looks like a resume heading."""
    stripped = line.strip().strip(":").strip()
    if not stripped or len(stripped) > 45:
        return None
    # Headings are short, mostly letters, and rarely end in a sentence.
    if re.search(r"[.;,]$", stripped):
        return None
    words = stripped.split()
    if len(words) > 4:
        return None
    normalized = re.sub(r"[^a-z\s]", " ", stripped.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    for canonical, pattern in SECTION_PATTERNS:
        if re.fullmatch(pattern, normalized):
            return canonical
    return None


def looks_like_heading(line: str) -> bool:
    """True if `line` is a resume section heading. Used to keep name detection
    from mistaking "Professional Summary" for a person."""
    return _match_heading(line) is not None


def split_sections(text: str) -> list[tuple[str, str]]:
    """Return [(section_name, body_text), ...] preserving document order."""
    lines = text.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current = "Header"
    buffer: list[str] = []

    for line in lines:
        heading = _match_heading(line)
        if heading:
            if buffer:
                sections.append((current, buffer))
            current = heading
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        sections.append((current, buffer))

    return [(name, "\n".join(body).strip()) for name, body in sections if "".join(body).strip()]


def chunk_resume(
    text: str, max_chars: int = 900, overlap: int = 150, start: int = 0
) -> list[Chunk]:
    return _build(split_sections(text), max_chars, overlap, start, "resume")


_HASH_HEADING = re.compile(r"^#{1,4}\s*(.+?)\s*:?$")
_BOLD_HEADING = re.compile(r"^\*\*(.+?)\*\*\s*:?$")
# A bare "Job search:" line. Restricted to plain words so ordinary prose ending
# in a colon ("I'm interested in the following:") is not mistaken for a heading.
_COLON_HEADING = re.compile(r"^([A-Za-z][A-Za-z0-9 /&+-]{1,48}):$")


def note_heading(line: str) -> str | None:
    """Return the heading text if this notes line introduces a section."""
    stripped = line.strip()
    if not stripped:
        return None

    for pattern in (_HASH_HEADING, _BOLD_HEADING):
        match = pattern.match(stripped)
        if match and match.group(1).strip() and len(match.group(1)) <= 50:
            return _clean_heading(match.group(1))

    match = _COLON_HEADING.match(stripped)
    if match and len(match.group(1).split()) <= 6:
        return _clean_heading(match.group(1))
    return None


def _clean_heading(value: str) -> str:
    value = value.strip()
    # Only title-case when the author typed it all lowercase. Doing it
    # unconditionally would turn "LLM & RAG work" into "Llm & Rag Work".
    if value.islower():
        return value.title()
    return value[0].upper() + value[1:]


def split_note_sections(text: str) -> list[tuple[str, str]]:
    """Split free-form notes on headings, defaulting to a single "Notes" block."""
    sections: list[tuple[str, list[str]]] = []
    current = "Notes"
    buffer: list[str] = []

    for line in text.split("\n"):
        heading = note_heading(line)
        if heading:
            if buffer:
                sections.append((current, buffer))
            current = heading
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        sections.append((current, buffer))

    return [(n, "\n".join(b).strip()) for n, b in sections if "".join(b).strip()]


def chunk_notes(
    text: str, max_chars: int = 900, overlap: int = 150, start: int = 0
) -> list[Chunk]:
    return _build(split_note_sections(text), max_chars, overlap, start, "notes")


def _build(
    sections: list[tuple[str, str]],
    max_chars: int,
    overlap: int,
    start: int,
    source: str,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    order = start
    for section, body in sections:
        for piece in _split_body(body, max_chars, overlap):
            chunks.append(
                Chunk(
                    chunk_id=f"c{order:03d}",
                    section=section,
                    # Prefixing the section makes retrieval and the LLM prompt self-describing.
                    text=f"[{section}] {piece}",
                    order=order,
                    source=source,
                )
            )
            order += 1
    return chunks


def _split_body(body: str, max_chars: int, overlap: int) -> list[str]:
    """Break a section body on paragraph/bullet boundaries, never mid-word."""
    body = body.strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    # Prefer splitting on blank lines, then on single newlines (bullets).
    units = [u.strip() for u in re.split(r"\n\s*\n", body) if u.strip()]
    if max(len(u) for u in units) > max_chars:
        units = [u.strip() for u in body.split("\n") if u.strip()]

    pieces: list[str] = []
    buf = ""
    for unit in units:
        while len(unit) > max_chars:  # one absurdly long line
            cut = unit.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            pieces.append(unit[:cut].strip())
            unit = unit[cut:].strip()
        if not buf:
            buf = unit
        elif len(buf) + len(unit) + 1 <= max_chars:
            buf = f"{buf}\n{unit}"
        else:
            pieces.append(buf)
            tail = buf[-overlap:] if overlap else ""
            # Carry a little context forward so a bullet split across chunks stays readable.
            buf = f"{tail}\n{unit}".strip() if tail else unit
    if buf:
        pieces.append(buf)
    return pieces
