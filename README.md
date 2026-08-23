# HireLens

An AI assistant that answers questions about **one candidate**, using **only** that
candidate's resume — and can score any job description against it.

Two audiences, one profile:

- **Visitors** get a friendly tour of your work.
- **Recruiters** get a first-round phone screen: evidence-backed answers, a one-click
  screening pack, and a scored fit report for the role they're hiring for.

Everything runs on free tiers. No paid API, no vector database, no hosting bill.

---

> **New to the code?** [`ARCHITECTURE.md`](ARCHITECTURE.md) walks through
> every file: what it does, which pattern it implements, and what breaks
> without it — plus deployment, update flow, and how the two apps connect.

## What makes it more than a resume chatbot

| Feature | Why it matters |
| --- | --- |
| **Dual persona** | The same resume answers casually for a visitor and like a screening call for HR. One toggle. |
| **Citations on every answer** | Each reply shows the exact resume section it came from, with a relevance bar. A recruiter can verify a claim in one click. |
| **Refuses to invent** | If the resume doesn't cover it, the assistant says so instead of guessing. Salary, visa status, and personal details are hard-blocked. |
| **JD fit scoring** | Paste a posting → weighted score, per-requirement verdict with a supporting quote, radar chart, honest gap list, suggested screening questions, and a draft cover letter. |
| **Score you can defend** | Computed in Python from the verdicts on a graded rubric, not guessed by the model. You can point at any score and show exactly which requirements produced it. |
| **Advocates without lying** | Constructive band labels, gaps paired with the nearest bridge, and a written case for an interview — while the score itself stays untouched. Framing is the candidate's; the number is the evidence's. |
| **Screening pack** | One click answers the eight standard first-round questions and exports them as Markdown. |
| **Context beyond the resume** | A resume is a snapshot. Notes you maintain — job-search status, what you're learning, the role you want — are indexed alongside it and cited separately, so the assistant can answer what the document can't. |
| **HR can take the resume** | A download button in the header serves the original file, so a recruiter who likes the answers leaves with the actual document. |
| **Knows whose resume it is** | The name is read from the resume itself, so uploading a new one rebrands the whole assistant. No config edit, no chance of the UI saying one name while the resume says another. |
| **Uses your actual pronouns** | You declare them in config; a post-processing pass enforces them. Models infer gender from first names and get it wrong — this makes that impossible rather than unlikely. |
| **Recruiter capture** | In HR mode the assistant offers a contact card — name, company, email/phone, role they're hiring for. Optional and skippable, never a gate. Each contact is stored with the exact questions that person asked. |
| **Owner analytics** | See what recruiters actually asked — and which questions your resume *couldn't* answer. Those are the gaps to go fix. |

---

## Stack

| Layer | Choice | Cost |
| --- | --- | --- |
| Backend | FastAPI (Python 3.11) | free |
| Frontend | Angular 20 (standalone components + signals) | free |
| LLM | Groq — `openai/gpt-oss-120b`, with `gpt-oss-20b` for parsing | free tier |
| Retrieval | BM25 + query expansion, optional local `fastembed` vectors | free, no API |
| Storage | JSON index + SQLite | free |
| Charts | Hand-rolled SVG | no dependency |
| Hosting | Render (API) + Vercel (UI) | free tier |

---

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

