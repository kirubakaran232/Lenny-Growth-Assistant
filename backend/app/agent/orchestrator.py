"""Turn orchestration: route -> retrieve -> (guard) -> generate -> validate/post-process.
The model never decides whether retrieval happens; the code does. This keeps small local models reliable."""
import logging
import re
import time
from dataclasses import dataclass, field

from ..config import Settings
from ..errors import ApiError
from ..kb.bm25 import tokenize
from ..kb.index import KnowledgeIndex, Passage
from ..llm.base import LLMError
from ..llm.registry import ProviderRegistry
from . import prompts
from .artifacts import ParsedArtifact, parse_artifact, sources_footer
from .router import Route, route
from .skills import load_skill

log = logging.getLogger("agent")

_CITE = re.compile(r"\[S(\d+)\]")
_NOISE = re.compile(
    r"\b(ship ?30( for 30)?|atomic essay|essay|blog ?post|newsletter|article|create|make|build|generate|write|draft|"
    r"turn|into|put|give me|produce|please|can you|could you|html|css|markdown|artifact|document|doc|page|one[- ]?pager|"
    r"cheat ?sheet|checklist|template|about|that|this|it|me|an?|the)\b", re.I)

_EPISODE_NUM = re.compile(r"\bepisode\s*(?:#|no\.?|number)?\s*\d{1,3}\b|\bep\.?\s*#?\d{1,3}\b", re.I)
_PAREN_CITE = re.compile(r"[\(\[]\s*((?:S\d+\s*[,;&]?\s*(?:and\s+)?)+)[\)\]]", re.I)

EPISODE_NUMBER_REPLY = ("The transcripts aren't numbered, so I can't look up an episode by number. Ask by guest or "
                        "topic instead, for example: *Summarize Lauryn Isford's episode*, *What did Lauryn Isford say "
                        "about onboarding?* or *What do guests say about pricing experiments?*")

CHITCHAT_REPLY = ("Hi! I answer product and growth questions from Lenny's Podcast transcripts, and can turn the "
                  "answers into a Ship 30 for 30 essay or a Markdown/HTML artifact. Try: *How do top teams "
                  "think about activation?*")
REFUSAL_REPLY = ("I couldn't find material in the Lenny's Podcast transcripts that supports an answer to that. "
                 "I only answer from the transcripts, so I'd rather say so than guess. Try rephrasing with "
                 "product, growth, hiring, pricing or strategy terms.")


@dataclass
class TurnResult:
    text: str
    kind: str
    sources: list[dict] = field(default_factory=list)
    artifact: ParsedArtifact | None = None
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)
    route: Route | None = None


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", _CITE.sub("", text)))


_FOLLOWUP = re.compile(r"^\s*(and|but|also|so|what about|how about)\b|"
                       r"\b(that|this|it|those|them|these|above|previous|earlier|more|another|else|elaborate|expand|examples?)\b", re.I)


def build_query(user_text: str, prior_user: list[str] | None = None, intent: str | None = None) -> str:
    """Standalone topic query (routing words stripped). `prior_user` is only passed for genuine follow-ups."""
    topic = " ".join(_NOISE.sub(" ", user_text).split())
    if not topic:
        topic = ""
    if prior_user:
        return " ".join(prior_user[-1:] + [topic]).strip()
    return topic


_META_WORDS = re.compile(r"\b(summari[sz]e|summary|discussed?|episodes?|podcast|says?|said|talk(?:ed|s)?|told|tell|what|did|does|"
                         r"with|key|takeaways?|main|points?|from|his|her|their|interview|conversation|learn(?:ed)?|"
                         r"covered?|overview|details?|about|in|on|of)\b", re.I)


def episode_topic(user_text: str, guest_name: str) -> str:
    """What is left of the question once the guest name and 'summarise the episode' wording are removed."""
    t = re.sub(re.escape(guest_name), " ", user_text, flags=re.I)
    return " ".join(_META_WORDS.sub(" ", _NOISE.sub(" ", t)).split()) if tokenize(_META_WORDS.sub(" ", _NOISE.sub(" ", t))) else ""


