"""In-memory retrieval index rebuilt from the `chunks` table. Swapped atomically on reload."""
import logging
import re
import threading
import time
from urllib.parse import quote_plus
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Chunk
from .bm25 import BM25

log = logging.getLogger("kb.index")


_YT = re.compile(r"^https://www\.youtube\.com/watch\?v=[\w-]{11}$")


@dataclass
class Passage:
    chunk_id: int
    episode_slug: str
    guest: str
    title: str
    url: str
    publish_date: str
    timestamp: str
    seconds: int
    text: str
    score: float
    coverage: float

    @property
    def search_url(self) -> str:
        """Always-valid fallback when the video link is missing, malformed or the video was removed."""
        return "https://www.youtube.com/results?search_query=" + quote_plus(f"{self.title} Lenny's Podcast")

    @property
    def deep_link(self) -> str:
        if not _YT.match(self.url or ""):  # missing/malformed upstream metadata: emit no link rather than a broken one
            return ""
        if not self.seconds:
            return self.url
        return f"{self.url}{'&' if '?' in self.url else '?'}t={self.seconds}s"


@dataclass
class SearchResult:
    passages: list[Passage]
    best_coverage: float
    best_score: float


class KnowledgeIndex:
    def __init__(self):
        self._bm25: BM25 | None = None
        self._rows: list[dict] = []
        self.state = "empty"  # empty | ingesting | ready | error
        self.error: str | None = None
        self._lock = threading.Lock()
        self.last_load_attempt = 0.0
        self._by_slug: dict[str, list[int]] = {}
        self._guests: dict[str, set[str]] = {}

    @property
    def size(self) -> int:
        return len(self._rows)

    @property
    def episodes(self) -> int:
        return len({r["episode_slug"] for r in self._rows})

    def load(self, db: Session) -> int:
        t0 = time.time()
        self.last_load_attempt = t0
        rows = []
        for c in db.execute(select(Chunk).order_by(Chunk.id)).scalars():
            rows.append({"id": c.id, "episode_slug": c.episode_slug, "guest": c.guest, "title": c.title,
                         "url": c.youtube_url, "date": c.publish_date, "ts": c.start_ts,
                         "seconds": c.start_seconds, "text": c.text})
        # text only: indexing the title into every chunk lets generic title words ("team") outrank real matches
        bm25 = BM25([r["text"] for r in rows]) if rows else None
        by_slug: dict[str, list[int]] = {}
        guests: dict[str, set[str]] = {}
        for i, r in enumerate(rows):
            by_slug.setdefault(r["episode_slug"], []).append(i)
            name = " ".join(r["guest"].lower().split())
            if len(name) >= 5:
                guests.setdefault(name, set()).add(r["episode_slug"])
        with self._lock:
            self._by_slug, self._guests = by_slug, guests
            self._rows, self._bm25 = rows, bm25
            self.state = "ready" if rows else "empty"
            self.error = None
        log.info("index loaded", extra={"chunks": len(rows), "episodes": self.episodes,
                                        "ms": int((time.time() - t0) * 1000)})
        return len(rows)

    def find_guest(self, text: str) -> tuple[str, list[str]] | None:
        """Longest guest name mentioned in `text` -> (name, episode slugs)."""
        low = " ".join(text.lower().split())
        hits = [n for n in self._guests if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", low)]
        if not hits:
            return None
        name = max(hits, key=len)
        return name, sorted(self._guests[name])

    def search_episode(self, slugs: list[str], topic: str, k: int = 6) -> SearchResult:
        """Passages from the given episode(s). With a topic: best BM25 matches inside it.
        Without one (a 'summarise the episode' request): evenly spaced passages across the whole conversation."""
        with self._lock:
            bm25, rows, by_slug = self._bm25, self._rows, self._by_slug
        idxs = [i for s in slugs for i in by_slug.get(s, [])]
        if not idxs or not bm25:
            return SearchResult([], 0.0, 0.0)

        def mk(i, score=0.0, cov=1.0):
            r = rows[i]
            return Passage(r["id"], r["episode_slug"], r["guest"], r["title"], r["url"], r["date"], r["ts"],
                           r["seconds"], r["text"], round(score, 3), cov)

        chosen: list[Passage] = []
        if topic.strip():
            allowed = set(idxs)
            for h in bm25.search(topic, limit=len(rows)):
                if h.doc in allowed and h.coverage > 0:
                    chosen.append(mk(h.doc, h.score, round(h.coverage, 2)))
                    if len(chosen) >= k:
                        break
        if not chosen:  # no topic, or topic not found in this episode: sample the whole episode in order
            step = max(1, len(idxs) // k)
            chosen = [mk(i) for i in idxs[::step][:k]]
        return SearchResult(chosen, 1.0, chosen[0].score)

    def search(self, query: str, k: int = 6, max_per_episode: int = 2) -> SearchResult:
        with self._lock:
            bm25, rows = self._bm25, self._rows
        if not bm25:
            return SearchResult([], 0.0, 0.0)
        out: list[Passage] = []
        per_ep: dict[str, int] = {}
        for h in bm25.search(query, limit=60):
            r = rows[h.doc]
            if per_ep.get(r["episode_slug"], 0) >= max_per_episode:
                continue
            per_ep[r["episode_slug"]] = per_ep.get(r["episode_slug"], 0) + 1
            out.append(Passage(r["id"], r["episode_slug"], r["guest"], r["title"], r["url"], r["date"],
                               r["ts"], r["seconds"], r["text"], round(h.score, 3), round(h.coverage, 2)))
            if len(out) >= k:
                break
        if out:  # drop weak tail: passages far below the best score only add distracting context
            out = [p for p in out if p.score >= 0.6 * out[0].score]
        return SearchResult(out, max((p.coverage for p in out), default=0.0), out[0].score if out else 0.0)