cp .env.example .env
```

Edit `backend/.env`:

```ini
GROQ_API_KEY=gsk_...            # free key: https://console.groq.com/keys
ADMIN_TOKEN=pick-something-private
OWNER_PRONOUNS=they/them        # they/them | she/her | he/him
OWNER_NAME=                     # leave blank: read from the resume
```

Run it:

```bash
uvicorn app.main:app --reload --port 8001
```

API docs at <http://127.0.0.1:8001/docs>.

> Ports 8001 and 4300, rather than the usual 8000/4200, so this project never
> collides with anything else you have running locally.

### 2. Frontend

```bash
cd frontend
npm install
npm start                       # http://localhost:4300
```

### 3. Load your resume

The project ships with a sample resume already indexed (a fictional "Jane Doe"),
so the app works the moment you start it and you can see what it does before
wiring in your own details.

To make it yours: open <http://localhost:4300>, go to the **Owner** tab, enter your
`ADMIN_TOKEN`, and upload your resume (PDF, DOCX, TXT, or MD). That replaces the
sample, and the assistant picks up your name from the document automatically —
the Owner tab shows you which name it found.

Pronouns are the one thing that can't be read from a resume, so set
`OWNER_PRONOUNS` in `backend/.env` if `they/them` isn't right for you.

Upload and analytics are token-gated on purpose — otherwise any visitor to your
public portfolio could replace the resume the assistant speaks from.

---

## Retrieval: two modes

The assistant has to find the right part of your resume before it can answer.

**Default — `EMBEDDER=lexical`.** BM25 keyword search plus a hand-written synonym
map (`app/services/expand.py`) that bridges how people ask to how resumes are
written: *"what did they study?"* → `education degree university`. Zero downloads,
tiny memory footprint, works on any free tier.

**Better — `EMBEDDER=fastembed`.** Adds local semantic embeddings
(`BAAI/bge-small-en-v1.5`, ~130 MB, runs offline, still free). Results are fused
with BM25 via reciprocal rank fusion. Handles phrasings the synonym map never
anticipated.

```bash
pip install -r requirements-optional.txt
# then set EMBEDDER=fastembed in .env
```

`EMBEDDER=auto` uses fastembed when it's installed and silently falls back to
lexical when it isn't. **Render's free tier (512 MB RAM) cannot fit fastembed** —
keep `lexical` there.

---

## How the fit score is calculated

1. The JD is parsed into discrete requirements, each tagged `must_have` or `nice_to_have`.
2. Each requirement retrieves its own supporting evidence from the resume.
3. The model returns a verdict per requirement: `match` / `partial` / `missing`, plus a quote.
4. **Python computes the score** — the model never picks the number:

   ```
   weight: must_have = 3, nice_to_have = 1

   credit: match        = 1.00   clearly demonstrated
           transferable = 0.70   shipped production work in an adjacent technology
           partial      = 0.50   real but thin or unquantified evidence
           learning     = 0.35   actively learning it, per the owner's own notes
           missing      = 0.00   nothing supports it, adjacent or otherwise

   score = 100 × Σ(weight × credit) / Σ(weight)
   ```

   The rubric is graded rather than three-state on purpose. A binary
   match/missing scale gives a candidate moving between neighbouring stacks the
   same credit as someone with no relevant background at all — which is wrong,
   and understates almost anyone changing jobs. "transferable" requires a named
   adjacent technology that actually appears in the evidence; without one it is
   "missing".

Two guardrails worth knowing about:

- A verdict of `match` with **no supporting quote** is automatically demoted to `partial`.
  Confident-but-unevidenced claims are the exact failure this tool exists to catch.
- A requirement the model forgot to judge is counted as `missing`, not dropped —
  so nothing quietly disappears from the denominator to inflate the score.

Bands: 85+ Strong match · 70+ Good match · 55+ Solid fit, some ramp-up ·
35+ Stretch role, strong fundamentals · below that, Early-stage fit.

**On advocacy vs honesty.** This tool represents a candidate, so the *framing*
is deliberately on their side: band labels are constructive, gaps are phrased
with the nearest bridge, and every report carries a `pitch` arguing why the
candidate is worth interviewing anyway. What is never adjusted is the number.
The score is whatever the verdicts produce, and the report shows every verdict
that fed it. That is the whole reason a recruiter can trust it — a score that
flatters is a score nobody can rely on, and an overclaim a recruiter disproves
in one question costs the interview.

**On repeatability:** the arithmetic is fully deterministic — the same verdicts always
produce the same score, and you can audit which requirement contributed what. The
*verdicts* come from a language model at temperature 0, which is near-repeatable but
not guaranteed identical; expect a re-run to land within a few points rather than
exactly the same number. Treat the score as a well-evidenced signal, not a measurement.

---

## Free-tier rate limits

Groq's free tier is generous on requests (1,000/day) but tight on throughput:
**8,000 tokens per minute, counted per model**, and output tokens include the
model's hidden reasoning tokens.

A JD match is two calls and originally cost ~6,400 tokens — about **one match per
minute** before a 429. Three changes brought the main model's share down to
~3,200:

| Change | Effect |
| --- | --- |
| `reasoning_effort: "low"` on structured calls | Reasoning tokens fell sharply; a strict JSON schema already constrains the work |
| JD parsing moved to `GROQ_MODEL_FAST` (`gpt-oss-20b`) | Mechanical extraction, and it draws on a **separate** per-model budget |
| Tighter `max_tokens` and evidence caps | The 14k-char evidence cap was never being reached in practice |

Verified this does not soften the scoring: a deliberately mismatched senior JD
still scores 21/100 with 10 requirements missing, while a well-matched one scores
in the 90s. Lower reasoning effort made the evaluator faster, not friendlier.

**When a 429 still happens**, the wait comes from Groq's own
`x-ratelimit-reset-tokens` header rather than a guess, and a short cool-off
(≤25s) is retried automatically before the user ever sees an error. Token usage
and remaining budget are logged on every call:

```
openai/gpt-oss-20b:  569 prompt +  294 completion =  863 tokens
openai/gpt-oss-120b: 1821 prompt + 1381 completion = 3202 tokens (2800 left this minute)
```

If you still hit limits, the levers are: raise `GROQ_MODEL_FAST` usage, lower
`MAX_REQUIREMENTS` in `jd_match.py`, or add a paid Groq tier.

---

## API

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/health` | — | Liveness + capabilities |
| `GET` | `/api/profile` | — | Index status |
| `POST` | `/api/profile/upload` | owner | Upload & index a resume |
| `GET` | `/api/profile/resume` | — | Download the original resume file |
| `GET` | `/api/profile/notes` | owner | Read the context notes |
| `PUT` | `/api/profile/notes` | owner | Replace notes & re-index |
| `DELETE` | `/api/profile` | owner | Clear the index |
| `POST` | `/api/chat` | — | Ask a question |
| `GET` | `/api/chat/suggestions` | — | Suggested question chips |
| `POST` | `/api/chat/screening-pack` | — | Answer the 8 standard questions |
| `POST` | `/api/match` | — | Score a pasted JD |
| `POST` | `/api/match/upload` | — | Score an uploaded JD file |
| `POST` | `/api/leads` | — | Recruiter leaves contact details |
| `GET` | `/api/admin/analytics` | owner | Question log & stats |
| `DELETE` | `/api/admin/analytics` | owner | Clear question & match logs |
| `GET` | `/api/admin/leads` | owner | Recruiter contacts + their questions |
| `DELETE` | `/api/admin/leads` | owner | Delete all contacts |
| `DELETE` | `/api/admin/leads/{id}` | owner | Delete one contact |

