import pytest

from app.agent.artifacts import parse_artifact, sources_footer
from app.agent.orchestrator import build_query, grounded_prior_user, is_followup, word_count
from app.agent.router import route


@pytest.mark.parametrize("msg,intent,atype", [
    ("hi", "chitchat", None),
    ("Thanks!", "chitchat", None),
    ("How do teams improve activation?", "qa", None),
    ("Write a Ship 30 for 30 essay about activation", "essay", "markdown"),
    ("turn that into an atomic essay", "essay", "markdown"),
    ("Create an HTML landing page summarising this", "artifact", "html"),
    ("make a markdown checklist for onboarding", "artifact", "markdown"),
    ("What is a good checklist for pricing?", "qa", None),
    ("Build a dashboard with CSS for activation metrics", "artifact", "html"),
])
def test_routing(msg, intent, atype):
    r = route(msg)
    assert r.intent == intent and r.artifact_type == atype


def test_followup_detection():
    assert is_followup("turn that into an essay") and is_followup("and for B2B?") and is_followup("why?")
    assert not is_followup("best sourdough bread recipe")
    assert not is_followup("How do top teams measure activation and retention?")


def test_prior_context_only_from_grounded_turns():
    from types import SimpleNamespace as N
    h = [N(role="user", content="activation?", kind="chat"), N(role="assistant", content="a", kind="chat"),
         N(role="user", content="sourdough?", kind="chat"), N(role="assistant", content="no", kind="refusal")]
    assert grounded_prior_user(h) == ["activation?"]
    assert build_query("and for B2B?", ["activation?"], "qa").startswith("activation?")


def test_query_strips_routing_noise():
    q = build_query("Write a Ship 30 for 30 essay about pricing experiments", [], "essay")
    assert q == "pricing experiments"


def test_parse_artifact_tag_and_fence_fallback():
    p = parse_artifact('Done.\n<artifact type="html" title="Plan">\n<h1>Hello world plan</h1>\n</artifact>', "markdown")
    assert (p.type, p.title, p.summary) == ("html", "Plan", "Done.")
    f = parse_artifact("Here:\n```markdown\n# Title here\n\nSome body text for it\n```", "markdown")
    assert f.type == "markdown" and f.title == "Title here"
    assert parse_artifact("no block at all", "markdown") is None
    assert parse_artifact('<artifact type="html" title="x">hi</artifact>', "html") is None  # too short


def test_unterminated_artifact_block_is_still_parsed():
    p = parse_artifact('<artifact type="markdown" title="T">\n# Heading\n\nbody body body body', "markdown")
    assert p and p.content.startswith("# Heading")


def test_sources_footer_escapes_html():
    src = [{"id": 1, "guest": "<b>X</b>", "title": "T&C", "url": "", "cited": True}]
    assert "&lt;b&gt;" in sources_footer("html", src) and "<b>X" not in sources_footer("html", src)


def test_word_count_ignores_citations():
    assert word_count("one two [S1] three") == 3
