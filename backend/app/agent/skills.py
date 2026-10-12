"""Skill loader: a skill is a SKILL.md with YAML frontmatter (config) and a markdown body (instructions)."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..kb.chunking import split_frontmatter

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    config: dict


@lru_cache
def load_skill(folder: str) -> Skill:
    meta, body = split_frontmatter((SKILLS_DIR / folder / "SKILL.md").read_text(encoding="utf-8"))
    return Skill(meta.get("name", folder), meta.get("description", ""), body.strip(), meta)
