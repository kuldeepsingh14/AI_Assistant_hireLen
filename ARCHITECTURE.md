# HireLens — how it works, file by file

A reference for the whole system: what each file does, which pattern it
implements, and **what breaks if it isn't there**. That last part is the useful
one — it explains *why* the code is shaped the way it is, which is what you need
when someone asks you about this project.

Read the [Request lifecycle](#request-lifecycle) first. Everything else is detail
hanging off it.

For the code itself — real snippets, explained block by block — see
[`CODE_WALKTHROUGH.md`](CODE_WALKTHROUGH.md).

---

## 1. What the system is

One candidate's résumé, turned into something a recruiter can interrogate.

- **Ask** — a chat that answers only from the résumé and the owner's notes, and
  shows the exact source behind every claim.
- **Job match** — paste a job description, get a scored fit report with
  per-requirement evidence.
- **Admin** — the owner uploads the résumé, writes context notes, and sees who
  has been asking what.

The technical spine is **RAG** (retrieval-augmented generation): don't ask the
model what it knows, retrieve the relevant text first and make it answer from
that. Everything in `backend/app/services/` exists to make retrieval good and to
stop the model inventing things.

---

## 2. How frontend and backend connect

They are two separately deployed apps that share nothing but an HTTP contract.

```
Browser
  └── Angular SPA            (Vercel, static files)
        │
        │  HTTPS + JSON, cross-origin
        │  Authorization for owner routes: X-Admin-Token header
        ▼
      FastAPI                (Render, one Python process)
        │
        ├── in-memory index   (rebuilt on boot)
        ├── SQLite            (questions + recruiter contacts)
        └── Groq API          (the language model)
```

**Three things make that connection work, and each fails in a way that looks
like something else:**

| Mechanism | Where | If it's wrong you see |
| --- | --- | --- |
| `apiUrl` baked into the bundle at build time | `environment.prod.ts` | Requests go to `localhost` from a live site |
| CORS origin allow-list | `main.py` + `ALLOWED_ORIGINS` | "No response from the API" — looks like the backend is down |
| CORS method allow-list | `main.py` `allow_methods` | One feature fails while everything else works |

The second and third are the same class of trap: the browser blocks the request
and **deliberately hides the reason from JavaScript**, so the app can only say
"no response". That is why `/api/health` reports the origins it accepts — it
turns an invisible failure into a readable one.

> **Angular reads no environment variables at runtime.** The API URL is compiled
> into the JavaScript. Setting `API_BASE` in Vercel does nothing. To change the
> backend URL you edit `environment.prod.ts` and push.

---

## 3. Request lifecycle

One question, end to end. Follow this and the file list below makes sense.

```
1  User types "what did they study?" and hits Send
       chat.ts ask()

2  POST /api/chat  { message, mode, history, session_id }
       api.service.ts

3  routers/chat.py  →  services/chat.py answer()

4  RETRIEVE          store.search(query)
       ├── expand.py    "study" → + education, degree, university…
       ├── bm25.py      keyword scores over every chunk
       ├── embed.py     vector scores (only if fastembed installed)
       └── fuse         reciprocal rank fusion → top 6 chunks

5  PROMPT            chat.py builds the system + user message
       persona rules + the retrieved excerpts + last few turns

6  GENERATE          llm.py → Groq

7  CLEAN             pronouns.py normalise, detect NOT_IN_RESUME

8  LOG               analytics.py records the question (not the answer)

9  Response  { answer, citations[], grounded, suggestions[] }

10 chat.ts renders the bubble; citations collapse under "Show 4 sources"
```

**Step 4 is the whole game.** If retrieval returns the wrong chunks, the model
answers wrongly no matter how good the prompt is. Most of the backend is there
to make step 4 reliable.

---

## 4. Backend, file by file

`backend/app/` — FastAPI. Layered: **routers** (HTTP) → **services** (logic) →
no framework code in services, which is what makes them testable without a
server.

### Entry and configuration

#### `main.py` — 76 lines
Creates the FastAPI app, installs CORS, mounts routers, and runs the startup
sequence: init SQLite → restore the index from disk → seed if empty.

- **Pattern:** application factory + `lifespan` context manager.
- **Without it:** nothing runs.
- **The subtle part:** `allow_methods` must list every verb the routes use. Miss
  one and that feature fails *only in a browser* — `curl` doesn't send
  preflights, so tests and manual checks pass. `tests/test_cors.py` asserts the
  list covers every route, because this bug already happened once with `PUT`.

#### `config.py` — 67 lines
One `Settings` class (pydantic-settings) reading `.env` locally and real
environment variables in production. `@lru_cache` makes it a singleton.

- **Pattern:** typed, centralised configuration.
- **Without it:** `os.getenv` scattered everywhere, no types, no single place to
  see what's configurable.
- **Note:** `local_origin_regex` allows any `localhost:<port>` in development,
  because IDE preview panes use a port that changes every session. It is off in
  production via `ALLOW_LOCAL_ORIGINS=false`.

#### `deps.py` — 26 lines
`require_owner` — a FastAPI dependency guarding owner-only routes via the
`X-Admin-Token` header, compared with `hmac.compare_digest`.

- **Pattern:** dependency injection for authorization.
- **Without it:** any visitor could replace the résumé the assistant answers
  from, or read recruiters' contact details.
- **Why `compare_digest`:** a plain `==` returns faster on an early mismatch,
  which leaks the token one character at a time to anyone timing the responses.

#### `models/schemas.py` — 166 lines
Every request and response shape, as Pydantic models.

- **Pattern:** schema-first contracts. FastAPI validates input, serialises
  output, and generates `/docs` from these.
- **Without it:** malformed input reaches your logic, and the frontend's
  TypeScript types drift from reality with nothing to catch it.

---

### The retrieval pipeline

This is the part worth understanding. Each stage is a separate file so it can be
tested and swapped independently.

#### `services/extract.py` — 92 lines
Bytes → clean text. PDF via `pypdf`, DOCX via `python-docx`, plus plain text.
Strips page numbers and PDF ligature junk. Also `safe_filename()`.

- **Pattern:** adapter — one interface over several file formats.
- **Without it:** you can only accept plain text.
- **Security:** `safe_filename()` flattens `../../app/main.py` to `main.py`. An
  upload filename is attacker-controlled and gets joined onto a directory path,
  so without this an upload could write outside the data folder.

#### `services/chunk.py` — 212 lines
Splits text into retrievable pieces, **section-aware**: it detects résumé
headings (`EXPERIENCE`, `SKILLS`, …) and chunks inside them, so every chunk knows
which section it came from. `chunk_notes()` does the same for markdown headings.

- **Pattern:** semantic chunking (rather than fixed-size windows).
- **Without it:** you'd split every 500 characters, cutting bullets in half and
  producing citations that say "chunk 7" instead of "Experience".
- **Detail that matters:** chunks are prefixed `[Experience] …`, so the section
  name is visible to both the keyword search and the model.

#### `services/expand.py` — 127 lines
A hand-written synonym map. `"study"` → adds `education degree university…`

- **Pattern:** query expansion for lexical search.
- **Without it:** *"what did they study?"* returns **zero results** — the résumé
  says "Education" and "B.E. Computer Engineering", sharing no words with the
  question. This was a real bug found in testing; the map exists because the
  cheap embedder is optional.

#### `services/bm25.py` — 61 lines
Okapi BM25 from scratch — term frequency, inverse document frequency, length
normalisation. No dependencies.

- **Pattern:** classic lexical ranking.
- **Without it:** you'd need a vector model always loaded, which does not fit in
  Render's free 512 MB.
- **Why hand-written:** the corpus is one résumé. Pulling in Elasticsearch or a
  vector database for ~12 chunks would be absurd.

#### `services/embed.py` — 54 lines
Optional local embeddings via `fastembed`. Degrades to lexical-only if the
package isn't installed.

- **Pattern:** optional dependency with graceful degradation.
- **Without it:** search is keyword-only. Works, but synonyms depend entirely on
  `expand.py`.
- **Production note:** deliberately disabled on Render (`EMBEDDER=lexical`) —
  loading the ONNX model exceeds 512 MB and the worker is OOM-killed mid-request,
  which surfaces as a confusing 502.

#### `services/store.py` — 249 lines
The index itself: chunks, BM25, optional vectors, persistence, and **hybrid
search**.

```python
# Two rankings fused by reciprocal rank fusion
fused[i] += 1 / (60 + rank)
```

- **Pattern:** in-memory vector store + RRF hybrid retrieval.
- **Why RRF and not averaging scores:** BM25 scores are unbounded, cosine
  similarity is −1..1. Averaging them is meaningless. Ranks are the only thing
  the two have in common.
- **Without the `_fallback()`:** an unmatched query returns *nothing*, and a
  model handed an empty context invents an answer. The fallback returns a spread
  of the résumé so the model can say "that isn't covered".
- **Also here:** `owner_name` resolution, and `set_notes()` which re-indexes
  résumé and notes together.

#### `services/identity.py` — 151 lines
Detects whose résumé this is: scans the first lines for something name-shaped,
falls back to an email local part, returns `None` when unsure.

- **Pattern:** heuristic extraction with an explicit "don't know".
- **Without it:** you hardcode the name in config and the UI says "Jane Doe"
  while the résumé says something else.
- **The traps it dodges:** `"Professional Summary"` is two Title Case words;
  `"Senior Backend Engineer"` is three. Both are rejected by a heading check and
  a job-word list.

#### `services/seed.py` — 63 lines
On boot, if nothing is indexed, load `backend/data/seed/`.

- **Pattern:** idempotent bootstrap from committed content.
- **Without it:** every Render deploy wipes the disk and the site comes back
  empty until someone re-uploads by hand.
- **Never overwrites:** a live upload wins while the process is running.

---

### Generation

#### `services/llm.py` — 239 lines
The Groq client. Rate-limit handling, automatic retry, JSON-mode parsing.

- **Pattern:** provider adapter + typed errors (`LLMUnavailable`, `RateLimited`).
- **Without it:** `httpx` calls scattered through the services, and every caller
  re-implementing "what do I do about a 429".
- **The three token optimisations, and why:** free tier is 8,000 tokens/minute
  **per model**, and output includes hidden reasoning tokens. A JD match cost
  6,434 tokens → about one match per minute. Now:
  1. `reasoning_effort="low"` on JSON calls — the schema does the thinking
  2. JD parsing runs on the smaller model, which has a **separate budget**
  3. `max_tokens` sized to the actual response

  Main-model cost dropped to ~3,200 tokens.
- **`parse_json()`:** models sometimes wrap JSON in prose or a fence. It salvages
  the object rather than failing the request.

#### `services/chat.py` — 215 lines
The two personas and the grounding rules.

- **Pattern:** prompt templates with a shared hard-rules block.
- **The escape hatch:** the model is told to emit `NOT_IN_RESUME` when the
  context doesn't cover the question. The backend detects that token and returns
  `grounded: false`. **Without it** the model fills gaps with plausible fiction —
  the single worst failure mode for a tool that speaks to recruiters.
- **The advocacy rules:** HR mode leads with strengths, treats gaps as ramp-up,
  and answers seniority questions by stating tenure honestly *then* making the
  technical case. Framing is deliberate; fabrication is explicitly forbidden,
  because a recruiter disproves an overclaim in one question.

#### `services/pronouns.py` — 189 lines
Rewrites gendered pronouns to the owner's declared set, with verb agreement.

- **Pattern:** deterministic post-processing.
- **Without it:** the model infers gender from a first name and does it
  *inconsistently* — "she" in one answer, "they" in the next, for the same
  person. A prompt rule alone demonstrably does not hold.
- **Why a verb whitelist:** a general "strip the -s" rule would turn "their
  skills" into "their skill".

#### `services/jd_match.py` — 366 lines
Job-description matching. Two LLM calls, then **deterministic scoring in
Python**.

```
weight: must_have 3, nice_to_have 1
credit: match 1.0 | transferable 0.7 | partial 0.5 | learning 0.35 | missing 0.0
score = 100 × Σ(weight × credit) / Σ(weight)
```

- **Pattern:** LLM for judgement, code for arithmetic.
- **Why the score isn't asked of the model:** the same résumé and JD must produce
  the same number, and you must be able to point at any score and show which
  requirements produced it. A model-generated number is neither.
- **`_align_verdicts()`:** the model sometimes drops or rewrites requirements.
  This re-aligns its output against the real list, and anything it failed to
  judge counts as *missing* rather than silently vanishing from the denominator —
  otherwise dropping a requirement would *raise* the score.
- **A claimed match with no evidence quote is demoted to partial.** That's the
  exact failure this tool exists to prevent.

#### `services/analytics.py` — 209 lines
SQLite. Logs questions (not answers) and stores recruiter contacts.

- **Pattern:** repository over `sqlite3`, single-writer lock.
- **Without it:** no idea which questions the résumé fails to answer.
- **Deliberate:** `clear_activity()` wipes questions and matches but **leaves
  contacts alone** — a button labelled "Clear" must not destroy someone's inbound
  recruiters.

---

### Routers — thin HTTP wrappers

| File | Routes | Notes |
| --- | --- | --- |
| `health.py` | `GET /api/health` | Also reports the CORS origins it loaded — the diagnostic that makes an invisible failure visible |
| `profile.py` | profile, upload, notes, résumé download | Upload and notes are owner-gated; download is public on purpose |
| `chat.py` | chat, suggestions, screening pack | The pack is 8 sequential calls — parallel bursts hit the rate limit |
| `match.py` | match, match/upload | |
| `leads.py` | `POST /api/leads` | Public write, owner-only read |
| `admin.py` | analytics, leads, clears | Entire router gated by `require_owner` |

**Pattern:** routers validate, call one service, translate exceptions to HTTP
status codes. No business logic. That is why 153 tests run without starting a
server.

---

## 5. Frontend, file by file

`frontend/src/app/` — Angular 20, standalone components, **signals** for state.
No NgModules, no NgRx.

### Core

#### `core/models.ts` — 149 lines
TypeScript mirrors of the Pydantic schemas.

- **Without it:** `any` everywhere, and a backend rename becomes a runtime crash
  instead of a compile error.
- **Discipline:** when you change `schemas.py`, change this in the same commit.

#### `core/api.service.ts` — 193 lines
Every HTTP call, in one place. Attaches the admin token; converts errors to
readable messages.

- **Pattern:** single API gateway service.
- **Without it:** URL strings scattered across components, and error handling
  rewritten in each.
- **`toError()`:** FastAPI puts the human-readable reason in `detail`. This
  surfaces that instead of "500". For `status === 0` it names *both* possible
  causes, because the browser refuses to say which.

#### `core/profile.store.ts` — 44 lines
One shared copy of the profile.

- **Pattern:** a tiny signal store — the lightest thing that solves it.
- **Without it (this actually happened):** each component fetched its own copy on
  init, so the header showed "the candidate" from page load while the chat showed
  the real name from a later fetch. Same screen, two truths.

#### `core/markdown.ts` — 85 lines
Model output → HTML.

- **Pattern:** escape-first rendering with a tag whitelist.
- **Without it:** you either lose formatting, or pass model output through
  `innerHTML` and trust it not to contain a `<script>`. This escapes everything
  first and then re-adds only bold, lists, code, headings.

### Features

| Component | Lines | Responsibility |
| --- | --- | --- |
| `app.ts` / `.html` | 164 / 125 | Shell: tabs, theme, welcome intro, résumé download |
| `features/chat/` | 322 | Chat, mode switch, citations, screening pack, contact capture |
| `features/match/` | 192 | JD form, score ring, requirement breakdown, export |
| `features/setup/` | 319 | Admin: unlock, upload, notes, analytics, contacts |
| `shared/radar-chart.ts` | 257 | Hand-built SVG radar |

**Why a hand-built chart:** a charting library is ~100 KB for one diagram, and
inline SVG themes correctly with CSS variables for free.

**Layout rule learned the hard way** — in `chat.css`, `.messages` needs
`min-height: 0`. A flex item defaults to `min-height: auto` and refuses to shrink
below its content, so the scroll pane never scrolls; instead the column overflows
and the rows below spill onto the footer.

### Styling

`styles.css` (315 lines) holds the design tokens. Both themes are defined on the
same hue axis, and every text/background pair was checked against WCAG AA.

The theme resolves in a tiny inline script in `index.html` **before first paint**
— otherwise the page flashes the wrong palette while Angular boots. Three states:
auto (follow device), light, dark. Auto stores nothing, which is what lets a
later OS change take effect.

---

## 6. Data and storage

| What | Where | Survives a redeploy? |
| --- | --- | --- |
| Résumé + notes (seeded) | `backend/data/seed/` (in git) | **Yes** |
| Uploaded résumé file | `backend/data/resume/` | No |
| Built index | `backend/data/index/` | No — rebuilt from seed |
| Questions + contacts | `backend/data/analytics.db` | **No** |
| API keys | environment variables | n/a |

Render's free disk is ephemeral. The seed folder is the answer: committed
content, indexed on boot. Because this repo is **public**, the committed résumé
is a contact-free copy — phone and email stripped.

---

## 7. Deployment

### How it is deployed

| Piece | Host | Reads |
| --- | --- | --- |
| Backend | Render (free web service) | `render.yaml` at the repo root |
| Frontend | Vercel (hobby) | Root Directory `frontend`, `frontend/vercel.json` |
| Keep-alive | GitHub Actions | `.github/workflows/keep-alive.yml` |

Both deploy from the **same repository**. Render is told `rootDir: backend`, so
you point it at the whole repo, not a subfolder.

### Updating

**Any code change is the same three steps:**

```bash
git add -A
git commit -m "what changed and why"
git push
```

Both hosts watch `main` and redeploy automatically. Backend ~60–90 s, frontend
~40 s.

**Know what a push costs you:** every push redeploys Render, which wipes the
disk. Seeded content comes back; the uploaded PDF and the analytics database do
not.

**Changing the backend URL** is a code change (`environment.prod.ts`), not a
Vercel setting.

**Changing configuration** — `GROQ_API_KEY`, `ALLOWED_ORIGINS`, `OWNER_NAME`,
`OWNER_PRONOUNS` — is done in Render → Environment. Saving restarts the service;
no push needed.

### When something breaks

| Symptom | Almost always | Check |
| --- | --- | --- |
| "No response from the API" | Origin not allowed | `/api/health` → `allowed_origins` |
| One feature fails, others fine | Method missing from CORS | `allow_methods` in `main.py` |
| 503 on chat | Key rejected or rate limit | The `detail` message says which |
| Site says "being set up" | Nothing indexed | `/api/health` → `resume_indexed` |
| First visit takes ~50 s | Render slept | Set the `API_URL` repo variable |

`/api/health` answers most of these without opening a dashboard.

---

## 8. If you were building this again

The order that would have saved the most time:

**1. Make retrieval work before touching the model.**
Extract → chunk → search, with a script that prints the top hits for ten real
questions. Retrieval quality sets the ceiling on answer quality; no prompt
rescues bad chunks. The `"what did they study?"` bug — zero results — was found
this way, before any prompt existed.

**2. Put the logic in services, not routes.**
The 153 tests run in ~3 seconds without a server because nothing important
depends on FastAPI. If it needs an HTTP client to test, it's in the wrong layer.

**3. Decide what the model is *not* allowed to do, early.**
Here: no inventing facts, no arithmetic, no pronoun guessing. Each became code —
the `NOT_IN_RESUME` token, Python scoring, `pronouns.py`. **Prompt rules alone do
not hold**, which was measured, not assumed.

**4. Compute anything a user might question.**
Scores are arithmetic over verdicts. When someone asks "why 71?", you show the
table. A model-generated number can't be defended.

**5. Handle the free tier as a design constraint.**
512 MB rules out loaded models. 8,000 tokens/min shapes how many calls a feature
can make. An ephemeral disk means anything that must survive has to be in git or
a database.

**6. Make invisible failures visible.**
Two full debugging sessions went into CORS problems that presented as "the
backend is down". `/api/health` now reports its own CORS config. Any state that
can silently break a request should be readable from outside.

**7. Write the test when you fix the bug.**
`PUT` missing from CORS passed every server-side test and failed only in a
browser. The test that now guards it reads the app's own routes, so a new
endpoint can't reintroduce it.

### A reasonable build order

1. Extraction + chunking, verified by eye
2. Search, verified against real questions
3. One endpoint, one prompt, grounded answers with citations
4. A UI thin enough to prove the API
5. Second feature (JD matching) reusing the same retrieval
6. Deploy early on the real free tier — its limits change your design
7. Polish: theme, layout, empty states, error messages

Deploying early matters more than it sounds. Half the interesting decisions in
this codebase — lexical embeddings, seeding, token budgets, CORS diagnostics —
came from meeting the free tier, not from planning.
