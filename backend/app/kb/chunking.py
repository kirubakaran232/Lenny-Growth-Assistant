"""Parse Lenny's transcript markdown (YAML frontmatter + timestamped turns) into retrievable chunks."""
import re
from dataclasses import dataclass

import yaml

# "Speaker Name (00:01:02):" or a bare "(00:01:02):" continuation header, on its own line.
_TURN = re.compile(r"^(?:(?P<speaker>[^\n(]+?)[ \t]*)?\((?P<ts>\d{1,3}:\d{2}(?::\d{2})?)\):[ \t]*$", re.M)


# Fallback format used by some episodes: "Speaker Name:" on its own line, no timestamps.
_TURN_NO_TS = re.compile(r"^(?P<speaker>[A-Z][^\n:()]{0,60}):[ \t]*$", re.M)


@dataclass
class Turn:
    speaker: str
    ts: str
    text: str


@dataclass
class ChunkData:
    chunk_index: int
    start_ts: str
    start_seconds: int
    text: str


def split_frontmatter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), parts[2]
    return {}, raw


def ts_to_seconds(ts: str) -> int:
    if not ts:
        return 0
    parts = [int(x) for x in ts.split(":")]
    while len(parts) < 3:  # "MM:SS" -> 0:MM:SS
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def normalize_ts(ts: str) -> str:
    if not ts:
        return ""
    t = ts_to_seconds(ts)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def parse_turns(body: str) -> list[Turn]:
    if "## Transcript" in body:
        body = body.split("## Transcript", 1)[1]
    matches = list(_TURN.finditer(body))
    if not matches:  # timestamp-less transcript
        matches = list(_TURN_NO_TS.finditer(body))
    turns: list[Turn] = []
    last_speaker = ""
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = " ".join(body[m.end():end].split())
        speaker = (m.group("speaker") or "").strip() or last_speaker
        last_speaker = speaker
        if text:
            turns.append(Turn(speaker, normalize_ts(m.groupdict().get("ts") or ""), text))
    return turns


def chunk_turns(turns: list[Turn], target_words: int = 280, overlap_turns: int = 1) -> list[ChunkData]:
    """Pack consecutive turns into ~target_words windows; carry `overlap_turns` into the next window."""
    chunks: list[ChunkData] = []
    cur: list[Turn] = []
    count = 0

    def flush(items: list[Turn]):
        if items:
            text = "\n".join(f"{t.speaker or 'Speaker'}: {t.text}" for t in items)
            chunks.append(ChunkData(len(chunks), items[0].ts, ts_to_seconds(items[0].ts), text))

    for t in turns:
        words = len(t.text.split())
        if words > target_words * 1.5:  # one very long monologue: split by words
            flush(cur)
            cur, count = [], 0
            toks = t.text.split()
            for j in range(0, len(toks), target_words):
                flush([Turn(t.speaker, t.ts, " ".join(toks[j:j + target_words]))])
            continue
        if cur and count + words > target_words:
            flush(cur)
            cur = cur[-overlap_turns:] if overlap_turns else []
            count = sum(len(x.text.split()) for x in cur)
        cur.append(t)
        count += words
    flush(cur)
    return chunks
