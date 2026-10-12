# Architecture

## Topology
```
Browser (vanilla JS)  ──HTTP──▶  FastAPI app (uvicorn, 1 container)  ──SQL──▶  PostgreSQL 16 (container)
   │  iframe sandbox="" (artifacts)        │  ├─ in-memory BM25 index (rebuilt from `chunks`)
   │                                       │  ├─ Orchestrator: router → retrieval → skill → validation
   │                                       │  └─ LLM registry ──▶ Ollama (host, :11434)  |  Anthropic API (optional)
```
`docker compose`: `db` (volume `pgdata`), `app` (volume `kbdata` holding the cloned transcripts). Ollama runs on the host (GPU/Metal access)
and is reached via `host.docker.internal`.

## Component boundaries (`backend/app`)
| Module | Responsibility |
|---|---|
| `main.py` | HTTP layer: routes, middleware (request id, security headers, access log), error handlers, lifespan/bootstrap |
| `schemas.py` | Request/response contracts + validation |
| `db.py` | SQLAlchemy models |
| `kb/` | `chunking` (parse + chunk), `bm25`, `index` (search), `ingest` (CLI + clone) |
| `agent/router.py` | Deterministic intent routing |
| `agent/orchestrator.py` | Retrieval policy, evidence gate, skill execution, citation validation |
| `agent/skills.py`, `skills/ship30/SKILL.md` | Skill definitions (config in frontmatter, instructions in body) |
| `agent/artifacts.py`, `sanitize.py` | Artifact extraction; untrusted-content sanitising |
| `llm/` | Provider interface, Ollama, Anthropic, registry + fallback |

## Database schema
* `sessions(id uuid, user_id, title, provider, user_metadata json, created_at, updated_at)`: `user_id` is a pseudonymous browser id; metadata holds user agent, language, viewport.
* `messages(id, session_id→sessions ON DELETE CASCADE, role, kind[chat|essay|artifact|refusal|chitchat], content, sources json, provider, model, latency_ms, meta json, created_at)`
* `artifacts(id, session_id→sessions CASCADE, message_id, type[markdown|html], title, content (raw), created_at)`
* `chunks(id, episode_slug, guest, title, youtube_url, publish_date, chunk_index, start_ts, start_seconds, text)`: provenance for every passage.
Tables are created at startup (`create_all`); production should adopt Alembic (explicitly out of scope).

## API
| Endpoint | Notes |
|---|---|
| `GET /health` | liveness |
| `GET /health/ready` | DB, KB state/size, provider status; 503 if DB or KB not ready |
| `GET /api/config` | providers (+availability/reason), default, fallback, KB stats |
| `POST /api/sessions`, `GET /api/sessions`, `GET/DELETE /api/sessions/{id}` | requires `X-User-Id`; foreign/missing sessions both → 404 |
| `POST /api/sessions/{id}/messages` | `{content ≤4000, provider?}` → user + assistant message, sources, artifact ref |
| `GET /api/artifacts/{id}` | raw content + sanitised `render_document` |
| `GET /api/artifacts/{id}/download` | attachment, `text/plain`, `nosniff` |
| `GET /api/search?q=` | retrieval debugging |
| `POST /api/kb/reload` | `X-Admin-Token`; disabled unless `ADMIN_TOKEN` set |

Errors: `{"error":{"code","message","details","request_id"}}`. Codes: `VALIDATION_ERROR`(422), `MISSING_USER_ID`(400), `SESSION_NOT_FOUND`/`ARTIFACT_NOT_FOUND`(404),
`KB_EMPTY`/`LLM_UNAVAILABLE`/`LLM_NOT_CONFIGURED`/`DB_UNAVAILABLE`(503), `LLM_TIMEOUT`(504), `ARTIFACT_PARSE_FAILED`(502), `INTERNAL_ERROR`(500).
A failed turn persists nothing, so retry never duplicates messages.

