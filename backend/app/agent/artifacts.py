"""Extract <artifact type=".." title=".."> blocks (or fenced code) from model output."""
import re
from dataclasses import dataclass
from html import escape

_BLOCK = re.compile(r"<artifact\b([^>]*)>(.*?)(?:</artifact>|\Z)", re.S | re.I)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_FENCE = re.compile(r"```(html|markdown|md)?\s*\n(.*?)```", re.S | re.I)


@dataclass
class ParsedArtifact:
    type: str
    title: str
    content: str
    summary: str  # model text outside the artifact block


def _strip_fence(text: str) -> str:
    m = _FENCE.fullmatch(text.strip())
    return m.group(2).strip() if m else text.strip()


def parse_artifact(text: str, default_type: str) -> ParsedArtifact | None:
    m = _BLOCK.search(text)
    if m:
        attrs = dict(_ATTR.findall(m.group(1)))
        content = _strip_fence(m.group(2))
        a_type = attrs.get("type", default_type).lower()
        summary = (text[:m.start()] + text[m.end():]).strip()
    else:
        f = _FENCE.search(text)
        if not f:
            return None
        a_type = {"html": "html", "markdown": "markdown", "md": "markdown"}.get((f.group(1) or "").lower(), default_type)
        attrs, content = {}, f.group(2).strip()
        summary = (text[:f.start()] + text[f.end():]).strip()
    a_type = "html" if a_type == "html" else "markdown"
    if len(content) < 20:
        return None
    title = (attrs.get("title") or _guess_title(content, a_type)).strip()[:120] or "Untitled artifact"
    return ParsedArtifact(a_type, title, content, summary)


def _guess_title(content: str, a_type: str) -> str:
    m = re.search(r"^#\s+(.+)$", content, re.M) if a_type == "markdown" else re.search(r"<title>(.*?)</title>|<h1[^>]*>(.*?)</h1>", content, re.S | re.I)
    if not m:
        return "Untitled artifact"
    return re.sub(r"<[^>]+>", "", next(g for g in m.groups() if g)).strip()


def sources_footer(artifact_type: str, sources: list[dict]) -> str:
    cited = [s for s in sources if s["cited"]]
    if not cited:
        return ""
    if artifact_type == "html":
        items = "".join(f"<li>{escape(s['guest'])} &mdash; {escape(s['title'])}</li>" for s in cited)
        return f'\n<footer class="sources"><h2>Sources</h2><ul>{items}</ul></footer>'
    def line(s):
        t = s["title"].replace("[", "(").replace("]", ")")
        return f"- [{s['id']}] {s['guest']} — " + (f"[{t}]({s['url']})" if s.get("url") else f"*{t}*")
    lines = "\n".join(line(s) for s in cited)
    return f"\n\n## Sources\n{lines}\n"
