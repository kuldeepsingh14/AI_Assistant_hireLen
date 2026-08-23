# Code walkthrough

The actual code, block by block, in the order a request travels through it.
Every snippet here is copied from the real files — if it differs from what you
see in the editor, the file is right and this is stale.

Companion to [`ARCHITECTURE.md`](ARCHITECTURE.md), which covers *what each file
is for*. This one covers *what each block does and why it is written that way*.

---

## Contents

1. [Configuration](#1-configuration) — one settings object
2. [Authorization](#2-authorization) — the owner guard
3. [Filename safety](#3-filename-safety) — untrusted input into a path
4. [Heading detection](#4-heading-detection) — guard-clause funnel
5. [BM25](#5-bm25) — the ranking formula
6. [Hybrid search](#6-hybrid-search) — the single most important block
7. [The empty-result fallback](#7-the-empty-result-fallback)
8. [Calling the model](#8-calling-the-model) — retries and rate limits
9. [Grounded answering](#9-grounded-answering) — the refusal token
10. [Pronoun rewriting](#10-pronoun-rewriting) — ambiguity resolution
11. [Deterministic scoring](#11-deterministic-scoring) — never trust the model with arithmetic
12. [Frontend: errors](#12-frontend-error-mapping)
13. [Frontend: shared state](#13-frontend-shared-state)
14. [Frontend: optimistic UI](#14-frontend-optimistic-ui)

---

## 1. Configuration

`backend/app/config.py`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_model_fast: str = "openai/gpt-oss-20b"
    embedder: str = "auto"
    allowed_origins: str = "http://localhost:4300,http://127.0.0.1:4300"
    admin_token: str = "change-me"
    owner_name: str = ""

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    ...
    return Settings()
```

**Reading it:**

- Each attribute is a typed field with a default. `pydantic-settings` fills it
  from an environment variable of the same name, uppercased — `groq_api_key`
  reads `GROQ_API_KEY`.
- Environment variables **win over** the `.env` file. That is what makes the
  same code work locally (file) and on Render (real env vars) with no branching.
- `origins` is a property, not a field. The env var arrives as one
  comma-separated string; the property is where it becomes a list. Parsing logic
  belongs next to the data, not at every call site.
- `@lru_cache` makes `get_settings()` a singleton — the file is read once, not
  on every request.

**The pattern:** centralised typed configuration. The alternative is
`os.getenv("GROQ_API_KEY")` scattered through the codebase, with no types, no
defaults, and no single place to see what's configurable.

---

## 2. Authorization

`backend/app/deps.py`

```python
async def require_owner(x_admin_token: str = Header(default="")) -> None:
    settings = get_settings()
    expected = settings.admin_token.strip()
    if not expected or expected == "change-me":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Owner actions are locked. Set ADMIN_TOKEN in backend/.env to something private.",
        )
    # compare_digest keeps the check constant-time against token guessing.
    if not hmac.compare_digest(x_admin_token.strip(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin token.")
```

**Reading it:**

- `Header(default="")` is FastAPI's dependency syntax. The parameter name
  `x_admin_token` maps to the `X-Admin-Token` header automatically.
- The first check **fails closed**. If nobody set a token, owner actions are
  *disabled* rather than open. A default of `"change-me"` that silently protected
  nothing would be worse than no auth at all, because it looks protected.
- `hmac.compare_digest` instead of `==`. A normal string comparison returns as
  soon as two characters differ, so `"a…"` fails fractionally faster than
  `"x…"` when the real token starts with `a`. Timing enough requests recovers
  the token one character at a time. `compare_digest` always takes the same time.

**Using it** — one line on the route, or on the whole router:

```python
@router.post("/upload", dependencies=[Depends(require_owner)])
```

**The pattern:** dependency injection for cross-cutting concerns. The route body
never mentions auth; it either runs or it never started.

---

## 3. Filename safety

`backend/app/services/extract.py`

An uploaded filename is attacker-controlled and gets joined onto a directory
path twice — once to store, once to serve.

```python
def safe_filename(filename: str, fallback: str = "resume") -> str:
    # Handle both separators regardless of host OS, plus Windows drive prefixes.
    base = re.split(r"[\\/]", filename.strip())[-1]
    base = re.sub(r"^[A-Za-z]:", "", base)

    stem, _, ext = base.rpartition(".")
    if not stem:  # no dot at all
        stem, ext = base, ""

    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._-")
    ext = re.sub(r"[^A-Za-z0-9]+", "", ext).lower()

    if not stem:
        stem = fallback
    stem = stem[:80]

    return f"{stem}.{ext}" if ext else stem
```

**Line by line:**

| Line | Does | Why |
| --- | --- | --- |
| `re.split(r"[\\/]", …)[-1]` | Keeps only the last path segment | `../../app/main.py` → `main.py`. Splits on **both** separators regardless of host OS |
| `re.sub(r"^[A-Za-z]:", …)` | Drops a Windows drive prefix | `C:evil.pdf` |
| `rpartition(".")` | Splits at the **last** dot | `my.resume.pdf` keeps `my.resume` as the stem |
| `[^A-Za-z0-9._ -]+` → `_` | Allow-list, not deny-list | You cannot enumerate every dangerous character; you *can* enumerate the safe ones |
| `.strip(" ._-")` | Removes leading/trailing junk | Stops `...` and hidden-file names |
| `stem[:80]` | Caps length | Filesystems have limits |

**A real bug this had.** The separator class was once `r"[\/]"` — forward slash
only, the backslash lost in an edit. Traversal was still blocked, because the
allow-list on the next line rewrites `\` to `_` and `.strip()` removes the
leading junk. But `C:\Windows\x.pdf` came out as `Windows_x.pdf` instead of
`x.pdf`.

That is **defense in depth** working as designed — one layer failed and the next
one held — but it is also why "the tests pass" isn't the same as "the code is
right". The test now pins the Windows case specifically.

---

## 4. Heading detection

`backend/app/services/chunk.py`

```python
def _match_heading(line: str) -> str | None:
    stripped = line.strip().strip(":").strip()
    if not stripped or len(stripped) > 45:
        return None
    # Headings are short, mostly letters, and rarely end in a sentence.
    if re.search(r"[.;,]$", stripped):
        return None
    words = stripped.split()
    if len(words) > 4:
        return None
    normalized = re.sub(r"[^a-z\s]", " ", stripped.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    for canonical, pattern in SECTION_PATTERNS:
        if re.fullmatch(pattern, normalized):
            return canonical
    return None
```

**Reading it:** this is a **guard-clause funnel**. Cheap rejections first,
expensive matching last.

1. Empty or over 45 characters → not a heading
2. Ends in `.`, `;`, `,` → that's a sentence
3. More than four words → that's prose
4. Normalise: lowercase, strip punctuation, collapse spaces — so `WORK
   EXPERIENCE:` and `Work Experience` both become `work experience`
5. Only now, try the patterns

`re.fullmatch`, not `re.search` — `search` would match "experience" inside
"Experience designing distributed systems", turning a bullet into a heading.

**The pattern:** normalise then match. Without step 4 you would need a pattern
for every capitalisation and punctuation variant.

---

## 5. BM25

`backend/app/services/bm25.py`

Two blocks. First, the index:

```python
df: Counter[str] = Counter()
for doc in self.docs:
    df.update(set(doc))
# +1 smoothing keeps idf positive even for terms present in every chunk.
self.idf = {
    term: math.log(1 + (self.n - count + 0.5) / (count + 0.5))
    for term, count in df.items()
}
```

`set(doc)` matters: document frequency counts *how many documents* contain a
term, not how many times. Without `set()`, a chunk repeating "Java" ten times
would count as ten documents.

`idf` is **inverse document frequency** — a term in every chunk carries no
information, a rare term carries a lot. The `+1` inside `log` keeps the result
positive; without it, a term appearing in every document gives a negative score
and actively pushes matching chunks *down*.

Then, scoring:

```python
for term in terms:
    tf = freq.get(term)
    if not tf:
        continue
    denom = tf + self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1))
    total += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
```

Three ideas in one expression:

- **`tf`** — more occurrences means more relevant…
- **…but with diminishing returns.** `tf / (tf + k1)` saturates. Ten mentions of
  "Java" is not ten times more relevant than one. `k1 = 1.5` controls how fast it
  flattens.
- **`length / avg_len`** — long chunks match more terms by chance. Dividing by
  relative length cancels that advantage. `b = 0.75` controls how strongly.

That is the whole algorithm. It fits in 61 lines and needs no dependencies,
which is why it works inside a 512 MB container.

---

## 6. Hybrid search

`backend/app/services/store.py` — **the most important block in the codebase.**

```python
def search(self, query: str, top_k: int = 6) -> list[Hit]:
    if not self.ready or not query.strip():
        return []

    rankings: list[list[int]] = []

    if self._bm25:
        # Expanded only for BM25: embeddings already capture the synonyms, and
        # padding a vector query with extra terms blurs it.
        lex = self._bm25.search(expand(query))
        if any(s > 0 for s in lex):
            rankings.append(sorted(range(len(lex)), key=lambda i: lex[i], reverse=True))

    if self._vectors is not None:
        qv = embed.encode([query], get_settings().embedder)
        if qv is not None:
            sims = (self._vectors @ qv[0]).tolist()
            rankings.append(sorted(range(len(sims)), key=lambda i: sims[i], reverse=True))

    if not rankings:
        return self._fallback(top_k)

    k = 60.0  # standard RRF damping
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)

    best = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    if not best:
        return self._fallback(top_k)
    ceiling = best[0][1] or 1.0
    # Normalize to 0-1 so the UI can show a meaningful relevance bar.
    return [Hit(chunk=self.chunks[i], score=round(s / ceiling, 4)) for i, s in best]
```

**Block by block:**

**Collect rankings, not scores.** Each retriever produces a list of chunk indices
ordered best-first. Note `sorted(range(len(lex)), key=…)` — it sorts *indices* by
their score, giving positions rather than values.

**Only BM25 gets the expanded query.** Embeddings already understand that
"study" relates to "education"; padding a vector query with twenty extra words
drags its position toward the average of all of them and makes it *less*
precise. Keyword search has no such understanding, so it needs the help.

**`self._vectors @ qv[0]`** — one matrix-vector product gives the cosine
similarity against every chunk at once, because both sides were L2-normalised at
encode time. For normalised vectors, dot product *is* cosine similarity.

**Reciprocal rank fusion** is the core idea:

```python
fused[idx] += 1.0 / (k + rank + 1)
```

Why not average the two scores? Because BM25 returns unbounded positives
(0 to ~15, depending on corpus) and cosine returns −1 to 1. Averaging them means
BM25 silently dominates. **Rank position is the only thing the two share.**

The contribution decays with rank, so being 1st matters much more than being
10th:

| Rank | Contribution |
| --- | --- |
| 1 | 1/61 = 0.0164 |
| 2 | 1/62 = 0.0161 |
| 10 | 1/70 = 0.0143 |
| 50 | 1/110 = 0.0091 |

`k = 60` is the constant from the original RRF paper. It damps the curve — with
a small `k`, first place would dominate so heavily that agreement between the
two retrievers stops mattering. A chunk ranked 3rd by *both* should beat a chunk
ranked 1st by one and 40th by the other, and `k = 60` is what makes that true.

**Normalising to 0–1 at the end** is purely for the UI: raw fused scores are
meaningless to a reader, but "this source is 100% / 84% / 61% relevant" drives a
bar.

---

## 7. The empty-result fallback

```python
def _fallback(self, top_k: int) -> list[Hit]:
    preferred = ("Summary", "Experience", "Skills", "Projects")
    ordered = sorted(
        self.chunks,
        key=lambda c: (preferred.index(c.section) if c.section in preferred else 99, c.order),
    )
    return [Hit(chunk=c, score=0.0) for c in ordered[:top_k]]
```

**Why this exists at all:** a language model handed an empty context does not say
"I don't know" — it produces the most statistically plausible résumé-shaped text,
which is a fabricated career. Returning *something* lets the model see real
content and correctly report that the answer isn't in it.

The sort key is a tuple: `(section_priority, original_order)`. Python compares
tuples left to right, so this sorts by section importance first and document
order within a section — in one expression, no grouping needed.

`score=0.0` is deliberate. The UI shows an empty relevance bar, honestly
signalling "nothing actually matched".

---

## 8. Calling the model

`backend/app/services/llm.py`

```python
if resp.status_code == 429:
    delay = _retry_delay(resp)
    # One automatic retry for a short cool-off, so a burst self-heals
    # instead of bouncing the user back with an error they can only fix by
    # waiting anyway.
    if not _retried and delay is not None and delay <= MAX_AUTO_RETRY_WAIT:
        log.info("Rate limited on %s; retrying in %.1fs", chosen, delay)
        await asyncio.sleep(delay + 0.5)
        return await complete(..., _retried=True)
    raise RateLimited(
        f"Groq's free tier allows a limited number of tokens per minute, and this "
        f"request went over. {_describe_wait(delay)}",
        delay,
    )
```

**Reading it:**

- `_retry_delay(resp)` reads the provider's **own** headers
  (`retry-after`, then `x-ratelimit-reset-tokens`) rather than guessing. Before
  this, the error said "wait a few seconds" when the real reset was a minute
  away — a message that is confidently wrong is worse than one that says nothing.
- The `_retried` flag is the recursion guard. Retry **once**; two 429s in a row
  means a real budget problem, not a burst, and looping would hang the request.
- `delay <= MAX_AUTO_RETRY_WAIT` (25 s) is the line between "wait for the user"
  and "tell the user". A job match already takes ~15 s, so a few more seconds
  beats making them click again. Two minutes does not.
- `RateLimited` subclasses `LLMUnavailable`, so callers that only care about
  "the model didn't work" catch the parent, while the router can catch the child
  to report a wait time.

And the defensive JSON parse:

```python
def parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = raw.find("{"), raw.rfind("}")
        candidate = raw[start : end + 1] if start != -1 and end > start else None
```

Three attempts, cheapest first: parse as-is; look for a fenced block; take
everything between the first `{` and the last `}`. Even in JSON mode, models
occasionally wrap output in prose. Failing the whole request over a stray
"Here's your JSON:" would be a bad trade.

---

## 9. Grounded answering

`backend/app/services/chat.py`

```python
prior = next((t.content for t in reversed(history) if t.role == "user"), "")
hits = index.search(f"{prior} {message}".strip(), settings.top_k)
if not hits:
    hits = index.search(message, settings.top_k)
```

**Why search on two turns:** "what about the second one?" contains no searchable
content. Prepending the previous question restores the subject. The fallback
line re-searches on the message alone in case the extra words hurt.

`next(…, "")` with a generator is the idiomatic "first match or default" —
no loop, no index errors.

```python
raw = await llm.complete(system, user_prompt, temperature=0.35, max_tokens=700)

grounded = NOT_FOUND not in raw
if not grounded:
    cleaned = raw.replace(NOT_FOUND, "").strip(" :-\n")
    text = cleaned or (
        f"{owner}'s resume doesn't cover that. Ask me about their experience, "
        "projects, or skills instead."
    )
    return pronouns.normalize(text, settings.owner_pronouns), [], False

# The prompt rule alone is not reliable, so enforce pronouns deterministically.
return pronouns.normalize(raw, settings.owner_pronouns), to_citations(hits), True
```

**The refusal token.** The system prompt instructs the model to emit
`NOT_IN_RESUME` when the context doesn't cover the question. This block detects
it, strips it, and returns `grounded=False` **with no citations** — because
citing sources for an answer you couldn't give would be actively misleading.

`cleaned or (default)` handles the model emitting the bare token with no
explanation.

**`temperature=0.35`** — low enough to stay factual, high enough not to read like
a form letter. Scoring calls use `0.0`, because there the same input must give
the same output.

---

## 10. Pronoun rewriting

`backend/app/services/pronouns.py`

The hard part isn't replacing words, it's that **"her" is two different words**:

```python
rest = m.string[m.end() :]
next_word = re.match(r"([A-Za-z']+)", rest)
following = next_word.group(1).lower() if next_word else ""
# No following word (end of sentence/clause) means it can't be a determiner.
determiner_position = bool(following) and following not in _NOT_A_NOUN_NEXT

...
elif lower == "her":
    # "her role" -> determiner; "gave it to her" -> object.
    out = poss_det if determiner_position else obj
```

- *"**her** role"* — possessive determiner → becomes *their*
- *"gave it to **her**"* — object pronoun → becomes *them*

The disambiguation is the **next word**. If a noun-ish word follows, it's
possessive. `_NOT_A_NOUN_NEXT` holds words that cannot start a noun phrase
(`the`, `and`, `to`, `with`…), so "her and I" is correctly read as an object.

Same block handles contractions:

```python
if subject == "they" and suffix == "s":
    suffix = "ve" if following in _PARTICIPLES else "re"
```

*"he's built"* → *"they've built"* (has), but *"he's interested"* → *"they're
interested"* (is). The following word decides which `'s` it was.

**Why this is code and not a prompt rule:** it was measured. Told to use
they/them, the model complied inconsistently — "she" in one answer, "they" in
the next, about the same person. Deterministic post-processing does not have
moods.

---

## 11. Deterministic scoring

`backend/app/services/jd_match.py`

```python
def _align_verdicts(requirements: list[dict], raw) -> list[RequirementVerdict]:
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
```

**The loop iterates over `requirements`, not over the model's reply.** That one
choice is the whole point:

- The model **drops** a requirement → it still appears, as `missing`
- The model **reorders** them → matched by text, not position
- The model **rewords** one → positional fallback catches it
- The model returns **garbage** → `isinstance` guards make it an empty dict

Why it matters: if a dropped requirement simply vanished, it would leave the
denominator too — and **dropping a hard requirement would raise the score**.
The most convenient failure would silently flatter the candidate.

`if status not in CREDIT: status = "missing"` — an unrecognised status becomes
the *harshest* value, not the most generous. Unknown input should never earn
credit.

Then the arithmetic:

```python
def _score(verdicts: list[RequirementVerdict]) -> int:
    total = sum(WEIGHTS[v.category] for v in verdicts)
    if not total:
        return 0
    earned = sum(WEIGHTS[v.category] * CREDIT[v.status] for v in verdicts)
    return int(round(100 * earned / total))
```

Ten lines. A weighted average, in Python, where you can read it.

**Why not ask the model for the score?** Because the same résumé and posting must
produce the same number twice, and because when a recruiter asks "why 71?" you
need to show the rows that produced it. A model-generated number is neither
reproducible nor explainable.

---

## 12. Frontend: error mapping

`frontend/src/app/core/api.service.ts`

```typescript
function toError(err: HttpErrorResponse) {
  let message = 'Something went wrong.';
  if (err.status === 0) {
    message =
      `No response from the API at ${environment.apiUrl}. The backend may be ` +
      `down, or the browser blocked this request. Check /api/health — it ` +
      `reports the origins the server accepts, which should include ` +
      `${location.origin}.`;
  } else if (typeof err.error?.detail === 'string') {
    message = err.error.detail;
  } else if (Array.isArray(err.error?.detail)) {
    message = err.error.detail.map((d: any) => d.msg ?? String(d)).join('; ');
  }
  return throwError(() => new Error(message));
}
```

**`status === 0` is the interesting case.** It means the response never arrived
*as far as JavaScript is concerned* — which covers a dead server, a refused CORS
origin, **and** a method missing from the CORS allow-list. The browser knows
which; it deliberately does not tell the page, because leaking that would itself
be an information disclosure.

An earlier version of this message blamed the origin specifically. That was
wrong once — the origin was fine and the missing piece was `PUT` in
`allow_methods` — and it sent a real debugging session down the wrong path for
twenty minutes. It now lists what to check instead of asserting a cause it
cannot know.

The two `detail` branches match FastAPI's two shapes: a string for
`HTTPException`, an array for validation errors.

---

## 13. Frontend: shared state

`frontend/src/app/core/profile.store.ts`

```typescript
@Injectable({ providedIn: 'root' })
export class ProfileStore {
  private readonly api = inject(ApiService);

  readonly profile = signal<ProfileStatus | null>(null);
  readonly ownerName = computed(() => this.profile()?.owner_name?.trim() || '');
  readonly ready = computed(() => this.profile()?.ready ?? false);

  refresh(): void {
    this.api.getProfile().subscribe({
      next: (p) => { this.profile.set(p); this.loaded.set(true); },
      error: () => this.loaded.set(true),
    });
  }
}
```

**`providedIn: 'root'`** makes it a singleton — every component that injects it
gets the same instance, which is what makes the state shared.

**`signal` for source data, `computed` for derived.** `ownerName` never gets
assigned; it recalculates when `profile` changes, and anything reading it
re-renders automatically. You cannot forget to update it, because you never
update it.

**The bug that caused this file to exist:** each component previously called
`getProfile()` in its own `ngOnInit`. The shell fetched at page load; the chat
fetched later. Upload a résumé mid-session and the header said "the candidate"
while the conversation said the real name — on the same screen. Two components,
two truths, no error anywhere.

---

## 14. Frontend: optimistic UI

`frontend/src/app/features/chat/chat.ts`

```typescript
// Snapshot the history *before* appending, so the backend doesn't see the
// question twice.
const history = this.messages()
  .filter((m) => !m.error && !m.pending)
  .slice(-6)
  .map((m) => ({ role: m.role, content: m.content }));

this.messages.update((m) => [
  ...m,
  { role: 'user', content: message },
  { role: 'assistant', content: '', pending: true },
]);
```

**Order matters.** The history is snapshotted *before* the new message is pushed.
Reversed, the backend would receive the question in both `message` and the last
history entry, and the model would see it asked twice.

**The filter is a correctness fix, not tidiness.** `error` bubbles hold error
text — sending "No response from the API…" as conversation history would have
the model try to interpret it as something the user said. `pending` bubbles are
empty placeholders.

**`slice(-6)`** caps context. Enough turns to resolve "what about that one?",
few enough to stay inside the token budget.

**Two messages are appended at once** — the real user message and an empty
assistant bubble marked `pending`. That placeholder is what renders the typing
dots. When the response lands:

```typescript
private replacePending(msg: ChatMessage): void {
  this.messages.update((list) => {
    const next = [...list];
    const i = next.findIndex((m) => m.pending);
    if (i >= 0) next[i] = msg;
    else next.push(msg);
    return next;
  });
}
```

It finds the placeholder and swaps it in place, so the answer appears where the
dots were rather than jumping to the bottom. The `else next.push(msg)` covers
the placeholder having been cleared mid-flight — the answer still arrives rather
than vanishing.

Note `[...list]` — signals compare by reference, so mutating the existing array
would not trigger a re-render. Every update returns a **new** array.

---

## The five ideas worth taking to another project

1. **Rank fusion beats score averaging** whenever you combine two retrievers.
   Scores from different systems are not comparable; positions are.
2. **Give the model an explicit way to refuse.** A token it can emit, which your
   code detects, beats hoping it says "I don't know" in prose you can parse.
3. **Iterate over your own list, not the model's reply.** Anything it dropped
   must still count, or the most convenient failure silently flatters the result.
4. **Compute anything a user might question.** If someone can ask "why that
   number?", the number belongs in code you can point at.
5. **Never let an error message assert a cause it cannot know.** `status === 0`
   has three possible causes and the browser hides which. Listing them beats
   guessing wrong.
