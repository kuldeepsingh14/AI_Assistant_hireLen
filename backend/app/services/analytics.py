"""Owner-only analytics: what recruiters asked, and who was asking.

SQLite, no server, no cost. Questions are logged; answers are not, so the log
stays small.

The `leads` table is the one place this app stores other people's personal data
(a recruiter's name and contact details, given voluntarily). It is owner-gated
on read, deletable from the console, and never leaves this database.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config import DATA_DIR
from ..models.schemas import AnalyticsResponse, Lead, QuestionStat

log = logging.getLogger(__name__)

DB_PATH: Path = DATA_DIR / "analytics.db"
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    mode       TEXT    NOT NULL,
    question   TEXT    NOT NULL,
    grounded   INTEGER NOT NULL,
    asked_at   TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS jd_matches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_title  TEXT,
    company    TEXT,
    score      INTEGER NOT NULL,
    matched_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    company    TEXT,
    email      TEXT,
    phone      TEXT,
    role       TEXT,
    note       TEXT,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_asked_at ON questions(asked_at DESC);
CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock, _connect() as conn:
        conn.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_question(session_id: str, mode: str, question: str, grounded: bool) -> None:
    # Analytics must never break a user-facing answer, so failures are swallowed.
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO questions (session_id, mode, question, grounded, asked_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, mode, question[:500], int(grounded), _now()),
            )
    except sqlite3.Error as exc:
        log.warning("Could not log question: %s", exc)


def log_match(job_title: str | None, company: str | None, score: int) -> None:
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO jd_matches (job_title, company, score, matched_at)"
                " VALUES (?, ?, ?, ?)",
                (job_title, company, score, _now()),
            )
    except sqlite3.Error as exc:
        log.warning("Could not log match: %s", exc)


def save_lead(
    session_id: str,
    name: str,
    company: str | None,
    email: str | None,
    phone: str | None,
    role: str | None,
    note: str | None,
) -> int:
    """Record a recruiter's contact details. Returns the new row id."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO leads (session_id, name, company, email, phone, role, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, name, company, email, phone, role, note, _now()),
        )
        return int(cur.lastrowid or 0)


def list_leads(limit: int = 100) -> list[Lead]:
    """Recruiters who left contact details, each with the questions they asked."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        leads = []
        for r in rows:
            asked = conn.execute(
                "SELECT question FROM questions WHERE session_id = ? ORDER BY id",
                (r["session_id"],),
            ).fetchall()
            leads.append(
                Lead(
                    id=r["id"],
                    name=r["name"],
                    company=r["company"],
                    email=r["email"],
                    phone=r["phone"],
                    role=r["role"],
                    note=r["note"],
                    created_at=r["created_at"],
                    questions=[a["question"] for a in asked],
                )
            )
        return leads


def delete_lead(lead_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        return cur.rowcount > 0


def clear_activity() -> None:
    """Wipe the question and match logs. Leaves leads alone - those are contacts,
    not activity, and losing them to a "clear log" click would be a nasty surprise."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM questions")
        conn.execute("DELETE FROM jd_matches")


def clear_leads() -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM leads")


def summary(limit: int = 40) -> AnalyticsResponse:
    with _lock, _connect() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(mode = 'hr'), 0)      AS hr,
                   COALESCE(SUM(mode = 'visitor'), 0) AS visitor,
                   COALESCE(SUM(grounded = 0), 0)     AS ungrounded,
                   COUNT(DISTINCT session_id)         AS sessions
            FROM questions
            """
        ).fetchone()
        matches = conn.execute("SELECT COUNT(*) AS n FROM jd_matches").fetchone()
        leads = conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()
        titles = conn.execute(
            "SELECT job_title, COUNT(*) AS n FROM jd_matches"
            " WHERE job_title IS NOT NULL AND job_title != ''"
            " GROUP BY job_title ORDER BY n DESC LIMIT 5"
        ).fetchall()
        recent = conn.execute(
            "SELECT question, mode, asked_at, grounded FROM questions"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    return AnalyticsResponse(
        total_questions=totals["total"],
        hr_questions=totals["hr"],
        visitor_questions=totals["visitor"],
        ungrounded_questions=totals["ungrounded"],
        total_sessions=totals["sessions"],
        total_jd_matches=matches["n"],
        total_leads=leads["n"],
        top_jd_titles=[f"{r['job_title']} ({r['n']})" for r in titles],
        recent=[
            QuestionStat(
                question=r["question"],
                mode=r["mode"],
                asked_at=r["asked_at"],
                grounded=bool(r["grounded"]),
            )
            for r in recent
        ],
    )
