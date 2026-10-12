# Coding Agent Session Transcript & Development Log

## Overview
This log documents the end-to-end development, debugging, and verification trajectory of the Lenny Growth Assistant, with sensitive secrets scrubbed.

---

### Step 1: Requirements Analysis & Specification Engineering
- **Objectives:**
  1. Detailed PRD covering user profiles, problem statements, success metrics, explicit assumptions, operational scope, core conversational and artifact flows, acceptance criteria, risks, mitigations, and phased implementation plans.
  2. UI/UX design document (`design.md`) establishing principles, information architecture, critical interaction states, responsive layouts, accessibility (WCAG AA guidelines, aria roles, skip links, contrast tokens), and trade-offs.
  3. Architecture documentation (`architecture.md`) detailing physical deployment topologies, container orchestration, component boundaries, PostgreSQL schemas, REST API endpoints, BM25 retrieval pipeline, deterministic agent routing, provider registry, security sandbox, and observability.
  4. Comprehensive automated test suite for API endpoints, knowledge base ingestion, tokenization/chunking, routing logic, artifact parsing, sanitization, plus a manual UI test verification plan.
  5. Agent transcripts documenting build trajectory, failure modes, corrections, and lessons learned.

---

### Step 2: Architecture & Implementation Highlights
- **Deterministic Routing Pipeline:**
  - Evaluates user intent before touching LLMs (`chitchat -> essay -> artifact -> qa`).
  - Offloads deterministic operations (BM25 search, evidence sufficiency gate, speaker disambiguation) to code rather than prompt engineering, preserving reliability on small 3B/7B local models.
- **Evidence Sufficiency Gate:**
  - Evaluates IDF-weighted coverage of query tokens against top retrieved passages. Queries falling below the threshold `MIN_QUERY_COVERAGE` trigger structured refusals immediately, eliminating hallucination on off-topic questions.
- **Defense-in-Depth Artifact Sandbox:**
  - Strict HTML sanitization via `nh3` allowlist (blocks script, iframe, form, SVG, event handlers).
  - CSS URL and import stripping.
  - Strict document Content Security Policy (`default-src 'none'; style-src 'unsafe-inline'`).
  - Sandboxed iframe execution (`sandbox="" srcdoc`) ensuring total browser-level isolation.

---

### Step 3: Key Failure Modes Encountered & Corrections Applied

| # | Failure Mode Encountered | Root Cause | Correction Applied |
|---|--------------------------|------------|-------------------|
| 1 | `open("tests/fixtures/...") FileNotFoundError` in `test_kb.py` | Test assumed current working directory was the `backend/` directory when executed. | Switched to `Path(__file__).parent / "fixtures/..."` to guarantee portable execution from any working directory. |
| 2 | `TypeError: build_query() takes from 1 to 2 positional arguments but 3 were given` in `test_router_and_artifacts.py` | Test callers provided optional `intent` argument while `build_query` signature only accepted `(user_text, prior_user)`. | Added `intent: str | None = None` to `build_query()` signature in `app.agent.orchestrator`. |
| 3 | `HTTP 429 RATE_LIMITED` in `test_api.py` (`test_offtopic_after_ontopic_is_not_rescued_by_earlier_context`) | The in-memory sliding-window rate limiter limits users to 20 messages per minute. In an automated test suite executing 21+ messages within ~5 seconds using the same `UID`, the limiter triggered. | Set `rate_limit_per_minute=0` in the test `Settings` fixture in `conftest.py` to allow fast automated test execution without artificial throttling. |
| 4 | Turn-result metadata misalignment | Positional parameter passing resulted in `meta` being placed in `latency_ms` during essay skill execution. | Refactored `TurnResult` instantiation across all orchestrator paths to use explicit keyword arguments. |
| 5 | Context poisoning across turns | Follow-up query expansion previously appended context to any short query regardless of groundedness. | Restricted context lending strictly to previously grounded user queries, skipping refusals and off-topic queries. |

---

### Step 4: Verification & Test Results
- **Automated Tests:**
  - Executed: `pytest backend/tests -v`
  - Result: **48 passed, 0 failed, 1 warning in 6.12s**.
- **Coverage Areas:**
  - API contracts, validation, status codes, session persistence, error handlers.
  - Ingestion, frontmatter parsing, chunking, BM25 scoring, and episode search.
  - Intent routing, follow-up detection, context borrowing, artifact extraction, citation normalization.
  - HTML fragment sanitization, CSP generation, and raw markdown escaping.

---

### Step 5: Secrets Sanitization
- `.env` verified to be git-ignored in `.gitignore`.
- Created clean `.env.example` with placeholder values for open-source and team distribution.
- All transcripts and documentation reviewed to confirm no private API keys or personal credentials are committed.
