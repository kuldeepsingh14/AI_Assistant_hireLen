"""Request/response contracts for the API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["visitor", "hr"]


# ---------- chat ----------
class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: Mode = "visitor"
    history: list[Turn] = Field(default_factory=list, max_length=20)
    session_id: str | None = None


class Citation(BaseModel):
    chunk_id: str
    section: str
    snippet: str
    score: float
    source: Literal["resume", "notes"] = "resume"


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    grounded: bool
    mode: Mode
    session_id: str
    suggestions: list[str] = Field(default_factory=list)


# ---------- ingest ----------
class NotesPayload(BaseModel):
    notes: str = Field(default="", max_length=20000)


class IngestResponse(BaseModel):
    filename: str
    characters: int
    chunks: int
    sections: list[str]
    embedder: str


class ProfileStatus(BaseModel):
    ready: bool
    filename: str | None
    chunks: int
    sections: list[str]
    note_sections: list[str] = Field(default_factory=list)
    has_notes: bool = False
    resume_downloadable: bool = False
    embedder: str
    llm_enabled: bool
    owner_name: str
    indexed_at: str | None


# ---------- JD matching ----------
class MatchRequest(BaseModel):
    job_description: str = Field(min_length=30, max_length=20000)
    job_title: str | None = None
    company: str | None = None


class RequirementVerdict(BaseModel):
    requirement: str
    category: Literal["must_have", "nice_to_have"]
    # Graded rather than binary: adjacent production experience and
    # actively-being-learned skills are real signal, not the same as nothing.
    status: Literal["match", "transferable", "partial", "learning", "missing"]
    evidence: str
    comment: str


class SkillAxis(BaseModel):
    """One spoke of the radar chart."""

    axis: str
    required: int  # 0-100, how heavily the JD weights it
    candidate: int  # 0-100, how well the resume covers it


class MatchResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    verdict: str
    summary: str
    # The candidate's case for an interview, written as advocacy rather than audit.
    pitch: str = ""
    ramp_up: str = ""
    requirements: list[RequirementVerdict]
    radar: list[SkillAxis]
    strengths: list[str]
    gaps: list[str]
    screening_questions: list[str]
    cover_letter: str
    job_title: str | None = None
    company: str | None = None


# ---------- screening pack ----------
class ScreeningAnswer(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)


class ScreeningPackResponse(BaseModel):
    owner_name: str
    answers: list[ScreeningAnswer]


# ---------- admin ----------
class QuestionStat(BaseModel):
    question: str
    mode: str
    asked_at: str
    grounded: bool


class LeadPayload(BaseModel):
    """Contact details a recruiter volunteers. Only `name` is required - a form
    that demands a phone number before answering anything just loses the lead."""

    name: str = Field(min_length=1, max_length=120)
    company: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=500)
    session_id: str | None = None


class Lead(BaseModel):
    id: int
    name: str
    company: str | None
    email: str | None
    phone: str | None
    role: str | None
    note: str | None
    created_at: str
    questions: list[str] = Field(default_factory=list)


class AnalyticsResponse(BaseModel):
    total_questions: int
    hr_questions: int
    visitor_questions: int
    ungrounded_questions: int
    total_sessions: int
    total_jd_matches: int
    total_leads: int = 0
    top_jd_titles: list[str]
    recent: list[QuestionStat]