def is_followup(user_text: str) -> bool:
    """A follow-up refers back to the conversation (pronouns, 'and...', 'more') or has almost no topic of its own."""
    topic_terms = len(tokenize(_NOISE.sub(" ", user_text)))
    return bool(_FOLLOWUP.search(user_text)) or topic_terms <= 2


def grounded_prior_user(history: list) -> list[str]:
    """User turns whose answer was grounded. Refusals/chitchat must never steer later retrieval."""
    out = []
    for i, m in enumerate(history):
        if m.role == "user" and i + 1 < len(history) and history[i + 1].kind in ("chat", "essay", "artifact"):
            out.append(m.content)
    return out


def _history(msgs: list, n: int) -> list[dict]:
    out = [{"role": m.role, "content": m.content[:1500]} for m in msgs[-n:] if m.kind != "error"]
    return out


def _sources(passages: list[Passage]) -> list[dict]:
    return [{"id": i, "episode_slug": p.episode_slug, "guest": p.guest, "title": p.title, "url": p.deep_link, "search_url": p.search_url,
             "timestamp": p.timestamp, "publish_date": p.publish_date, "snippet": p.text[:320], "score": p.score,
             "cited": False} for i, p in enumerate(passages, 1)]


def normalize_citations(text: str) -> str:
    """Models write (S1), [S1, S2], (S1 and S2)... Normalise all of them to [S1][S2]."""
    return _PAREN_CITE.sub(lambda m: "".join(f"[S{n}]" for n in re.findall(r"S(\d+)", m.group(1), re.I)), text)


def _mark_cited_by_markers(text: str, sources: list[dict]) -> tuple[str, int]:
    text = normalize_citations(text)
    valid = {s["id"] for s in sources}
    found = {int(n) for n in _CITE.findall(text)}
    bad = found - valid
    if bad:
        text = _CITE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", text)
    for s in sources:
        s["cited"] = s["id"] in found
    return text, len(bad)


def _mark_cited_by_names(content: str, sources: list[dict]) -> None:
    """Mark sources cited when the guest name appears in the artifact content.
    No fallback: an empty sources footer is more honest than a fabricated one."""
    low = content.lower()
    for s in sources:
        s["cited"] = bool(s["guest"]) and s["guest"].lower().split(" (")[0] in low


def _not_supported(text: str) -> str | None:
    t = text.strip()
    if t.upper().startswith("NOT_SUPPORTED"):
        return t[len("NOT_SUPPORTED"):].lstrip(" :.-\n") or REFUSAL_REPLY
    return None


