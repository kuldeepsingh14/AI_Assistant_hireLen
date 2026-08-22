"""Score a job description against the indexed resume.

Two LLM calls, then a deterministic score. The arithmetic is done in Python on
purpose: a recruiter can be told exactly how the number was produced, and the
same resume + JD always yields the same score.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..models.schemas import MatchResponse, RequirementVerdict, SkillAxis
from . import llm, pronouns
from .store import index

log = logging.getLogger(__name__)

WEIGHTS = {"must_have": 3.0, "nice_to_have": 1.0}

# Graded credit. A three-state rubric scored adjacent production experience the
# same as no experience at all, which understates any candidate moving between
# neighbouring stacks - the normal case for a switch. Each step is defensible on
# its own terms, and the report shows which step every requirement landed on.
CREDIT = {
    "match": 1.0,          # clearly demonstrated in the evidence
    "transferable": 0.7,   # production experience in a directly adjacent technology
    "partial": 0.5,        # some evidence, but thin or unquantified
    "learning": 0.35,      # actively learning it per their own notes, not yet shipped
    "missing": 0.0,        # nothing supports it
}

MAX_REQUIREMENTS = 14
MAX_AXES = 6

_PARSE_SYSTEM = """
You are a technical recruiter breaking a job description into checkable requirements.

Return JSON only, shaped exactly like:
{
  "job_title": string or null,
  "company": string or null,
  "requirements": [
    {"requirement": "concise, checkable phrasing (max 90 chars)",
     "category": "must_have" | "nice_to_have"}
  ],
  "axes": [
    {"axis": "short skill-area label (max 22 chars)", "required": 0-100}
  ]
}

