"""Ingestion: transcripts on disk -> chunks table. Idempotent full rebuild."""
import argparse
import logging
import subprocess
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..db import Base, Chunk, make_engine
from ..logging_setup import setup_logging
from .chunking import chunk_turns, parse_turns, split_frontmatter

log = logging.getLogger("kb.ingest")


def fetch_transcripts(settings: Settings) -> None:
    """Shallow-clone the public transcript repo so that KB_PATH exists."""
    episodes = Path(settings.kb_path)
    repo_dir = episodes.parent
    if episodes.exists():
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    log.info("cloning transcripts", extra={"repo": settings.kb_repo_url, "dest": str(repo_dir)})
    subprocess.run(["git", "clone", "--depth", "1", settings.kb_repo_url, str(repo_dir)],
                   check=True, capture_output=True, timeout=600)


def ingest_path(db: Session, episodes_dir: Path, settings: Settings) -> dict:
    files = sorted(episodes_dir.glob("*/transcript.md"))
    if not files:
        raise FileNotFoundError(f"no */transcript.md files under {episodes_dir}")
    db.execute(delete(Chunk))
    n_chunks = skipped = 0
    for f in files:
        try:
            meta, body = split_frontmatter(f.read_text(encoding="utf-8"))
            chunks = chunk_turns(parse_turns(body), settings.chunk_words, settings.chunk_overlap_turns)
            if not chunks:
                skipped += 1
                log.warning("no chunks parsed", extra={"file": str(f)})
                continue
            title = " ".join(str(meta.get("title", f.parent.name)).split())
            for c in chunks:
                db.add(Chunk(episode_slug=f.parent.name, guest=str(meta.get("guest", "")), title=title,
                             youtube_url=str(meta.get("youtube_url", "")),
                             publish_date=str(meta.get("publish_date", "")), chunk_index=c.chunk_index,
                             start_ts=c.start_ts, start_seconds=c.start_seconds, text=c.text))
            n_chunks += len(chunks)
        except Exception:  # one bad file must not abort the whole ingest
            skipped += 1
            log.exception("failed to ingest file", extra={"file": str(f)})
    db.commit()
    stats = {"episodes": len(files) - skipped, "skipped": skipped, "chunks": n_chunks}
    log.info("ingest complete", extra=stats)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Lenny's Podcast transcripts into the database")
    ap.add_argument("--path", help="episodes directory (default: KB_PATH)")
    ap.add_argument("--fetch", action="store_true", help="git clone the transcript repo if missing")
    args = ap.parse_args()
    s = get_settings()
    setup_logging(s.log_level)
    if args.fetch:
        fetch_transcripts(s)
    engine = make_engine(s.database_url)
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        print(ingest_path(db, Path(args.path or s.kb_path), s))


if __name__ == "__main__":
    main()
