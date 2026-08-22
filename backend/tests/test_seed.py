"""Seeding a profile from committed files on an ephemeral-disk host."""
from __future__ import annotations

from pathlib import Path

import pytest

SAMPLE = (Path(__file__).parent / "sample_resume.txt").read_bytes()


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """Isolated seed dir + a fresh index that never touches the real store."""
    import app.services.seed as seed_mod
    import app.services.store as store_mod
    from app.services.store import ResumeIndex

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    monkeypatch.setattr(seed_mod, "SEED_DIR", seed_dir)

    for name in ("META_PATH", "VECTOR_PATH", "TEXT_PATH", "NOTES_PATH"):
        monkeypatch.setattr(store_mod, name, tmp_path / f"{name}.dat")

    index = ResumeIndex()
    monkeypatch.setattr(seed_mod, "index", index)
    return seed_mod, index, seed_dir


def test_seeds_resume_when_index_is_empty(seeded) -> None:
    seed_mod, index, seed_dir = seeded
    (seed_dir / "resume.txt").write_bytes(SAMPLE)

    assert seed_mod.load_if_empty() is True
    assert index.ready
    assert index.detected_name == "Jane Doe"


def test_seeds_notes_alongside_the_resume(seeded) -> None:
    seed_mod, index, seed_dir = seeded
    (seed_dir / "resume.txt").write_bytes(SAMPLE)
    (seed_dir / "notes.md").write_text("## Job search\nOpen to offers.", encoding="utf-8")

    seed_mod.load_if_empty()
    assert "Job search" in index.note_sections
    assert any(c.source == "notes" for c in index.chunks)


def test_readme_is_not_mistaken_for_a_resume(seeded) -> None:
    """The folder documents itself; that file must never become the profile."""
    seed_mod, index, seed_dir = seeded
    (seed_dir / "README.md").write_text("# Seed profile\nPut your resume here.", encoding="utf-8")

    assert seed_mod.load_if_empty() is False
    assert not index.ready


def test_notes_alone_do_not_seed(seeded) -> None:
    seed_mod, index, seed_dir = seeded
    (seed_dir / "notes.md").write_text("## Job search\nOpen.", encoding="utf-8")

    assert seed_mod.load_if_empty() is False
    assert not index.ready


def test_empty_seed_dir_is_a_noop(seeded) -> None:
    seed_mod, index, _ = seeded
    assert seed_mod.load_if_empty() is False
    assert not index.ready


def test_an_uploaded_profile_is_never_overwritten(seeded) -> None:
    """A live upload must win over the committed seed."""
    seed_mod, index, seed_dir = seeded
    (seed_dir / "resume.txt").write_bytes(SAMPLE)

    from app.services.extract import extract_text

    index.build(extract_text("real.txt", b"KULDEEP SINGH\nSKILLS\nJava, Spring Boot"), "real.txt")
    assert seed_mod.load_if_empty() is False
    assert index.filename == "real.txt"


def test_unreadable_seed_does_not_crash_startup(seeded) -> None:
    """A corrupt committed file must not take the whole service down on boot."""
    seed_mod, index, seed_dir = seeded
    (seed_dir / "resume.pdf").write_bytes(b"this is not a pdf")

    assert seed_mod.load_if_empty() is False
    assert not index.ready
