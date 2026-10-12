# Build log (AI-assisted, Claude)

## Failures and corrections
1. **Scaffold failed silently.** `mkdir -p a/{b,c}` under `/bin/sh` created a literal `{b,c}` directory, so later file writes failed. Detected from error output; recreated directories explicitly.
2. **Parser matched 273/303 episodes.** Real data (cloned and inspected first) had timestamp-less `Name:` turns and `MM:SS` timestamps. Added both formats → 302/303.
3. **Speaker-regex bug found by a unit test.** `\s*` crossed newlines, so a bare `(01:30):` header swallowed the prior paragraph's last line as its "speaker". Fixed to `[ \t]*`; re-verified on the full corpus (62,835 turns, no malformed speakers).
4. **Off-topic detection too weak.** Raw term coverage let "sourdough bread recipe" through; switched to IDF-weighted coverage and raised the threshold to 0.5.
5. **`TurnResult` positional-argument bug** put `meta` into `latency_ms` (caught by the essay test). Switched to keyword args.
6. **Found only by the live end-to-end run:** follow-up logic appended earlier user turns to every short query, so off-topic questions inherited on-topic context and a later essay request was wrongly refused. Redesigned: standalone search first, context only for real follow-ups, only from grounded turns; follow-ups are judged on the earlier question's coverage. Added regression tests.
7. Several of my own tests encoded wrong expectations (coverage with an unseen word, a deep link at t=0); corrected the tests, not the code, after confirming behaviour was right.
9. **Path dependency in test fixtures:** `open("tests/fixtures/...")` failed when running pytest from the repository root instead of the backend folder. Fixed using `Path(__file__).parent / "fixtures/..."`.
10. **`build_query` signature:** Callers in routing tests passed `intent` to `build_query`. Added optional `intent: str | None = None` to match all caller forms cleanly.
11. **Rate limiter triggered by rapid test execution:** Fast automated test execution sent >20 requests within 5 seconds under the same test user ID, triggering HTTP 429 `RATE_LIMITED`. Configured `rate_limit_per_minute=0` in the test `Settings` fixture.

## What was verified, and how
* 48 automated tests pass (SQLite, fake LLM) with 0 failures in ~6 seconds.
* Live server run against the full 303-episode corpus with auto-ingest (302 episodes, 29,146 passages), a mock Ollama HTTP server exercising the real provider code, and curl for QA, follow-up, HTML artifact (script stripped), essay and chitchat.

## Not verified (be sceptical)
Docker image build / compose, real PostgreSQL, real Ollama models and essay quality, Anthropic API, the browser UI (JS only syntax-checked), the CSP behaviour of `srcdoc` iframes in real browsers, and genuine model compliance with `NOT_SUPPORTED`. The demo video and GitHub publishing are yours to do.
