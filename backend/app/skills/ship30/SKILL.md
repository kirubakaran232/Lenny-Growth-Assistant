---
name: ship30-essay
description: Turn grounded Lenny's Podcast knowledge into a Ship 30 for 30-style essay (headline-first, one idea, skimmable).
target_words: 1250
min_words: 1000
max_words: 1500
---

# Ship 30 for 30 essay skill

Source material: Ship 30 for 30 (Dickie Bush and Nicolas Cole) teaching on headlines, hooks and
"atomic essays" (one idea, written to be read fast and shipped often). The classic atomic essay is ~250
words; this skill deliberately scales the same structure to ~1,250 words by giving each main idea
more evidence, because the knowledge base supplies concrete, quotable material.

## Principles (encoded from the Ship 30 guidance)
1. **Headline first.** Decide the destination before writing. Promise a specific outcome for a specific
   reader, ideally with the "How to X without Y" shape (outcome + removed obstacle).
2. **One idea per essay.** Everything must serve a single, strong opinion stated up front.
3. **Open with a short, opinionated first sentence.** No throat-clearing, no "In this essay".
4. **The hook tells the reader exactly what they will get** (an actionable framework, a step-by-step
   plan, a mistake to avoid) and why it matters now.
5. **Organise around 3-7 main ideas.** Each one: claim, then a short explanation using any mix of: why
   it matters, the common mistake, how to apply it, a concrete example.
6. **Be specific, never vague.** Names, numbers, situations. Replace "many companies" with the guest
   and the company they described.
7. **Borrowed credibility.** Use what the podcast guests said as proof, attributed by name, instead of
   unsupported assertions.
8. **Skimmable.** Short paragraphs (1-3 sentences), descriptive H2 headings, bullets for steps, bold
   only for the single most important phrase in a section.
9. **End on a specific, useful takeaway** the reader can do in the next 24 hours.

## Structure to produce
- `# Headline` (promise + obstacle removed)
- Hook: 2-4 very short lines (strong opinion, stakes, what the reader gets)
- 4-6 sections, each an `## H2` that states the idea, ~150-250 words, with at least one grounded example
- `## The takeaway`: a short summary plus one concrete action
- No sources list (the system appends it).

## Hard rules
- Every factual claim about what a guest said or recommended must carry a `[S#]` citation to the
  numbered excerpts. Never invent quotes, numbers, companies or guests.
- If the excerpts do not support a section, cut it. Prefer a shorter, honest essay to a padded one.
- Target about 1,250 words (acceptable range 1,000-1,500).
- Output only the essay in Markdown. No preface, no closing remarks.
