"""Deterministic intent router. Rules are cheap, testable, and do not depend on a small local model
following a tool-calling protocol. Order matters: chitchat > essay > artifact > qa."""
import re
from dataclasses import dataclass

_CHITCHAT = re.compile(r"^\s*(hi|hello|hey|yo|thanks|thank you|thx|ok|okay|cool|great)\b[\s!.?]*$", re.I)
_ESSAY = re.compile(r"\b(ship ?30|atomic essay|essay|blog ?post|newsletter|write (me )?(an? )?(article|post))\b", re.I)
_CREATE = re.compile(r"\b(create|make|build|generate|write|draft|turn|put|give me|produce|design|prepare)\b", re.I)
_ARTIFACT = re.compile(
    r"\b(artifact|html|css|landing page|web ?page|one[- ]?pager|markdown|\.md|cheat ?sheet|checklist|template|"
    r"playbook|slide|dashboard|infographic|document|doc|table|canvas|memo|brief|prd|roadmap)\b", re.I)
_HTML = re.compile(r"\b(html|css|landing page|web ?page|dashboard|infographic|slide|canvas|visual)\b", re.I)


@dataclass(frozen=True)
class Route:
    intent: str  # chitchat | essay | artifact | qa
    artifact_type: str | None = None  # markdown | html
    reason: str = ""


def route(message: str) -> Route:
    m = message.strip()
    if _CHITCHAT.match(m):
        return Route("chitchat", reason="greeting/ack")
    if _ESSAY.search(m) and not _HTML.search(m):
        return Route("essay", "markdown", "essay keyword")
    if _ARTIFACT.search(m) and _CREATE.search(m):
        return Route("artifact", "html" if _HTML.search(m) else "markdown", "create verb + artifact noun")
    return Route("qa", reason="default")
