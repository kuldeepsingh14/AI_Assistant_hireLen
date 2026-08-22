"""Re-seed the profile from committed files when the runtime store is empty.

Render's free tier gives an ephemeral disk: every restart and every deploy wipes
whatever was uploaded through the admin console, and the site would come back
with no resume at all. Anything placed in `backend/data/seed/` is committed with
the repo, so it survives, and is indexed automatically when there is no existing
index to load.

This never overwrites a live profile - an upload through the console always wins
until the disk is wiped.
"""
from __future__ import annotations

import logging

from ..config import SEED_DIR
from .extract import SUPPORTED, extract_text
from .store import index

log = logging.getLogger(__name__)

NOTES_FILE = "notes.md"
# Documentation that lives in the folder must never be mistaken for a resume.
IGNORED = {NOTES_FILE, "readme.md", "readme.txt", ".gitkeep"}


def _find_resume():
    """First resume-shaped file in the seed directory, in a stable order."""
    candidates = [
        p
        for p in sorted(SEED_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED and p.name.lower() not in IGNORED
    ]
    return candidates[0] if candidates else None


def load_if_empty() -> bool:
    """Index the seed resume and notes if nothing is loaded. Returns True if it did."""
    if index.ready:
        return False
    if not SEED_DIR.is_dir():
        return False

    resume = _find_resume()
    if resume is None:
        return False

    try:
        text = extract_text(resume.name, resume.read_bytes())
        index.build(text, resume.name)
    except Exception as exc:
        log.error("Could not index the seed resume %s: %s", resume.name, exc)
        return False

    notes_path = SEED_DIR / NOTES_FILE
    if notes_path.is_file():
        try:
            index.set_notes(notes_path.read_text(encoding="utf-8"))
        except Exception as exc:  # notes are optional; a bad file must not block boot
            log.warning("Could not load seed notes: %s", exc)

    log.info("Seeded profile from %s (%d chunks)", resume.name, len(index.chunks))
    return True