Owner routes take the token in an `X-Admin-Token` header.

---

## Tests

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

145 tests cover parsing, section detection, chunking, query expansion, retrieval
targeting, pronoun enforcement, name detection, notes indexing, upload-filename
safety, CORS origin rules, and the scoring rules — including guards that no
status can ever be worth more than a real match, and that the graded credits
stay strictly ordered.

---

## Deploying free

**Backend → Render.** `render.yaml` is ready. Point Render at the repo, set
`GROQ_API_KEY` in the dashboard, and set `ALLOWED_ORIGINS` to your Vercel URL.

**Frontend → Vercel.** Put your Render URL in `frontend/src/environments/environment.prod.ts`,
then deploy; `vercel.json` handles the build and SPA routing.

Two things to know about the free tier:

- Render free instances **sleep after ~15 minutes idle**. The first request after
  that takes ~30 seconds. Fine for a portfolio; mention it if a recruiter is watching.
- Render's disk is **ephemeral**. A restart wipes the uploaded resume, so re-upload
  after a cold start — or commit your resume to `backend/data/resume/` and index it
  on boot if you'd rather not think about it.

---

## Project layout

```
backend/
  app/
    config.py            settings
    deps.py              owner-token guard
    models/schemas.py    request/response contracts
    routers/             health, profile, chat, match, admin
    services/
      extract.py         PDF/DOCX/TXT → text
      chunk.py           section-aware chunking
      bm25.py            keyword search
      expand.py          synonym bridge for lexical search
      embed.py           optional local vectors
      store.py           the index + hybrid retrieval
      llm.py             Groq client
      chat.py            personas + grounding rules
      identity.py        detects the owner's name from the resume
      pronouns.py        deterministic pronoun enforcement
      jd_match.py        JD parsing, evaluation, scoring
      analytics.py       SQLite question log
  tests/                 145 tests
frontend/
  src/app/
    core/                api client, models, markdown renderer
    shared/radar-chart   dependency-free SVG radar
    features/chat        dual-mode chat + screening pack
    features/match       JD matcher + fit report
    features/setup       owner console + analytics
```

