"""Work out whose resume this is.

The owner's name should come from the document, not from a config value someone
has to remember to change - a resume that says "Kuldeep Singh" while the UI says
"Jane Doe" is the kind of mismatch that makes the whole assistant look broken.

Strategy: scan the first handful of lines for something shaped like a person's
name, then fall back to the local part of an email address. Returns None when
nothing is convincing enough, so the caller can use its configured default rather
than display a guess.
"""
from __future__ import annotations

import re

from .chunk import looks_like_heading

# How far into the document to look. The name is on line 1 of essentially every
# resume; past the header block, any Title Case phrase is a false positive.
_SCAN_LINES = 8

# Lowercase words that are legitimately part of a name.
_PARTICLES = {
    "van", "von", "de", "der", "den", "del", "della", "di", "da", "dos", "das",
    "la", "le", "bin", "ibn", "al", "el", "of", "san", "st",
}

# A Title Case line made of these is a job title, not a name.
_JOB_WORDS = {
    "engineer", "developer", "manager", "analyst", "designer", "consultant",
    "intern", "scientist", "architect", "administrator", "specialist", "lead",
    "director", "officer", "president", "founder", "student", "graduate",
    "programmer", "researcher", "associate", "executive", "head", "senior",
    "junior", "principal", "staff", "full", "stack", "frontend", "backend",
    "software", "data", "web", "cloud", "product", "project", "technical",
}

# Document-title noise that can precede the actual name.
_LABEL_RE = re.compile(
    r"^\s*(resum[eé]|curriculum\s+vitae|cv|profile|personal\s+details)\s*(of|:|-|–|—)?\s*",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"([A-Za-z][A-Za-z0-9._%-]*)@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Split on the separators resumes use between name and contact details.
_SEPARATORS = re.compile(r"\s*[|•·/\\]\s*|\s{3,}|\s+[–—]\s+")


def extract_name(text: str) -> str | None:
    """Best-effort owner name from resume text, or None if unsure."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()][:_SCAN_LINES]

    for line in lines:
        # "JANE DOE | Bengaluru | jane@x.com" -> try the leading segment.
        candidate = _SEPARATORS.split(line)[0].strip()
        candidate = _LABEL_RE.sub("", candidate).strip(" ,-–—:")
        if _is_name(candidate):
            return _titlecase(candidate)

    return _from_email(text)


def _is_name(value: str) -> bool:
    if not value or len(value) > 60:
        return False
    # Contact lines, addresses, and headings are never the name.
    if re.search(r"[0-9@#()\[\]{}<>+=_]", value) or "," in value:
        return False
    if re.search(r"\b(https?|www)\b", value, re.IGNORECASE):
        return False
    if looks_like_heading(value):
        return False

    tokens = value.split()
    if not 2 <= len(tokens) <= 4:
        return False

    lowered = {t.lower().strip(".") for t in tokens}
    if lowered & _JOB_WORDS:
        return False

    for token in tokens:
        core = token.strip(".'-")
        if not core or len(core) > 20:
            return False
        if not re.fullmatch(r"[A-Za-z][A-Za-z'’-]*", core):
            return False
        # Stray lowercase words mean it is a sentence, unless it is a name particle.
        if core.islower() and core.lower() not in _PARTICLES:
            return False

    # Require the line to read as a name: Title Case or ALL CAPS throughout.
    significant = [t.strip(".'-") for t in tokens if t.strip(".'-").lower() not in _PARTICLES]
    return bool(significant) and all(
        t[0].isupper() and (t.isupper() or t[1:].islower() or len(t) == 1 or _mixed_ok(t))
        for t in significant
    )


def _mixed_ok(token: str) -> bool:
    """Allow McDonald, O'Brien, and hyphenated names."""
    return bool(re.fullmatch(r"[A-Z][a-z]*(['’-]?[A-Z]?[a-z]+)*", token))


def _titlecase(value: str) -> str:
    out = []
    for token in value.split():
        lower = token.lower()
        if lower.strip(".") in _PARTICLES and out:
            out.append(lower)
        elif token.isupper() or token.islower():
            # "JANE" -> "Jane"; preserve internal punctuation like O'BRIEN.
            out.append(re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), lower))
        else:
            out.append(token)  # already mixed case - trust the document
    return " ".join(out)


def _from_email(text: str) -> str | None:
    """"kuldeep.singh@example.com" -> "Kuldeep Singh"."""
    match = _EMAIL_RE.search(text)
    if not match:
        return None
    local = match.group(1)
    parts = [p for p in re.split(r"[._-]+", local) if p.isalpha() and len(p) > 1]
    # A single token could be anything ("info", "contact"); two reads like a name.
    if len(parts) < 2 or len(parts) > 3:
        return None
    if {p.lower() for p in parts} & _JOB_WORDS:
        return None
    return " ".join(p.capitalize() for p in parts)


# Values that mean "nobody set this", so detection should win.
_PLACEHOLDERS = {"", "your name", "the candidate", "your_name", "name"}

FALLBACK = "the candidate"


def resolve_owner_name(configured: str | None, detected: str | None) -> str:
    """Pick the name to display.

    Detection from the resume is the default, so uploading a new resume is all it
    takes to rebrand the assistant. OWNER_NAME stays available as an explicit
    override for when detection is wrong or a different display name is wanted.
    """
    value = (configured or "").strip()
    if value and value.lower() not in _PLACEHOLDERS:
        return value
    return (detected or "").strip() or FALLBACK
