# GuruAI Architecture — a guided walkthrough

This document exists to be read **alongside the code**, not instead of it. It
follows one chat request from the browser all the way to the streamed answer and
back, opening each file at the moment the request reaches it. By the end you'll
have touched every hard part of the system — auth, retrieval, CRAG, the LLM
chain, and mastery tracking — in the order the code actually runs them.


## The 10,000-foot shape

```
Browser (static/*.html, vanilla JS)
   │  fetch() / EventSource
   ▼
server.py                     ← wires 11 routers together, ~60 lines, no logic
   │
   ├── src/api/routers/*      ← HTTP handlers, one file per feature area
   │      │
   │      ├── src/api/deps.py            ← auth: "who is this, and is it theirs?"
   │      ├── src/sessions/*             ← read/write sessions, messages, documents
   │      ├── src/personalization/*      ← mastery (EMA) + spaced repetition
   │      └── src/rag/*                  ← retrieval, CRAG grading, the answer chain
   │
   ├── PostgreSQL (DATABASE_URL) ← all durable state
   └── pgvector (document_chunks) ← chunk embeddings, queried via cosine distance
```

Two external LLMs do the thinking:
- **Groq / Llama 3.3** — writes answers and quizzes ([src/core/llm.py](../src/core/llm.py))
- **Google Gemini Flash** — the CRAG relevance grader ([src/rag/crag.py](../src/rag/crag.py))

Everything else is plumbing you can fully understand.

---

## The layers, and the one rule that keeps them honest

The refactor split the code into four layers. The rule is: **each layer only
calls the one below it.**

| Layer | Lives in | Knows about | Does NOT know about |
|-------|----------|-------------|---------------------|
| HTTP | `src/api/routers/` | requests, cookies, status codes | SQL, pgvector internals |
| Domain | `src/sessions/`, `src/personalization/` | SQL rows, business rules | HTTP, LLMs |
| RAG | `src/rag/` | pgvector, LLM chains, prompts | HTTP, the Postgres schema |
| Infra | `src/core/`, `src/auth/` | DB connections, model singletons, tokens | everything above |

When you read a router and it looks thin — good, it's supposed to. The logic
lives one layer down where it can be tested without a web server.

---

## Walkthrough: one chat request, end to end

Open [src/api/routers/chat.py](../src/api/routers/chat.py) and keep it in front of
you. Everything below traces the `chat()` function in that file, top to bottom.

### 0. The browser sends the question

`static/index.html` POSTs `{session_id, question}` to `/api/chat` and opens the
response as a stream. It expects Server-Sent Events: many `{"chunk": "..."}`
frames, then one `{"sources": [...]}` frame, then `[DONE]`.

### 1. "Who is this?" — authentication

```python
def chat(req: ChatRequest, user_id: int = Depends(get_current_user)):
```

That `Depends(get_current_user)` is FastAPI's dependency injection. Before your
handler body runs, FastAPI calls
[`get_current_user`](../src/api/deps.py) in `deps.py`, which:
1. reads the `access_token` cookie,
2. verifies its HMAC signature via [`verify_access_token`](../src/auth/auth.py),
3. returns the `user_id` inside — or raises `401` and your handler never runs.

**Key idea:** every protected endpoint gets `user_id` this same way. Auth isn't
scattered through handlers; it's one dependency they all declare. Read `deps.py`
once and you've read the auth for all 34 routes.

The tokens are hand-rolled (stdlib `hmac` + `base64`, no JWT library) — see
[src/auth/auth.py](../src/auth/auth.py). Small enough to read in full in five
minutes, and worth doing.

### 2. "Is this session theirs?" — authorization

```python
verify_session_ownership(req.session_id, user_id)
```

Authentication proved *who* you are; this proves you own *this* resource. It
looks up the session's `user_id` and raises `404` if the session doesn't exist,
`403` if it belongs to someone else. This is the line that stops user B from
reading user A's chats. (The smoke test hammers exactly this — search
`tests/smoke_test.py` for "cross-user".)

### 3. Load the retriever

```python
retriever = retriever_cache.get(req.session_id)
if not retriever:
    raise HTTPException(status_code=400, "No database built ...")
```

