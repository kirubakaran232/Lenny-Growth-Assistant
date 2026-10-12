"""Small dependency-free BM25 index with light stemming."""
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

STOP = set("""a an and are as at be but by for from has have how i if in into is it its of on or our so
that the their them then there these they this to was we were what when where which who why will with you your
can could do does did should would about me my us not no yes than very more most also just any some
best think thinks good great way ways really tell explain mean means get make need want important thing things""".split())
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-']*")


def stem(w: str) -> str:
    w = w.replace("'s", "").strip("'-")
    for suf in ("ingly", "ing", "edly", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


@dataclass
class Hit:
    doc: int
    score: float
    coverage: float  # idf-weighted share of query terms present in the chunk


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(docs)
        self.post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lens: list[int] = []
        for i, d in enumerate(docs):
            toks = tokenize(d)
            self.lens.append(len(toks))
            for term, tf in Counter(toks).items():
                self.post[term].append((i, tf))
        self.avg = (sum(self.lens) / self.N) if self.N else 0.0

    def search(self, query: str, limit: int = 50) -> list[Hit]:
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms or not self.N:
            return []
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, float] = defaultdict(float)  # idf mass of matched terms
        max_idf = math.log(1 + self.N)  # weight of a term never seen in the corpus
        total_mass = 0.0
        for t in terms:
            plist = self.post.get(t)
            if not plist:
                total_mass += max_idf
                continue
            idf = math.log(1 + (self.N - len(plist) + 0.5) / (len(plist) + 0.5))
            total_mass += idf
            for doc, tf in plist:
                denom = tf + self.k1 * (1 - self.b + self.b * self.lens[doc] / (self.avg or 1))
                scores[doc] += idf * idf * tf * (self.k1 + 1) / denom  # idf^2: rare, topical terms dominate generic ones
                matched[doc] += idf
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [Hit(d, s, matched[d] / total_mass) for d, s in ranked]