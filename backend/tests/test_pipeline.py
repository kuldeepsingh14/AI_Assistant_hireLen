"""Tests for the parts that must work without an API key: parsing, chunking, retrieval, scoring."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models.schemas import RequirementVerdict
from app.services import jd_match
from app.services.chunk import chunk_resume, split_sections
from app.services.expand import expand
from app.services.extract import UnsupportedFile, extract_text
from app.services.store import ResumeIndex

SAMPLE = (Path(__file__).parent / "sample_resume.txt").read_bytes()


@pytest.fixture(scope="module")
def text() -> str:
    return extract_text("sample_resume.txt", SAMPLE)


@pytest.fixture(scope="module")
def index(text: str) -> ResumeIndex:
    idx = ResumeIndex()
    # Build without touching the shared on-disk index.
    from app.services.bm25 import BM25

    idx.chunks = chunk_resume(text, 900, 150)
    idx.full_text = text
    idx.filename = "sample_resume.txt"
    idx._bm25 = BM25([c.text for c in idx.chunks])
    return idx


# ---------- extraction ----------
def test_extract_plain_text(text: str) -> None:
    assert "Zeta Payments" in text
    assert "PES University" in text


def test_extract_rejects_unknown_type() -> None:
    with pytest.raises(UnsupportedFile):
        extract_text("resume.pages", b"whatever")


def test_extract_strips_page_furniture() -> None:
    cleaned = extract_text("r.txt", b"Real line\nPage 1 of 3\n2\nAnother line")
    assert "Page 1 of 3" not in cleaned
    assert "Real line" in cleaned and "Another line" in cleaned


# ---------- chunking ----------
def test_sections_are_detected(text: str) -> None:
    names = [name for name, _ in split_sections(text)]
    for expected in ("Summary", "Experience", "Projects", "Skills", "Education"):
        assert expected in names


def test_chunks_carry_section_labels(text: str) -> None:
    chunks = chunk_resume(text, 900, 150)
    assert chunks
    assert all(c.text.startswith(f"[{c.section}]") for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_long_section_splits_under_limit() -> None:
    body = "EXPERIENCE\n" + "\n".join(f"- Did notable thing number {i}." * 3 for i in range(60))
    chunks = chunk_resume(body, 300, 50)
    assert len(chunks) > 1
    # Allow for the "[Section] " prefix on top of the raw budget.
    assert all(len(c.text) <= 300 + 40 for c in chunks)


# ---------- query expansion ----------
def test_expansion_bridges_vocabulary_gap() -> None:
    assert "education" in expand("what did they study?")
    assert "certification" in expand("are they certified?")


def test_expansion_keeps_original_terms() -> None:
    assert expand("kubernetes").startswith("kubernetes")


def test_expansion_is_noop_for_unknown_words() -> None:
    assert expand("zzz qqq") == "zzz qqq"


# ---------- retrieval ----------
@pytest.mark.parametrize(
    "query,expected_section",
    [
        ("what did they study?", "Education"),
        ("are they AWS certified?", "Certifications"),
        ("tell me about their projects", "Projects"),
        ("which programming languages do they know?", "Skills"),
        ("where do they work now?", "Experience"),
    ],
)
def test_retrieval_finds_right_section(index: ResumeIndex, query: str, expected_section: str) -> None:
    hits = index.search(query, 3)
    assert hits, f"no hits for {query!r}"
    assert expected_section in {h.chunk.section for h in hits}


def test_unanswerable_query_still_returns_context(index: ResumeIndex) -> None:
    """Never hand the model an empty context - it invents things when starved."""
    hits = index.search("what is their favourite colour?", 3)
    assert hits
    assert all(h.score == 0.0 for h in hits)


def test_empty_index_returns_nothing() -> None:
    assert ResumeIndex().search("anything", 3) == []


# ---------- deterministic scoring ----------
def _v(category: str, status: str) -> RequirementVerdict:
    return RequirementVerdict(
        requirement="r", category=category, status=status, evidence="e", comment="c"
    )


def test_must_haves_outweigh_nice_to_haves() -> None:
    missing_must = jd_match._score([_v("must_have", "missing"), _v("nice_to_have", "match")])
    missing_nice = jd_match._score([_v("must_have", "match"), _v("nice_to_have", "missing")])
    assert missing_nice > missing_must


def test_score_bounds() -> None:
    assert jd_match._score([_v("must_have", "match")]) == 100
    assert jd_match._score([_v("must_have", "missing")]) == 0
    assert jd_match._score([]) == 0
    assert jd_match._score([_v("must_have", "partial")]) == 50


def test_missing_verdict_counts_against_score() -> None:
    """A requirement the model forgot to judge must not vanish from the denominator."""
    requirements = [
        {"requirement": "Python", "category": "must_have"},
        {"requirement": "Kubernetes", "category": "must_have"},
    ]
    verdicts = jd_match._align_verdicts(
        requirements,
        [{"requirement": "Python", "status": "match", "evidence": "4 years", "comment": "ok"}],
    )
    assert len(verdicts) == 2
    assert verdicts[1].status == "missing"
    assert jd_match._score(verdicts) == 50


def test_match_without_evidence_is_demoted_to_partial() -> None:
    verdicts = jd_match._align_verdicts(
        [{"requirement": "Rust", "category": "must_have"}],
        [{"requirement": "Rust", "status": "match", "evidence": "", "comment": "claims it"}],
    )
    assert verdicts[0].status == "partial"


def test_garbage_verdict_payload_does_not_crash() -> None:
    verdicts = jd_match._align_verdicts(
        [{"requirement": "Go", "category": "nice_to_have"}], "not a list"
    )
    assert verdicts[0].status == "missing"


def test_bands_are_ordered() -> None:
    assert jd_match._band(95) == "Strong match"
    assert jd_match._band(75) == "Good match"
    assert jd_match._band(60) == "Solid fit, some ramp-up"
    assert jd_match._band(45) == "Stretch role, strong fundamentals"
    assert jd_match._band(10) == "Early-stage fit"


def test_band_wording_is_constructive_but_score_is_untouched() -> None:
    """Labels are editorial; the number must never be adjusted to flatter."""
    verdicts = [_v("must_have", "match"), _v("must_have", "missing")]
    assert jd_match._score(verdicts) == 50


def test_graded_credit_is_ordered() -> None:
    """Each step must be worth strictly less than the one above it."""
    order = ["match", "transferable", "partial", "learning", "missing"]
    values = [jd_match.CREDIT[s] for s in order]
    assert values == sorted(values, reverse=True)
    assert values[0] == 1.0 and values[-1] == 0.0


def test_adjacent_experience_scores_above_missing() -> None:
    """The point of the graded rubric: shipping RabbitMQ is not the same as nothing."""
    adjacent = jd_match._score([_v("must_have", "transferable")])
    nothing = jd_match._score([_v("must_have", "missing")])
    exact = jd_match._score([_v("must_have", "match")])
    assert nothing < adjacent < exact


def test_learning_counts_but_counts_least() -> None:
    learning = jd_match._score([_v("must_have", "learning")])
    partial = jd_match._score([_v("must_have", "partial")])
    assert 0 < learning < partial


def test_no_credit_can_exceed_a_real_match() -> None:
    """Guard against a future edit quietly inflating a status above 100%."""
    assert max(jd_match.CREDIT.values()) == jd_match.CREDIT["match"] == 1.0
    assert jd_match._score([_v("must_have", s) for s in jd_match.CREDIT]) <= 100


# ---------- llm json salvage ----------
def test_json_parsed_from_fenced_block() -> None:
    from app.services.llm import parse_json

    assert parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('{"b": 2}') == {"b": 2}