Building a retriever means querying the session's chunks out of the `document_chunks`
table in Postgres and fitting a TF-IDF model over them — far too slow to redo every
message. So [src/api/retriever_cache.py](../src/api/retriever_cache.py) keeps an
in-process LRU cache (max 32). First call for a session builds and caches it; later
calls reuse it. If the session never uploaded documents, `get()` returns `None` and
the request stops here with a `400`.

> This is the layer boundary in action: the router asks the cache for "the
> retriever for this session" and doesn't know or care that the chunks live as
> rows in a Postgres table queried via pgvector.

### 4. Assemble the student's context

```python
profile_summary = mastery.build_profile_summary(user_id)
memory_context  = user_memory.get_memory_as_system_context(user_id)
chain = build_rag_chain(retriever, profile_summary, memory_context)
```

Before answering, the system gathers *who this student is*:
- **`build_profile_summary`** ([mastery.py](../src/personalization/mastery.py)) —
  a text block of their tracked topics and mastery scores ("Biology: Weak (32%)
  Mitosis"). This is how the tutor knows to go slow on weak topics.
- **`get_memory_as_system_context`** ([user_memory.py](../src/personalization/user_memory.py))
  — stored preferences ("likes analogies", "second-year student").

Both get baked into the system prompt. Open
[src/rag/chain.py](../src/rag/chain.py) and read the prompt strings — this is
where the app's whole *personality* lives. Note the "ADAPTATION" rules that tell
the LLM to sound like a different person for weak vs. strong topics. The prompt is
doing a lot of the product's work.

### 5. Trim history

```python
text_history = [m for m in history_raw if m["role"] in ("user","assistant")]
if len(text_history) > _HISTORY_TURNS:   # 4
    text_history = text_history[-4:]
```

Quiz messages are filtered out of what the LLM sees, and only the last 2 Q&A
pairs are replayed — a cost/latency control so the prompt doesn't grow without
bound. If this is the first message, the session gets auto-titled from the
question.

### 6. The heart: Corrective RAG

```python
context_text, source_label, sources_metadata = build_crag_context(retriever, req.question)
```

This one call ([src/rag/crag.py](../src/rag/crag.py), `build_crag_context`) is the
most interesting thing in the codebase. It runs a three-stage pipeline:

**Stage A — Hybrid retrieval** ([src/rag/retriever.py](../src/rag/retriever.py)).
`retriever.invoke(question)` runs *two* searches and fuses them:
- **Dense** (pgvector): semantic similarity via Gemini embeddings, queried with
  cosine-distance (`<=>`) SQL — catches meaning.
- **Sparse** (TF-IDF): keyword overlap — catches exact terms the dense model
  might blur.
- **`reciprocal_rank_fusion`** merges the two ranked lists: each doc scores
  `1/(k+rank)` from each list, summed. A doc ranked high by *both* wins. This is
  RRF, and the function is ~15 lines — read it fully, it's the core retrieval
  idea.
- **`diversify_by_document`** then round-robins across source documents so one
  long PDF can't monopolize all 4 slots in a multi-document session.

**Stage B — Relevance grading** (`grade_documents`). The retrieved chunks are
handed *in one batch* to Gemini, which replies with just the IDs of the ones
actually relevant ("0, 2"). Irrelevant chunks are dropped. This is the
"Corrective" in CRAG — retrieval casts a wide net, then a cheap fast model prunes
it. On grader error the code keeps all docs (fail-open).

**Stage C — Fallback ladder.** Based on what survived grading:
- ≥1 relevant chunk → use it, label `[Textbook]`, and tag each chunk with
  `[Source: filename · Page N]` so the answer can cite by name.
- 0 relevant chunks → try a **web search** (`_web_search`, DuckDuckGo). *Note:
  this needs the optional `ddgs` package, which isn't installed by default — so
  today this rung silently no-ops.* See the tech-debt note in CLAUDE.md.
- web search empty/unavailable → fall back to `[General Knowledge]`, and the
  prompt is told to warn the student the answer isn't from their documents.

The function returns three things: the `context_text` for the prompt, a
`source_label`, and `sources_metadata` — the structured list the UI's citation
drawer renders. **This is why grading happens before streaming starts:** the
sources have to be known up front so they can be sent as the final SSE frame.

### 7. Stream the answer

```python
def generate():
    full_response = ""
    try:
        for chunk in chain.stream({...}):
            full_response += chunk
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield f"data: {json.dumps({'sources': sources_metadata})}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        if full_response:
            store.add_message(req.session_id, "assistant", full_response, sources=sources_metadata)
```

`chain.stream(...)` runs the LangChain pipeline from
[chain.py](../src/rag/chain.py): `prompt | model | StrOutputParser`. Tokens arrive
from Groq one at a time; each is forwarded to the browser immediately as an SSE
frame (that's why the answer *types out* live). After the last token, the sources
frame goes out, then `[DONE]`.

The `finally` block is the important subtlety: the full answer is persisted to
SQLite via [`store.add_message`](../src/sessions/store.py) **only after** the
stream finishes — and it stores `sources` alongside, so citations survive a page
reload. Because it's in `finally`, a client that disconnects mid-stream still gets
whatever was generated saved.

That's the whole request. Nine steps, four layers, two LLMs.

---

## A second, shorter trace: uploading a document (the write path)

The chat trace was the read path. The write path is worth a quick look too —
open [src/api/routers/sessions.py](../src/api/routers/sessions.py),
`upload_and_build`:

1. Auth + ownership (same two dependencies as before).
2. For each uploaded file: [`loader.py`](../src/rag/loader.py) parses PDF/DOCX/TXT
   into text and splits it into ~512-char chunks, tagging each chunk with its
   `document_id`, `source` filename, and page number.
3. A per-file row is written via
   [`documents.add_document`](../src/sessions/documents.py). A file that fails to
   parse is recorded as `status="failed"` and doesn't block the others.
4. [`embedder.create_vectorstore`](../src/rag/embedder.py) embeds all chunks
   (Gemini `gemini-embedding-001`) and inserts them into the `document_chunks`
   table in Postgres.
5. `retriever_cache.refresh(...)` rebuilds the cached retriever so the next chat
   turn sees the new documents.

Notice the metadata tagging in step 2 is what makes citation in the chat trace
(step 6) possible. The two paths are two halves of one design.

---

## How mastery tracking works (the other "brain")

Independent of RAG, and read it after the traces above. Two functions in
[src/personalization/mastery.py](../src/personalization/mastery.py) write mastery:

- **`update_topic_performance`** — called when a quiz answer comes in
  (`/api/quiz/answer`). Right/wrong nudges an **Exponential Moving Average**:
  `new = 0.3*result + 0.7*old`. Recent performance matters more than old, but no
  single answer swings the score wildly. It also fuzzy-matches topic names
  (`difflib`) so "Mitosis" and "mitosis " don't become two topics.
- **`update_ema`** — called by the "I studied this" button
  (`/api/topics/{id}/mark-reviewed`), setting the EMA from a 0–10 self-rating.

Both then advance the **spaced-repetition schedule**
([spaced_rep.py](../src/personalization/spaced_rep.py)): a weaker topic comes back
sooner, a stronger one later, intervals lengthening with each review. The review
queue (`build_review_queue`) surfaces what's due.

`scratch/test_spaced_rep.py` is a runnable, assertion-by-assertion spec for all of
this. Read the test and the code side by side — it's the fastest way in.

---

## How to verify your understanding

Reading has a ceiling. Break past it:

1. **Run the map.** `python tests/smoke_test.py` — 84 checks, no API keys,
   ~15 seconds. Reading the test top-to-bottom is a second tour of the whole API.
2. **Add a `print()`** inside `build_crag_context` or `update_topic_performance`,
   re-run the relevant test, and watch real values flow.
3. **Predict which test breaks.** Change `_EMA_ALPHA` in `mastery.py`, guess which
   assertions in `test_spaced_rep.py` fail, then check. Right = you understand it.
4. **Open `/docs`.** Start the server and visit `http://localhost:8000/docs` for a
   live, clickable reference of every endpoint (FastAPI generates it for free).

## What to skip at first

- **`static/index.html`** (~2,340 lines, inline JS/CSS) — skim only to find the
  `fetch()` call for an endpoint you're tracing. It's the least-organized file in
  the repo; that's known tech debt, not your misunderstanding.
- **`src/migrations/`** — one-time schema patches, already applied.

## One caveat, because this codebase was AI-written

Trust the **tests and the schema** over comments and docstrings. Generated code
sometimes carries confident prose that has drifted from what the code does — we
already found docs claiming `bcrypt`/JWT when the auth is hand-rolled stdlib
crypto. A passing test can't lie about behavior; a comment can. When they
disagree, believe the test and read the code.
