# PRD: The Lenny Growth Assistant

## 1. Discovery brief

**Primary user.** A product manager or growth lead at a startup/scale-up (secondary: a founder or content marketer on the same team)
who regularly needs *credible, specific* guidance and has limited time to watch/read 300+ hours of podcast content.

**Job to be done.** "Give me what experienced operators actually said about X, so I can use it in a decision, a doc, or a post, and
let me trust it." Pain removed: searching transcripts manually; generic LLM answers with no provenance; re-formatting answers into
essays/one-pagers by hand.

**Success metrics.**
| Metric | Target | How measured |
|---|---|---|
| Groundedness: answers with ≥1 valid citation, or an explicit refusal | ≥ 95% | `meta.uncited` and `kind=refusal` flags on every message; golden-set eval |
| Unsupported-question handling: off-topic golden questions refused | ≥ 90% | golden set (next step; see Risks) |
| Time to first useful answer, local 7B | p50 < 30 s; cloud p50 < 10 s | `latency_ms` on every message, logged |
| Essay length compliance (1,000–1,500 words) | ≥ 85% after ≤1 repair pass | `meta.length_ok` |
| Adoption proxy | ≥ 60% of sessions have ≥ 2 turns; ≥ 30% open an artifact | sessions/messages/artifacts tables |

**Assumptions** (client brief was incomplete):
1. Internal tool for a small team; no SSO yet, so identity is a pseudonymous browser id (not a security boundary).
2. The public transcript repo is the sole corpus; it is refreshed manually, not continuously.
3. Local demo hardware is a laptop (8–16 GB RAM): a 7B-class Ollama model is the realistic default.
4. "Strictly from the transcripts" means refusing rather than supplementing with model knowledge.
5. The Ship 30 for 30 guide's essays are ~250 words; the brief asks for ~1,250, so the skill scales the same structure (one idea, headline-first, 3–7 ideas, specific, skimmable) rather than inventing a different format.
6. English only; the corpus is English.
7. The linked Ship 30 source was not provided as a URL in the brief text; the skill was encoded from Ship 30 for 30's public headline, hook and atomic-essay guidance (see `skills/ship30/SKILL.md`). **Verify against the exact guide the client intends.**

**Scope.**
| Included | Excluded (and why) |
|---|---|
| Hybrid-free BM25 retrieval with evidence gate | Embeddings/vector DB: adds infra + GPU/latency cost; BM25 is transparent and debuggable. Planned upgrade. |
| Deterministic router + 3 skills (QA, essay, artifact) | LLM-driven tool calling: unreliable on small local models |
| Per-message provider toggle, optional fallback | Auto-routing by cost/quality: premature |
| Sandboxed artifact viewer (Preview/Source/Copy/Download) | Editing artifacts in place, version history |
| Postgres persistence of sessions, messages, artifacts, chunks | Auth/SSO, multi-tenant admin, Alembic migrations (documented as production steps) |
| JSON logs, health/readiness, structured errors | Metrics/tracing backends (logs carry the fields needed) |
| Non-streaming responses | Token streaming: more moving parts; a status line covers the wait. Priority next feature for local models. |

## 2. Core flows
1. **Ask:** question → route → retrieve → evidence gate → generate → validate citations → persist → render with source chips.
2. **Follow-up:** "and why does that matter?" borrows the last *grounded* question for retrieval; refusals never steer later retrieval.
3. **Essay:** "write a Ship 30 for 30 essay about X" → skill prompt + excerpts → length check/one repair pass → Markdown artifact with Sources → viewer.
4. **Artifact:** "create an HTML one-pager / Markdown checklist" → parse `<artifact>` block → store raw → sanitise on read → sandboxed iframe.
5. **Switch model:** header selector per message; failures surface specific, actionable errors; optional fallback.

## 3. Acceptance criteria
* New chat creates an independent session; contexts never mix (test: `test_sessions_are_independent_and_user_scoped`).
* Every answer shows sources with guest, episode, timestamp and link, or is an explicit refusal (`test_grounded_answer…`, `test_off_topic…`).
* Conversations persist across restarts (`test_grounded_answer_has_cited_sources_and_persists`).
* Provider can be changed by env var and by UI without code changes; Ollama is the demo default.
* Generated HTML cannot execute script, submit forms or fetch network resources (`test_sanitize.py`, sandbox + CSP).
* Missing key / Ollama down / timeout / empty retrieval / DB down each produce a structured, actionable error (api tests).
* `docker compose up` yields a working app with no manual configuration other than having Ollama running.

## 4. Risks and trade-offs
| Risk | Mitigation | Residual |
|---|---|---|
| Hallucination | Excerpt-only prompt, `[S#]` citation validation (invalid markers stripped, uncited answers flagged), evidence gate, `NOT_SUPPORTED` sentinel | Small models can cite loosely; no semantic faithfulness check yet → golden-set eval + LLM-judge is the next step |
| Latency (local) | 7B default, bounded context (≤8 excerpts), status line, timeouts | No streaming; first call loads the model |
| Cost (cloud) | Gate refuses before calling the LLM; chitchat never calls the LLM; one bounded repair pass | No per-user budget |
| Local model quality | Deterministic pipeline does retrieval/formatting; model only writes | Essays below 1,000 words are flagged, not hidden |
| Data leakage | Transcripts are public; cloud calls send only excerpts + chat history; no keys in repo; user id is random | Chat history goes to the cloud provider when selected: disclose to users |
| Unsafe artifacts | nh3 allow-list → CSS URL stripping → CSP → `iframe sandbox=""` (no scripts, opaque origin) | A browser-level sandbox bug would be the remaining exposure |
| Prompt injection via transcripts | Excerpts are quoted data; model has no tools that act on the world | Output could still repeat injected text |

## 5. Implementation plan (as built)
1. Parse/chunk/index transcripts; validate on the full corpus (found and fixed 3 format variants). 2. Provider abstraction + registry.
3. Orchestrator + router + skills. 4. API, persistence, errors, logging. 5. Sanitiser + viewer. 6. Tests. 7. Docker/compose/docs.
**Next:** golden-set eval, hybrid embeddings, streaming, Alembic, SSO, incremental re-ingest.
