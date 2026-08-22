"""Recruiter lead capture and log clearing."""
from __future__ import annotations

import pytest

from app.models.schemas import LeadPayload


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the analytics module at a throwaway database."""
    import app.services.analytics as a

    monkeypatch.setattr(a, "DB_PATH", tmp_path / "test.db")
    a.init()
    return a


# ---------- storage ----------
def test_lead_is_saved_and_listed(db) -> None:
    db.save_lead("s1", "Priya Nair", "Acme", "priya@acme.com", None, "Backend Engineer", None)
    leads = db.list_leads()
    assert len(leads) == 1
    assert leads[0].name == "Priya Nair"
    assert leads[0].company == "Acme"
    assert leads[0].role == "Backend Engineer"


def test_lead_carries_the_questions_from_that_session(db) -> None:
    """The point of storing session_id: see what this recruiter actually asked."""
    db.log_question("s1", "hr", "Why should we hire them?", True)
    db.log_question("s1", "hr", "Do they know Kafka?", True)
    db.log_question("s2", "hr", "Someone else's question", True)
    db.save_lead("s1", "Priya", "Acme", "p@acme.com", None, None, None)

    lead = db.list_leads()[0]
    assert lead.questions == ["Why should we hire them?", "Do they know Kafka?"]
    assert "Someone else's question" not in lead.questions


def test_leads_are_newest_first(db) -> None:
    db.save_lead("s1", "First", None, "a@x.com", None, None, None)
    db.save_lead("s2", "Second", None, "b@x.com", None, None, None)
    assert [l.name for l in db.list_leads()] == ["Second", "First"]


def test_delete_one_lead(db) -> None:
    db.save_lead("s1", "Keep", None, "k@x.com", None, None, None)
    doomed = db.save_lead("s2", "Remove", None, "r@x.com", None, None, None)
    assert db.delete_lead(doomed) is True
    assert [l.name for l in db.list_leads()] == ["Keep"]
    assert db.delete_lead(99999) is False


# ---------- clearing ----------
def test_clearing_activity_leaves_leads_alone(db) -> None:
    """A "clear log" click must never destroy someone's inbound recruiters."""
    db.log_question("s1", "hr", "A question", True)
    db.log_match("Backend Engineer", "Acme", 82)
    db.save_lead("s1", "Priya", "Acme", "p@acme.com", None, None, None)

    db.clear_activity()

    stats = db.summary()
    assert stats.total_questions == 0
    assert stats.total_jd_matches == 0
    assert stats.total_leads == 1
    assert len(db.list_leads()) == 1


def test_clearing_leads_is_separate(db) -> None:
    db.log_question("s1", "hr", "A question", True)
    db.save_lead("s1", "Priya", None, "p@acme.com", None, None, None)

    db.clear_leads()

    assert db.list_leads() == []
    assert db.summary().total_questions == 1


def test_lead_count_appears_in_summary(db) -> None:
    assert db.summary().total_leads == 0
    db.save_lead("s1", "Priya", None, "p@acme.com", None, None, None)
    assert db.summary().total_leads == 1


# ---------- validation ----------
def test_name_is_required() -> None:
    with pytest.raises(Exception):
        LeadPayload(name="")


def test_contact_fields_are_optional_on_the_schema() -> None:
    """Validation of "email or phone" lives in the router, not the model."""
    payload = LeadPayload(name="Priya")
    assert payload.email is None and payload.phone is None