Rules:
- Extract at most 14 requirements. Merge duplicates. One capability each.
- "must_have" = stated as required/essential/minimum. Everything else is nice_to_have.
- Skip generic filler ("team player", "good communication") unless the JD stresses it.
- "axes" = 4 to 6 broad skill areas this role is built on (e.g. "Backend", "Cloud
  & DevOps", "Data/ML", "Frontend"). "required" is how heavily the JD weights that
  area, 0-100. Axes must be derived from the JD, not from a fixed list.
""".strip()

_EVAL_SYSTEM = """
You are evaluating one candidate's resume against a parsed job specification, the
way an honest hiring manager would.

You are evaluating fairly, not pedantically. Adjacent production experience is
real evidence that someone can do the job; treat it as such. You are also not a
salesperson - a claim a recruiter can disprove in one question costs the
candidate the interview.

Return JSON only, shaped exactly like:
{
  "verdicts": [
    {"requirement": "<copied verbatim from the input list>",
     "status": "match" | "transferable" | "partial" | "learning" | "missing",
     "evidence": "<short quote or close paraphrase from the EVIDENCE, empty string if missing>",
     "comment": "<one sentence, max 140 chars, explaining the call>"}
  ],
  "axes": [{"axis": "<copied verbatim from the input axes>", "candidate": 0-100}],
  "strengths": ["3-5 specific strengths for THIS role, each max 110 chars"],
  "gaps": ["2-4 gaps, each phrased as the gap AND the nearest bridge, max 140 chars"],
  "screening_questions": ["4-6 questions a recruiter should ask"],
  "pitch": "<70-110 words: the case for interviewing this candidate anyway. Lead
             with what they have proven, then treat the gaps as ramp-up with a
             concrete reason to believe - adjacent experience, evidence of
             learning fast, or something they are already studying.>",
  "ramp_up": "<one sentence: realistically, what would it take for them to be
               fully productive in this role?>",
  "cover_letter": "<160-220 word first-person cover letter from the candidate>"
}

Choosing a status:
- "match"        - the evidence clearly demonstrates this requirement.
- "transferable" - they have not used this exact tool, but have shipped
                   production work in a directly adjacent one (e.g. RabbitMQ for
                   a Kafka requirement; Spring Boot REST for a FastAPI one; one
                   cloud provider for another). Say which in the comment.
- "partial"      - some genuine evidence, but thin, unquantified, or peripheral.
- "learning"     - their own notes say they are actively learning it. Never infer
                   this from the resume; it must be stated in their notes.
- "missing"      - nothing in the evidence supports it, adjacent or otherwise.

Rules:
- Return exactly one verdict per input requirement, in the same order.
- Evidence must be traceable to the EVIDENCE text. Never invent a project,
  employer, metric, year, or technology. Inventing one is worse than "missing".
- "transferable" needs a named adjacent technology that actually appears in the
  evidence. Without one, it is "missing".
- Years of experience are a fact: never round them up or call a shortfall a match.
- Gaps stay honest, but each should point at the nearest real bridge. A report
  with no gaps is not credible, and a recruiter will trust the rest of it less.
- The cover letter uses only evidence-backed facts and claims nothing marked
  missing.
""".strip()


async def match(job_description: str, job_title: str | None, company: str | None) -> MatchResponse:
    if not index.ready:
        raise ValueError("Upload a resume before running a job-description match.")

    spec = await _parse_jd(job_description)
    requirements = spec["requirements"][:MAX_REQUIREMENTS]
    axes = spec["axes"][:MAX_AXES]

    evidence = _gather_evidence(requirements, job_description)
    evaluation = await _evaluate(requirements, axes, evidence)

    verdicts = _align_verdicts(requirements, evaluation.get("verdicts", []))
    score = _score(verdicts)

    # Every free-text field here is model-written prose about a real person, so
    # it needs the same pronoun enforcement the chat answers get. Without this
    # the report happily says "he" for a candidate who uses they/them.
    who = get_settings().owner_pronouns
    fix = lambda text: pronouns.normalize(text, who)

    return MatchResponse(
        score=score,
        verdict=_band(score),
        summary=_summary(score, verdicts, spec.get("job_title") or job_title),
        requirements=[_fix_verdict(v, fix) for v in verdicts],
        radar=_radar(axes, evaluation.get("axes", [])),
        strengths=[fix(x) for x in _strings(evaluation.get("strengths"), 5)],
        gaps=[fix(x) for x in _strings(evaluation.get("gaps"), 5)],
        screening_questions=[
            fix(x) for x in _strings(evaluation.get("screening_questions"), 6)
        ],
        pitch=fix(str(evaluation.get("pitch") or "").strip()),
        ramp_up=fix(str(evaluation.get("ramp_up") or "").strip()),
        cover_letter=fix(str(evaluation.get("cover_letter") or "").strip()),
        job_title=spec.get("job_title") or job_title,
        company=spec.get("company") or company,
    )


# ---------- step 1: parse the JD ----------
async def _parse_jd(job_description: str) -> dict:
    # Splitting a JD into requirements is mechanical extraction, so it runs on the
    # smaller model: fewer tokens, and it draws on a separate rate-limit budget,
    # leaving the main model's budget for the judgement call that follows.
    data = await llm.complete_json(
        _PARSE_SYSTEM,
        f"JOB DESCRIPTION:\n{job_description[:9000]}",
        max_tokens=1400,
        model=get_settings().groq_model_fast,
    )
    requirements = []
    for item in data.get("requirements") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("requirement", "")).strip()
        if not text:
            continue
        category = item.get("category")
        requirements.append(
            {
                "requirement": text[:160],
                "category": category if category in WEIGHTS else "nice_to_have",
            }
        )
    if not requirements:
        raise ValueError(
            "No concrete requirements could be read from that job description. "
            "Paste the full posting, including the responsibilities and qualifications."
        )

    axes = []
    for item in data.get("axes") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("axis", "")).strip()
        if label:
            axes.append({"axis": label[:22], "required": _clamp(item.get("required"), 60)})
    if not axes:
        axes = [{"axis": "Overall fit", "required": 100}]

    return {
        "job_title": _opt_str(data.get("job_title")),
        "company": _opt_str(data.get("company")),
        "requirements": requirements,
        "axes": axes,
    }


# ---------- step 2: retrieve evidence per requirement ----------
def _gather_evidence(requirements: list[dict], job_description: str) -> str:
    """Union of the top chunks for each requirement, so the evaluator sees the
    parts of the resume that actually bear on this role rather than the whole file."""
    settings = get_settings()
    picked: dict[str, tuple[float, str]] = {}

    for req in requirements:
        for hit in index.search(req["requirement"], 3):
            key = hit.chunk.chunk_id
            if key not in picked or hit.score > picked[key][0]:
                picked[key] = (hit.score, hit.chunk.text)

    # Also pull chunks matching the JD as a whole, to catch context no single
    # requirement phrase retrieves.
    for hit in index.search(job_description[:1500], settings.top_k):
        picked.setdefault(hit.chunk.chunk_id, (hit.score, hit.chunk.text))

    if not picked:
        return index.full_text[:7000]

    ordered = sorted(picked.items(), key=lambda kv: kv[0])
    body = "\n\n".join(text for _, (_, text) in ordered)
    return body[:9000]


# ---------- step 3: evaluate ----------
async def _evaluate(requirements: list[dict], axes: list[dict], evidence: str) -> dict:
    req_lines = "\n".join(
        f"{i + 1}. [{r['category']}] {r['requirement']}" for i, r in enumerate(requirements)
    )
    axis_lines = "\n".join(f"- {a['axis']}" for a in axes)
    prompt = (
        f"REQUIREMENTS TO EVALUATE (one verdict each, same order):\n{req_lines}\n\n"
        f"SKILL AXES TO SCORE:\n{axis_lines}\n\n"
        f"RESUME EVIDENCE:\n{evidence}"
    )
    return await llm.complete_json(_EVAL_SYSTEM, prompt, max_tokens=2600)


# ---------- deterministic scoring ----------
def _align_verdicts(requirements: list[dict], raw) -> list[RequirementVerdict]:
    """Trust the requirement list, not the model's echo of it.

    The model sometimes drops, reorders, or rewrites entries; anything it failed to
    judge is counted as missing rather than silently disappearing from the score.
    """
    items = raw if isinstance(raw, list) else []
    by_text = {
        str(item.get("requirement", "")).strip().lower(): item
        for item in items
        if isinstance(item, dict)
    }

    verdicts: list[RequirementVerdict] = []
    for i, req in enumerate(requirements):
        item = by_text.get(req["requirement"].strip().lower())
        if item is None and i < len(items) and isinstance(items[i], dict):
            item = items[i]  # positional fallback when the text was reworded
        item = item or {}

        status = item.get("status")
        if status not in CREDIT:
            status = "missing"
        evidence = str(item.get("evidence") or "").strip()
        if status != "missing" and not evidence:
            # A claimed match with no evidence is exactly the failure mode this
            # tool exists to prevent, so demote it.
            status = "partial"
        comment = str(item.get("comment") or "").strip()[:200]
        verdicts.append(
            RequirementVerdict(
                requirement=req["requirement"],
                category=req["category"],
                status=status,
                evidence=evidence[:400],
                comment=comment or "No supporting evidence found in the resume.",
            )
        )
    return verdicts


def _fix_verdict(v: RequirementVerdict, fix) -> RequirementVerdict:
    """Normalize the prose on a verdict, leaving the status and weighting alone."""
    return v.model_copy(update={"comment": fix(v.comment), "evidence": fix(v.evidence)})


def _score(verdicts: list[RequirementVerdict]) -> int:
    total = sum(WEIGHTS[v.category] for v in verdicts)
    if not total:
        return 0
    earned = sum(WEIGHTS[v.category] * CREDIT[v.status] for v in verdicts)
    return int(round(100 * earned / total))


def _band(score: int) -> str:
    """Label for a score.

    The wording is deliberately constructive - a mid score is a candidate worth
    a conversation, not a rejection - but the wording is the only thing that
    changes. The number underneath is whatever the verdicts produced.
    """
    if score >= 85:
        return "Strong match"
    if score >= 70:
        return "Good match"
    if score >= 55:
        return "Solid fit, some ramp-up"
    if score >= 35:
        return "Stretch role, strong fundamentals"
    return "Early-stage fit"


def _summary(score: int, verdicts: list[RequirementVerdict], title: str | None) -> str:
    musts = [v for v in verdicts if v.category == "must_have"]
    met = sum(1 for v in musts if v.status == "match")
    covered = sum(1 for v in musts if v.status in ("match", "transferable", "partial"))
    role = f"the {title} role" if title else "this role"

    lead = (
        f"{_band(score)} for {role} at {score}/100. "
        f"{met} of {len(musts)} must-haves are directly evidenced"
    )
    # Adjacent coverage is the difference between "half the list" and "half the
    # list, plus neighbouring experience on most of the rest".
    if covered > met:
        lead += f", with {covered - met} more covered by adjacent or partial experience"
    return lead + f", across {len(verdicts)} requirements checked."


def _radar(axes: list[dict], scored) -> list[SkillAxis]:
    got = {}
    for item in scored if isinstance(scored, list) else []:
        if isinstance(item, dict):
            got[str(item.get("axis", "")).strip().lower()] = item.get("candidate")
    return [
        SkillAxis(
            axis=a["axis"],
            required=a["required"],
            candidate=_clamp(got.get(a["axis"].strip().lower()), 0),
        )
        for a in axes
    ]


# ---------- small helpers ----------
def _clamp(value, default: int) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _opt_str(value) -> str | None:
    text = str(value).strip() if value else ""
    if not text or text.lower() in ("null", "none", "n/a"):
        return None
    return text[:120]


def _strings(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip()[:200] for v in value if str(v).strip()][:limit]