---

## Context notes

The resume answers "what have they done". It cannot answer "are they looking?",
"what are they learning right now?", or "what role do they want next?" — the
questions a recruiter actually opens with.

So the admin console has a notes editor. Write free-form markdown; `## Headings`
become citable sections:

```markdown
## Job search
Actively looking for a switch and open to interviewing now.

## Currently learning
LLMs, RAG pipelines, LangChain and LangGraph for agentic workflows.

## What I want next
A backend or AI engineering role owning production systems end to end.
```

Notes are indexed **alongside** the resume in one search space, so a single
question can draw on both. Every chunk is tagged with its source, and the UI
labels each citation "résumé" or "own notes" — a recruiter can see which claims
come from the document and which are the candidate's own framing.

Re-uploading a resume keeps your notes. Clearing the profile removes both.

---

## How the name is detected

`identity.py` scans the first few lines for something shaped like a person's
name: 2–4 tokens, Title Case or ALL CAPS, no digits or contact punctuation. It
skips section headings (so "Professional Summary" isn't mistaken for a person)
and job titles (so "Senior Backend Engineer" isn't either), handles a name
sharing a line with contact details (`KULDEEP SINGH | Mumbai | +91…`), and strips
document labels like "Resume of". If no line convinces it, it falls back to a
two-part email local part (`kuldeep.singh@…` → "Kuldeep Singh"), rejecting
generic mailboxes like `info@`. When nothing is convincing it returns nothing
rather than guessing, and the app falls back to `OWNER_NAME` or "the candidate".

Set `OWNER_NAME` in `.env` to override detection — useful if you want a different
display name than the one on the document.

---

## Recruiter contacts

Switching to HR mode offers a contact card once per visit. It asks for a name,
company, email or phone, and the role being hired for. It is deliberately not a
gate — a recruiter who has to fill a form before getting an answer just closes
the tab — and "Not now" is remembered so it never nags.

Each contact is stored with the `session_id` of that conversation, so the admin
console shows a recruiter's details *and* the exact questions they asked. That
context is the point: knowing Meridian Digital asked about Kafka twice is worth
more than the email address alone.

**Clearing.** "Clear" on the activity panel wipes the question and match logs and
deliberately leaves contacts alone — a button labelled "clear log" should never
destroy inbound recruiters. Contacts have their own delete, individually or all
at once.

This is the one place the app stores other people's personal data. It never
leaves the local SQLite file, it is owner-gated on read, and it is deletable from
the console. If you deploy publicly, that is a privacy obligation you are taking
on — say so on the page if your jurisdiction expects it.

---

## Notes on safety

- The model is instructed to never invent an employer, title, date, degree, or metric,
  and to refuse questions about salary, visa status, age, or marital status unless
  those appear verbatim in the resume.
- Prompt-injection attempts in a pasted job description are ignored by an explicit rule.
- Model output is escaped before rendering; only a fixed tag whitelist is re-introduced,
  so nothing the model emits can become executable markup.
- Pronouns are enforced in code, not left to the prompt. During testing the model
  produced "they" for one question and "she" for the next on the same resume;
  prompt rules alone did not hold, so output is rewritten to the declared set.
- Uploaded filenames are flattened to a safe basename before being stored or
  served. Without that, a name like `../../app/main.py` would escape the data
  directory on write and on download.
- The resume download is deliberately public — that is the feature — so treat the
  contact details on your resume as published once you deploy.
- The owner token is compared in constant time.
