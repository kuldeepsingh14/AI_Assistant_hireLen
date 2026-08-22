"""Query expansion for lexical retrieval.

BM25 matches words, not meanings: a recruiter asking "what did they study?"
shares no vocabulary with a resume that says "Education / B.E. Computer Science".
Semantic embeddings solve this, but they are an optional dependency here, so the
lexical path gets a small hand-written bridge covering how people actually ask
about a resume. Expansion terms are appended, never substituted, so a query that
already matched keeps ranking the same way.
"""
from __future__ import annotations

import re

# trigger words -> resume vocabulary to add
_SYNONYMS: dict[str, str] = {
    # education
    "study": "education degree university college school academic bachelor master",
    "studied": "education degree university college school academic bachelor master",
    "studies": "education degree university college academic",
    "degree": "education university college bachelor master b.e b.tech m.tech bsc msc",
    "college": "education university institute school",
    "university": "education college institute",
    "school": "education university college",
    "graduate": "education degree university graduation",
    "graduation": "education degree university",
    "gpa": "education cgpa percentage marks grade",
    "academic": "education degree university college",
    "qualification": "education degree certification",
    "qualifications": "education degree certification",
    # experience
    "experience": "worked role position company employment engineer developer",
    "years": "experience present since worked",
    "career": "experience employment role position company",
    "background": "experience education summary profile",
    "worked": "experience role company position",
    "company": "experience employer organisation organization worked",
    "companies": "experience employer worked roles",
    "employer": "company experience worked",
    "job": "role position experience company",
    "jobs": "roles positions experience companies",
    "role": "position title engineer developer experience",
    "current": "present now latest recent",
    "recent": "present current latest",
    "senior": "lead principal staff experience",
    # skills
    "skill": "skills technologies languages frameworks tools stack",
    "skills": "technologies languages frameworks tools stack proficient",
    "tech": "technologies stack tools frameworks languages",
    "technologies": "skills stack tools frameworks languages",
    "stack": "technologies skills frameworks tools",
    "language": "languages python java javascript programming",
    "languages": "python java javascript typescript go programming",
    "framework": "frameworks library libraries",
    "tools": "technologies software platforms",
    "know": "skills experience proficient familiar",
    "expert": "skills proficient advanced strong",
    "proficient": "skills experienced strong",
    # projects / achievements
    "project": "projects built developed created application system tool",
    "projects": "built developed created application system portfolio",
    "built": "developed created project implemented designed",
    "build": "developed created project implemented",
    "portfolio": "projects work github",
    "achievement": "achievements awards honors accomplishments impact results",
    "achievements": "awards honors accomplishments impact recognized",
    "award": "awards honors recognition achievement",
    "impact": "results improved reduced increased achieved metrics",
    "proud": "achievements awards accomplishments best",
    "best": "top strongest achievements strongest",
    "opensource": "open source github contribution",
    "github": "open source projects repository",
    # certifications
    "certified": "certification certificate credential",
    "certification": "certifications certified certificate course training",
    "certifications": "certified certificate courses training",
    "course": "courses training certification",
    # contact / logistics
    "contact": "email phone linkedin github reach",
    "email": "contact reach mail",
    "phone": "contact mobile number call",
    "location": "based city address relocate contact",
    "based": "location city address",
    "linkedin": "contact profile links",
    # HR-flavoured questions
    "hire": "summary experience achievements skills impact strengths",
    "hiring": "summary experience achievements skills",
    "strength": "skills achievements experience strong expertise",
    "strengths": "skills achievements experience expertise",
    "weakness": "skills experience learning improving development",
    "fit": "skills experience match requirements",
    "leadership": "led lead managed mentored team ownership",
    "led": "leadership lead managed team owned",
    "team": "collaborated leadership led worked colleagues",
    "manage": "managed leadership led team ownership",
    "challenge": "problem solved difficult complex built",
    "problem": "solved challenge issue built fixed",
    "responsible": "responsibilities owned led role",
    "summary": "profile objective about overview",
    "overview": "summary profile about",
    "about": "summary profile overview background",
}

_WORD = re.compile(r"[a-z]+")


def expand(query: str, max_extra: int = 24) -> str:
    """Append resume-vocabulary synonyms for the recognised terms in `query`."""
    words = _WORD.findall(query.lower())
    if not words:
        return query

    present = set(words)
    extra: list[str] = []
    seen: set[str] = set()

    for word in words:
        for term in _SYNONYMS.get(word, "").split():
            # Adding a term already in the query would double-count it in BM25.
            if term not in present and term not in seen:
                seen.add(term)
                extra.append(term)
            if len(extra) >= max_extra:
                break
        if len(extra) >= max_extra:
            break

    return f"{query} {' '.join(extra)}" if extra else query
