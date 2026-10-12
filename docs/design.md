# Design

**Principles.** (1) Trust is visible: every answer shows its sources and every refusal says why. (2) The user never meets infrastructure: errors say what to do next. (3) Chat and artifact work side by side. (4) Calm, dense-enough, keyboard-first.

**Information architecture.** Left: conversations (new, switch, delete) + KB status. Centre: header with model selector and fallback note, message log, status/alert region, composer. Right: Artifact Viewer (title, type badge, Preview/Source tabs, Copy, Download, Close) opened automatically for essays/artifacts or from an "Open" button on the message.

**Key states.** Empty (explanation + 4 starter prompts) · sending (spinner + "local models can take a minute", input disabled) · answer (badges: model, latency, fallback, uncited) · refusal ("Not in the transcripts" badge) · error (message, code, request id, Retry, Dismiss; the failed text is re-sendable) · provider unavailable (red dot + reason in the note) · KB ingesting (sidebar status) · artifact viewer open/closed.

**Citations.** `[n]` links in text and source chips below; both open the same excerpt panel (guest, episode, date, timestamp, deep link, snippet). Only cited sources are shown as chips.

**Artifact Viewer.** Sandboxed iframe, with a one-line note on what is blocked. Source tab shows raw output for inspection.

**Responsive.** ≥1100px: three columns. ≤1100px: viewer becomes a full-screen overlay (Esc closes). ≤800px: sidebar becomes a slide-in drawer via a hamburger (`aria-expanded`).

**Accessibility.** Skip link; labelled controls; `role=log aria-live=polite` for the transcript, `role=status`/`alert` for progress/errors; tablist with arrow-key navigation; visible focus rings; `prefers-color-scheme` dark theme; `prefers-reduced-motion`; no colour-only meaning (badges carry text). Contrast follows token pairs chosen for AA in both themes (not formally audited).

**Decisions.** Vanilla JS, no build step: one fewer thing for an evaluator to break. No streaming in v1 (status line instead); this is the top UX gap for slow local models.