class Orchestrator:
    def __init__(self, settings: Settings, index: KnowledgeIndex, providers: ProviderRegistry):
        self.s, self.index, self.providers = settings, index, providers

    def handle(self, history: list, user_text: str, provider: str) -> TurnResult:
        t0 = time.time()
        r = route(user_text)
        log.info("routed", extra={"intent": r.intent, "artifact_type": r.artifact_type, "reason": r.reason})
        if r.intent == "chitchat":
            return TurnResult(CHITCHAT_REPLY, "chitchat", route=r, latency_ms=0)
        if _EPISODE_NUM.search(user_text):
            log.info("refusal: episode number lookup")
            return TurnResult(EPISODE_NUMBER_REPLY, "refusal", route=r, meta={"reason": "episode_number"})
        if self.index.size == 0:
            raise ApiError(503, "KB_EMPTY", "The knowledge base is empty or still ingesting. "
                           "Run `python -m app.kb.ingest --fetch` (or wait for auto-ingest) and retry.",
                           {"kb_state": self.index.state})

        k = self.s.retrieval_top_k + (2 if r.intent != "qa" else 0)
        t1 = time.time()
        guest = self.index.find_guest(user_text)
        if guest:  # the user named a guest: answer from that guest's episode only
            name, slugs = guest
            topic = episode_topic(user_text, name)
            res = self.index.search_episode(slugs, topic, max(k, 6))
            query, used_context = f"[episode:{','.join(slugs)}] {topic}", False
            log.info("episode-scoped retrieval", extra={"guest": name, "episodes": slugs, "topic": topic[:100]})
        else:
            res = None
            query = build_query(user_text, None)
            if query:
                res = self.index.search(query, k, self.s.max_chunks_per_episode)
            used_context = False
        if not guest and (res is None or res.best_coverage < self.s.min_query_coverage) and is_followup(user_text):
            prior = grounded_prior_user(history)
            if prior:  # borrow the most recent grounded question to resolve "that", "and B2B?", etc.
                query, used_context = build_query(user_text, prior), True
                res = self.index.search(query, k, self.s.max_chunks_per_episode)
                # sufficiency is judged on the earlier, already-grounded question: unfamiliar words in a
                # follow-up ("why does that matter?") must not make a well-supported topic look unsupported
                base = self.index.search(prior[-1], k, self.s.max_chunks_per_episode)
                res.best_coverage = max(res.best_coverage, base.best_coverage)
        if res is None:
            res = self.index.search(user_text, k, self.s.max_chunks_per_episode)
        log.info("retrieval", extra={"query": query[:200], "used_context": used_context, "hits": len(res.passages),
                                     "best_score": res.best_score, "best_coverage": res.best_coverage,
                                     "ms": int((time.time() - t1) * 1000)})
        if not res.passages or res.best_coverage < self.s.min_query_coverage:
            log.info("refusal: insufficient evidence", extra={"coverage": res.best_coverage})
            return TurnResult(REFUSAL_REPLY, "refusal", route=r, meta={"reason": "low_coverage",
                              "coverage": res.best_coverage}, latency_ms=int((time.time() - t0) * 1000))

        sources = _sources(res.passages)
        ctx = prompts.format_context(res.passages)
        hist = _history(history, self.s.history_messages)
        try:
            if r.intent == "essay":
                out = self._essay(provider, hist, user_text, ctx, sources)
            elif r.intent == "artifact":
                out = self._artifact(provider, hist, user_text, ctx, sources, r.artifact_type or "markdown")
            else:
                out = self._qa(provider, hist, user_text, ctx, sources)
        except LLMError as e:
            log.error("llm failure", extra={"code": e.code, "error": str(e), "provider": provider})
            raise ApiError(e.http_status, e.code, str(e), {"provider": provider}) from e
        out.route = r
        out.latency_ms = int((time.time() - t0) * 1000)
        log.info("turn complete", extra={"intent": r.intent, "kind": out.kind, "provider": out.provider,
                                         "model": out.model, "fallback": out.fallback_used,
                                         "latency_ms": out.latency_ms, "sources_cited": sum(s["cited"] for s in out.sources)})
        return out

    # ---- skills -------------------------------------------------------------------------------
    def _call(self, provider, messages, max_tokens):
        t = time.time()
        res, used, fb = self.providers.chat_with_fallback(provider, messages, max_tokens=max_tokens,
                                                          temperature=self.s.llm_temperature)
        log.info("llm call", extra={"provider": used, "model": res.model, "fallback": fb,
                                    "ms": int((time.time() - t) * 1000), **{k: v for k, v in res.usage.items() if isinstance(v, int)}})
        return res, used, fb

    def _qa(self, provider, hist, user_text, ctx, sources) -> TurnResult:
        # small local models obey instructions placed right next to the question far better than system-prompt rules
        reminder = ("\n\n(Answer only from the excerpts above. End every bullet or sentence with the excerpt "
                    "number it came from, like [S1] or [S2]. Skip irrelevant excerpts. If they don't answer the "
                    "question, reply NOT_SUPPORTED.)")
        msgs = [{"role": "system", "content": prompts.QA_SYSTEM + "\n\n" + ctx}, *hist,
                {"role": "user", "content": user_text + reminder}]
        res, used, fb = self._call(provider, msgs, 900)
        refusal = _not_supported(res.text)
        if refusal is not None:
            return TurnResult(refusal, "refusal", provider=used, model=res.model, fallback_used=fb,
                              meta={"reason": "model_not_supported"})
        text, bad = _mark_cited_by_markers(res.text.strip(), sources)
        meta = {"invalid_citations_removed": bad}
        if not any(s["cited"] for s in sources):
            meta["uncited"] = True
            text += "\n\n*Note: this answer did not cite any transcript excerpt, so treat it with caution.*"
            log.warning("uncited answer", extra={"provider": used})
        return TurnResult(text, "chat", sources, provider=used, model=res.model, fallback_used=fb, meta=meta)

    def _essay(self, provider, hist, user_text, ctx, sources) -> TurnResult:
        skill = load_skill("ship30")
        cfg = skill.config
        msgs = [{"role": "system", "content": prompts.ESSAY_SYSTEM.format(skill=skill.body) + "\n\n" + ctx}, *hist,
                {"role": "user", "content": user_text}]
        res, used, fb = self._call(provider, msgs, 2800)
        refusal = _not_supported(res.text)
        if refusal is not None:
            return TurnResult(refusal, "refusal", provider=used, model=res.model, fallback_used=fb)
        essay, passes = res.text.strip(), 0
        n = word_count(essay)
        if n < cfg["min_words"] or n > cfg["max_words"]:  # one bounded repair pass
            direction = "Expand it with more grounded detail." if n < cfg["min_words"] else "Tighten it."
            msgs += [{"role": "assistant", "content": essay},
                     {"role": "user", "content": prompts.EXPAND_NOTE.format(n=n, target=cfg["target_words"], direction=direction)}]
            res2, used, fb2 = self._call(used if not fb else provider, msgs, 3200)
            if _not_supported(res2.text) is None and word_count(res2.text) > 0:
                better = abs(word_count(res2.text) - cfg["target_words"]) < abs(n - cfg["target_words"])
                essay, n, passes = (res2.text.strip(), word_count(res2.text), 1) if better else (essay, n, 1)
            fb = fb or fb2
        essay, bad = _mark_cited_by_markers(essay, sources)
        essay = _CITE.sub(lambda m: f"[{m.group(1)}]", essay)
        essay += sources_footer("markdown", sources)
        title = (re.search(r"^#\s+(.+)$", essay, re.M) or [None, "Ship 30 for 30 essay"])[1].strip()
        art = ParsedArtifact("markdown", title[:120], essay, "")
        ok = cfg["min_words"] <= n <= cfg["max_words"]
        msg = (f"Here's your Ship 30 for 30 essay, **{title}** ({n:,} words). It's open in the viewer; "
               f"every claim is cited to the transcripts.")
        if not ok:
            msg += f" Note: the model landed at {n:,} words, outside the {cfg['min_words']:,}–{cfg['max_words']:,} target."
        return TurnResult(msg, "essay", sources, art, provider=used, model=res.model, fallback_used=fb,
                          meta={"word_count": n, "length_ok": ok, "repair_passes": passes,
                                "invalid_citations_removed": bad})

    def _artifact(self, provider, hist, user_text, ctx, sources, atype) -> TurnResult:
        label = "self-contained HTML/CSS snippet" if atype == "html" else "Markdown document"
        system = prompts.ARTIFACT_SYSTEM.format(atype=atype, atype_label=label, atype_rules=prompts.ATYPE_RULES[atype])
        msgs = [{"role": "system", "content": system + "\n\n" + ctx}, *hist, {"role": "user", "content": user_text}]
        res, used, fb = self._call(provider, msgs, 3000 if atype == "html" else 2200)
        refusal = _not_supported(res.text)
        if refusal is not None:
            return TurnResult(refusal, "refusal", provider=used, model=res.model, fallback_used=fb)
        parsed = parse_artifact(res.text, atype)
        if parsed is None:
            looks_html = atype == "html" and "<" in res.text and ">" in res.text
            if atype == "markdown" or looks_html:
                log.warning("artifact tag missing; using whole reply", extra={"type": atype})
                parsed = ParsedArtifact(atype, "Untitled artifact", res.text.strip(), "")
            else:
                log.error("artifact parse failed", extra={"preview": res.text[:200]})
                raise ApiError(502, "ARTIFACT_PARSE_FAILED",
                               "The model did not return a usable artifact. Try again or use a larger model.",
                               {"provider": used, "model": res.model})
        _mark_cited_by_names(parsed.content, sources)
        parsed.content += sources_footer(parsed.type, sources)
        summary = parsed.summary or f"Created **{parsed.title}**."
        return TurnResult(summary + " It's open in the viewer.", "artifact", sources, parsed, provider=used,
                          model=res.model, fallback_used=fb, meta={"artifact_type": parsed.type})
