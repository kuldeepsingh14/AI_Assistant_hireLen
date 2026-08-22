"""Owner notes: context that isn't on the resume, indexed alongside it."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.chunk import chunk_notes, split_note_sections
from app.services.extract import extract_text, safe_filename
from app.services.store import ResumeIndex

SAMPLE = (Path(__file__).parent / "sample_resume.txt").read_bytes()

NOTES = """## Job search
Actively looking to switch roles and open to interviewing now.

## Currently learning
Building depth in LLMs, RAG pipelines, LangChain and LangGraph for agentic workflows.

## What I want next
A backend or AI engineering role with ownership of production systems.
"""


@pytest.fixture
def index(tmp_path, monkeypatch) -> ResumeIndex:
    """A real index writing to a temp dir, so tests never touch the live one."""
    import app.services.store as store_mod

    for name in ("META_PATH", "VECTOR_PATH", "TEXT_PATH", "NOTES_PATH"):
        monkeypatch.setattr(store_mod, name, tmp_path / f"{name.lower()}.dat")

    idx = ResumeIndex()
    idx.build(extract_text("sample_resume.txt", SAMPLE), "sample_resume.txt")
    return idx


# ---------- note sectioning ----------
def test_markdown_headings_become_sections() -> None:
    """The author's capitalization is preserved - see the acronym test below."""
    names = [n for n, _ in split_note_sections(NOTES)]
    assert names == ["Job search", "Currently learning", "What I want next"]


def test_bold_and_colon_headings_also_work() -> None:
    assert [n for n, _ in split_note_sections("**Job search**\nLooking now.")] == ["Job search"]
    assert [n for n, _ in split_note_sections("Job search:\nLooking now.")] == ["Job search"]


def test_unheaded_notes_get_one_section() -> None:
    chunks = chunk_notes("Just some free-form context about me.")
    assert len(chunks) == 1
    assert chunks[0].section == "Notes"


def test_note_chunks_are_tagged_as_notes() -> None:
    assert all(c.source == "notes" for c in chunk_notes(NOTES))


# ---------- indexing together ----------
def test_notes_are_added_to_the_index(index: ResumeIndex) -> None:
    before = len(index.chunks)
    index.set_notes(NOTES)
    assert len(index.chunks) > before
    assert {c.source for c in index.chunks} == {"resume", "notes"}


def test_chunk_ids_stay_unique_across_sources(index: ResumeIndex) -> None:
    index.set_notes(NOTES)
    ids = [c.chunk_id for c in index.chunks]
    assert len(ids) == len(set(ids))


def test_notes_are_retrievable(index: ResumeIndex) -> None:
    """The whole point: questions the resume cannot answer now have a source."""
    index.set_notes(NOTES)

    hits = index.search("are they looking for a new job?", 5)
    assert any(h.chunk.source == "notes" for h in hits)

    hits = index.search("do they know LangChain or RAG?", 5)
    assert any("LangChain" in h.chunk.text for h in hits)


def test_resume_still_retrievable_after_notes(index: ResumeIndex) -> None:
    index.set_notes(NOTES)
    hits = index.search("what did they study?", 5)
    assert any(h.chunk.section == "Education" for h in hits)


def test_notes_survive_a_resume_reupload(index: ResumeIndex) -> None:
    """Re-uploading a resume must not silently wipe the owner's notes."""
    index.set_notes(NOTES)
    index.build(extract_text("r.txt", SAMPLE), "sample_resume.txt")
    assert index.notes == NOTES.strip()
    assert any(c.source == "notes" for c in index.chunks)


def test_clearing_notes_removes_their_chunks(index: ResumeIndex) -> None:
    index.set_notes(NOTES)
    index.set_notes("")
    assert index.notes == ""
    assert all(c.source == "resume" for c in index.chunks)


def test_note_sections_listed_separately(index: ResumeIndex) -> None:
    index.set_notes(NOTES)
    assert index.note_sections == ["Job search", "Currently learning", "What I want next"]
    assert "Education" not in index.note_sections


# ---------- filename safety ----------
@pytest.mark.parametrize(
    "raw",
    [
        "../../../../app/main.py",
        "..\\..\\evil.pdf",
        "C:/Windows/system32/config.pdf",
        "/etc/passwd",
    ],
)
def test_traversal_filenames_are_flattened(raw: str) -> None:
    safe = safe_filename(raw)
    assert "/" not in safe and "\\" not in safe
    assert not safe.startswith("..")


def test_ordinary_filenames_stay_recognizable() -> None:
    assert safe_filename("Kuldeep_Singh_resume.pdf") == "Kuldeep_Singh_resume.pdf"
    assert safe_filename("my resume.docx") == "my resume.docx"


def test_empty_filename_gets_a_fallback() -> None:
    assert safe_filename("") == "resume"
    assert safe_filename("...") == "resume"


def test_acronyms_survive_heading_normalization() -> None:
    """Title-casing everything would turn "LLM & RAG work" into "Llm & Rag Work"."""
    assert [n for n, _ in split_note_sections("## LLM & RAG work\nStudying.")] == [
        "LLM & RAG work"
    ]
    assert [n for n, _ in split_note_sections("## job search\nLooking.")] == ["Job Search"]


def test_prose_ending_in_a_colon_is_not_a_heading() -> None:
    text = "I'm interested in the following:\nBackend and AI roles."
    assert [n for n, _ in split_note_sections(text)] == ["Notes"]


def test_long_line_is_not_a_heading() -> None:
    long_line = "This is a fairly long sentence that happens to end with a colon here:"
    assert [n for n, _ in split_note_sections(long_line + "\nmore")] == ["Notes"]


# ---------- the match report gets the same pronoun treatment as chat ----------
def test_match_report_prose_is_pronoun_normalized() -> None:
    """The report is model-written prose about a real person, like chat answers."""
    from app.services.jd_match import _fix_verdict
    from app.services.pronouns import normalize
    from app.models.schemas import RequirementVerdict

    fix = lambda t: normalize(t, "they/them")
    v = RequirementVerdict(
        requirement="Java",
        category="must_have",
        status="match",
        evidence="He built the service.",
        comment="She has four years of Java.",
    )
    fixed = _fix_verdict(v, fix)
    assert fixed.evidence == "They built the service."
    assert fixed.comment == "They have four years of Java."
    # Status and weighting must be untouched by a text pass.
    assert fixed.status == "match" and fixed.category == "must_have"
