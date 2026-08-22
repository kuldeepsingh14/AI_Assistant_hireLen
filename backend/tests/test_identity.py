"""Tests for detecting whose resume this is."""
from __future__ import annotations

import pytest

from app.services.identity import FALLBACK, extract_name, resolve_owner_name


# ---------- the common layouts ----------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("KULDEEP SINGH\nBengaluru | kuldeep@example.com", "Kuldeep Singh"),
        ("Kuldeep Singh\nBackend Engineer", "Kuldeep Singh"),
        ("JANE DOE\nSUMMARY\nBackend engineer.", "Jane Doe"),
        # name and contact details sharing one line
        ("KULDEEP SINGH | Bengaluru, India | +91 99999 99999", "Kuldeep Singh"),
        ("Jane Doe • jane@x.com • github.com/jane", "Jane Doe"),
        # a document title above the name
        ("RESUME\nKuldeep Singh\nBengaluru", "Kuldeep Singh"),
        ("Curriculum Vitae of Kuldeep Singh", "Kuldeep Singh"),
        ("Resume: Jane Doe", "Jane Doe"),
        # three and four part names
        ("Kuldeep Pratap Singh\nEngineer", "Kuldeep Pratap Singh"),
        ("Maria de la Cruz\nDesigner at X", "Maria de la Cruz"),
    ],
)
def test_detects_name(text: str, expected: str) -> None:
    assert extract_name(text) == expected


def test_preserves_intentional_casing() -> None:
    assert extract_name("Ada McDonald\nEngineer") == "Ada McDonald"
    assert extract_name("Sean O'Brien\nEngineer") == "Sean O'Brien"
    assert extract_name("Anne-Marie Hughes\nEngineer") == "Anne-Marie Hughes"


# ---------- things that are not the name ----------
def test_section_heading_is_not_a_name() -> None:
    """"Professional Summary" is two Title Case words - the trap this must dodge."""
    assert extract_name("Professional Summary\nA backend engineer with 4 years.") is None


def test_job_title_is_not_a_name() -> None:
    assert extract_name("Senior Backend Engineer\nBengaluru") is None
    assert extract_name("Full Stack Developer") is None


def test_contact_lines_are_not_names() -> None:
    assert extract_name("Bengaluru, India") is None
    assert extract_name("+91 99999 99999") is None
    assert extract_name("github.com/janedoe") is None


def test_prose_is_not_a_name() -> None:
    assert extract_name("Experienced engineer who builds things.") is None


def test_single_word_is_not_a_name() -> None:
    """One word is too weak a signal - better to fall back than guess wrong."""
    assert extract_name("Kuldeep\nBackend Engineer") is None


# ---------- email fallback ----------
def test_falls_back_to_email_local_part() -> None:
    text = "Professional Summary\nBackend engineer.\nReach me: kuldeep.singh@example.com"
    assert extract_name(text) == "Kuldeep Singh"


def test_generic_mailbox_is_rejected() -> None:
    assert extract_name("Summary\nText here.\ncontact@example.com") is None
    assert extract_name("Summary\nText.\ninfo@example.com") is None


def test_returns_none_when_nothing_is_convincing() -> None:
    assert extract_name("Summary\nSome text with no name at all.") is None
    assert extract_name("") is None


# ---------- precedence ----------
def test_detected_name_wins_by_default() -> None:
    assert resolve_owner_name("", "Kuldeep Singh") == "Kuldeep Singh"
    assert resolve_owner_name(None, "Kuldeep Singh") == "Kuldeep Singh"


def test_placeholders_do_not_override_detection() -> None:
    for placeholder in ("Your Name", "the candidate", "  ", "NAME"):
        assert resolve_owner_name(placeholder, "Kuldeep Singh") == "Kuldeep Singh"


def test_explicit_config_overrides_detection() -> None:
    assert resolve_owner_name("K. Singh", "Kuldeep Singh") == "K. Singh"


def test_fallback_when_nothing_known() -> None:
    assert resolve_owner_name("", None) == FALLBACK


def test_real_sample_resume() -> None:
    from pathlib import Path

    from app.services.extract import extract_text

    raw = (Path(__file__).parent / "sample_resume.txt").read_bytes()
    assert extract_name(extract_text("sample_resume.txt", raw)) == "Jane Doe"