## Ingestion and retrieval
1. **Load:** `*/transcript.md` under `KB_PATH` (cloned from the public repo on first start or `python -m app.kb.ingest --fetch`).
2. **Parse:** YAML frontmatter (guest, title, youtube_url, date) + turns. Three real formats are handled: `Name (HH:MM:SS):`, `Name (MM:SS):`/bare `(MM:SS):` continuations, and timestamp-less `Name:`.
3. **Chunk:** consecutive turns packed to ~280 words with 1-turn overlap; long monologues split by words. Each chunk keeps speaker labels, start timestamp and episode metadata.
4. **Index:** full rebuild (idempotent) into `chunks`; BM25 (k1 1.4, b 0.75, light stemming, stopwords) built in memory at boot (~4 s for ~29k chunks). Title and guest are indexed with the text.
5. **Refresh:** re-run ingest, then restart or `POST /api/kb/reload`. Incremental refresh is a documented next step.
6. **Retrieve:** top-k with ≤2 chunks/episode for diversity. Follow-ups: search standalone first; only if that fails *and* the message looks like a follow-up, prepend the last grounded user question.
7. **Evidence gate:** `best_coverage` = IDF-weighted share of query terms present in the best passage; below `MIN_QUERY_COVERAGE` the system refuses without calling the LLM.
8. **Trace back:** every answer carries `sources[]` (guest, title, date, timestamp, deep link `&t=<s>`, snippet, cited flag).

## Agent routing
`chitchat → essay → artifact → qa` by regex (`router.py`). Retrieval is *always* executed by code, never delegated to the model, which keeps 3–7B local models reliable.
* **QA skill:** excerpt-only system prompt; citations `[S#]` validated (unknown markers stripped; no citations → flagged); `NOT_SUPPORTED:` → refusal.
* **Ship 30 essay skill:** `SKILL.md` loaded at runtime (principles, structure, hard rules, word targets); word count checked; one bounded repair pass; Markdown artifact with a numbered Sources section.
* **Artifact skill:** model emits `<artifact type title>…</artifact>`; fallbacks for fenced code and unterminated tags; unparseable HTML → 502.

**Deviation to flag:** the brief names the Claude Agent SDK or Pi. Both assume a tool-calling agent loop (the Agent SDK is Claude-hosted/CLI-based), which conflicts with the mandatory local-Ollama demo and with small-model reliability.
I implemented a thin provider-agnostic agent layer instead. The skill/provider boundaries are the seams where the Agent SDK could be swapped in for the Anthropic path.

## Model toggle
`ProviderRegistry` builds Ollama and Anthropic providers from env. Session default + per-message override. `chat_with_fallback` retries once on `FALLBACK_PROVIDER`. Provider status feeds `/api/config` and the UI dot (Anthropic is not probed to avoid spending tokens).

## Security
* **Artifacts are untrusted.** Layers: (1) `nh3` allow-list (no script/iframe/form/img/svg/object; no event handlers; only http/https/mailto links, `rel=noopener noreferrer nofollow`); (2) CSS scrub of `url()`, `@import`, `expression`; (3) in-document CSP `default-src 'none'; style-src 'unsafe-inline'`; (4) `<iframe sandbox="" srcdoc>`: no scripts, opaque origin, no forms/popups/top navigation. Sanitising happens **on read**, so rule improvements apply retroactively; raw content stays available in the Source tab and is never injected into the app DOM.
* Assistant Markdown is rendered server-side and sanitised; the SPA uses `textContent` everywhere else.
* App CSP `script-src 'self'`, `frame-ancestors 'none'`, `nosniff`, `no-referrer`.
* No secrets in the repo; `.env` ignored; keys are never logged. Session access is scoped by `X-User-Id` (isolation, not authentication).
* The viewer *permits*: inline CSS, text, tables, lists, details/summary, https links (inert in the sandbox). It *blocks*: JS, forms, images, fonts, network, popups.

## Observability
JSON logs (stdout) with `request_id` (also returned as `X-Request-ID`). Events: `request` (path/status/ms), `routed`, `retrieval` (query, hits, scores, coverage, ms), `llm call` (provider, model, ms, tokens), `primary provider failed`, `refusal`, `uncited answer`, `artifact parse failed`, `index loaded`, `ingest complete`, `failed to ingest file`. `/health/ready` surfaces DB/KB/provider state.
