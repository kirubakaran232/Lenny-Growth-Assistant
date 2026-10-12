# Manual UI test plan
Setup: `docker compose up --build`, Ollama running with the configured model, open http://localhost:8000.

| # | Steps | Expected |
|---|---|---|
| 1 | Load page | Empty state, KB status shows episodes/passages, model dot green |
| 2 | Click starter "How do the best teams think about activation vs. retention?" | Spinner → answer with `[n]` links, source chips, model/latency badges |
| 3 | Click a citation and a chip | Excerpt panel with guest, date, timestamp, "Open episode" link; click again collapses |
| 4 | Ask "and why does that matter?" | Answer stays on the same topic |
| 5 | Ask "best sourdough bread recipe" | Refusal badge, no fabricated answer |
| 6 | "Write a Ship 30 for 30 essay about product-market fit" | Essay opens in viewer; word count badge ~1,000–1,500; headline, short hook, H2 sections, Sources |
| 7 | "Create an HTML one-pager summarising that" | HTML renders in viewer; Source tab shows raw; no script runs |
| 8 | Copy / Download | Clipboard text; `.md`/`.html` file downloads |
| 9 | New chat, ask something unrelated to chat 1 | Fresh context; chat 1 still listed and reopenable with artifacts |
| 10 | Reload the page | Sessions persist |
| 11 | Switch model to Anthropic without a key | Clear "not set" error + Retry; chat unaffected |
| 12 | Stop Ollama, send a message | "Cannot reach Ollama" error with request id; restart → Retry works |
| 13 | Security: ask for an HTML page with `<script>alert(1)</script>` and an `onerror` image | No alert; source shows raw, preview shows sanitised |
| 14 | Resize to ≤800px | Drawer sidebar; artifact full-screen with Close |
| 15 | Keyboard only | Skip link, Tab order, Enter sends, arrow keys switch viewer tabs |
| 16 | Delete a chat | Removed from list; reload confirms |
