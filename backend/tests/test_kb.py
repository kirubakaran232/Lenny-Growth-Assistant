from pathlib import Path
from app.kb.bm25 import BM25, tokenize
from app.kb.chunking import chunk_turns, normalize_ts, parse_turns, split_frontmatter
from app.kb.index import KnowledgeIndex
from sqlalchemy.orm import sessionmaker
from app.db import make_engine


def test_frontmatter_and_turns_hhmmss():
    path = Path(__file__).parent / "fixtures" / "episodes" / "alice-example" / "transcript.md"
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["guest"] == "Alice Example"
    turns = parse_turns(body)
    assert turns[1].speaker == "Alice Example" and turns[1].ts == "00:00:30"


def test_turns_mmss_and_no_timestamp_formats():
    mmss = parse_turns("## Transcript\n\nA (01:05):\nhello world\n\n(01:30):\nmore from A\n")
    assert [t.ts for t in mmss] == ["00:01:05", "00:01:30"] and mmss[1].speaker == "A"
    plain = parse_turns("## Transcript\n\nAdriel Frederick:\nSome text here.\n\nLenny:\nQuestion?\n")
    assert [t.speaker for t in plain] == ["Adriel Frederick", "Lenny"] and plain[0].ts == ""
    assert normalize_ts("5:07") == "00:05:07"


def test_chunking_respects_size_and_overlap():
    body = "## Transcript\n\n" + "\n\n".join(f"S (00:{i:02d}:00):\n" + " ".join(["w"] * 50) for i in range(10))
    chunks = chunk_turns(parse_turns(body), target_words=120, overlap_turns=1)
    assert len(chunks) > 3
    assert all(len(c.text.split()) <= 120 + 50 + 20 for c in chunks)
    assert chunks[1].text.split("\n")[0] == chunks[0].text.split("\n")[-1]  # overlap carries one turn


def test_long_monologue_is_split():
    chunks = chunk_turns(parse_turns("## Transcript\n\nA (00:00:01):\n" + " ".join(["x"] * 1000)), target_words=200)
    assert len(chunks) == 5


def test_bm25_ranks_relevant_doc_and_coverage_penalises_unknown_terms():
    docs = ["activation onboarding retention cohort", "pricing packaging willingness survey", "hiring interview loop"]
    bm = BM25(docs)
    top = bm.search("activation retention cohort")[0]
    assert top.doc == 0 and top.coverage > 0.9
    miss = bm.search("sourdough bread recipe")
    assert not miss or miss[0].coverage < 0.1
    assert tokenize("pricing") == ["pric"] or tokenize("pricing") == ["pricing"]


def test_index_search_from_db(seeded):
    engine = make_engine(seeded.database_url)
    with sessionmaker(engine)() as db:
        idx = KnowledgeIndex()
        assert idx.load(db) > 0 and idx.episodes == 2
    res = idx.search("How do I improve onboarding activation?")
    assert res.passages[0].guest == "Alice Example" and res.best_coverage >= 0.5
    assert "youtube.com/watch?v=" in res.passages[0].deep_link
    off = idx.search("best sourdough bread recipe")
    assert off.best_coverage < 0.5


def test_empty_index_returns_nothing():
    assert KnowledgeIndex().search("anything").passages == []
