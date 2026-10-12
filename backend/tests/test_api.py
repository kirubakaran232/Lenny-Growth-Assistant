from sqlalchemy import text

from app.db import Base
from tests.conftest import UID, UID2, make_client, new_session
from app.llm.base import LLMTimeout, LLMUnavailable


def _post(c, sid, msg, headers=UID, **extra):
    return c.post(f"/api/sessions/{sid}/messages", json={"content": msg, **extra}, headers=headers)


def test_health_and_ready(client_factory):
    c, *_ = client_factory()
    assert c.get("/health").json() == {"status": "ok"}
    r = c.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["knowledge_base"]["episodes"] == 2


def test_validation_and_missing_user_header_are_structured(client_factory):
    c, *_ = client_factory()
    r = c.post("/api/sessions", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "MISSING_USER_ID" and r.json()["error"]["request_id"]
    sid = new_session(c)
    r = _post(c, sid, "")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert r.json()["error"]["details"][0]["field"] == "content"
    assert c.post("/api/sessions", json={"provider": "gpt"}, headers=UID).status_code == 422


def test_grounded_answer_has_cited_sources_and_persists(client_factory, seeded):
    c, ollama, _ = client_factory()
    sid = new_session(c, metadata={"locale": "en"})
    r = _post(c, sid, "How do I improve onboarding activation?")
    assert r.status_code == 200, r.text
    a = r.json()["assistant_message"]
    assert a["kind"] == "chat" and a["provider"] == "ollama"
    cited = [s for s in a["sources"] if s["cited"]]
    assert cited and cited[0]["guest"] == "Alice Example" and "youtube.com" in cited[0]["url"]
    assert 'href="#src-1"' in a["content_html"]
    # the transcript excerpts were actually given to the model
    assert "TRANSCRIPT EXCERPTS" in ollama.calls[0][0]["content"]
    # persistence: a brand-new app instance on the same DB sees the conversation
    c2, *_ = make_client(seeded)
    d = c2.get(f"/api/sessions/{sid}", headers=UID).json()
    assert [m["role"] for m in d["messages"]] == ["user", "assistant"] and d["title"].startswith("How do I improve")
    c2.__exit__(None, None, None)


def test_sessions_are_independent_and_user_scoped(client_factory):
    c, ollama, _ = client_factory()
    s1, s2 = new_session(c), new_session(c)
    _post(c, s1, "How do I improve onboarding activation?")
    _post(c, s2, "How do I run a pricing experiment?")
    _post(c, s1, "and what about retention?")
    third = ollama.calls[2]
    joined = " ".join(m["content"] for m in third if m["role"] != "system")
    assert "onboarding activation" in joined and "pricing experiment" not in joined
    assert len(c.get(f"/api/sessions/{s1}", headers=UID).json()["messages"]) == 4
    assert len(c.get(f"/api/sessions/{s2}", headers=UID).json()["messages"]) == 2
    assert c.get(f"/api/sessions/{s1}", headers=UID2).status_code == 404  # other user cannot read
    assert _post(c, s1, "hello there friend", headers=UID2).status_code == 404
    assert len(c.get("/api/sessions", headers=UID).json()) == 2 and c.get("/api/sessions", headers=UID2).json() == []


def test_off_topic_question_is_refused_without_calling_llm(client_factory):
    c, ollama, _ = client_factory()
    sid = new_session(c)
    a = _post(c, sid, "best sourdough bread recipe").json()["assistant_message"]
    assert a["kind"] == "refusal" and a["sources"] == [] and not ollama.calls


def test_model_can_self_report_not_supported(client_factory):
    c, *_ = client_factory(ollama_fn=lambda m, n: "NOT_SUPPORTED: The excerpts only discuss onboarding.")
    sid = new_session(c)
    a = _post(c, sid, "How do I improve onboarding activation?").json()["assistant_message"]
    assert a["kind"] == "refusal" and a["content"].startswith("The excerpts only") and a["sources"] == []


def test_invalid_citations_removed_and_uncited_answers_flagged(client_factory):
    c, *_ = client_factory(ollama_fn=lambda m, n: "Activation matters [S1] and [S9].")
    sid = new_session(c)
    a = _post(c, sid, "How do I improve onboarding activation?").json()["assistant_message"]
    assert "[S9]" not in a["content"] and a["meta"]["invalid_citations_removed"] == 1
    c2, *_ = client_factory(ollama_fn=lambda m, n: "Activation matters a lot.")
    sid = new_session(c2)
    a = _post(c2, sid, "How do I improve onboarding activation?").json()["assistant_message"]
    assert a["meta"]["uncited"] is True and "did not cite" in a["content"]


def test_provider_toggle_per_request_and_session_default(client_factory):
    c, ollama, anth = client_factory()
    sid = new_session(c)
    a = _post(c, sid, "How do I improve onboarding activation?", provider="anthropic").json()["assistant_message"]
    assert a["provider"] == "anthropic" and anth.calls and not ollama.calls
    assert c.get("/api/sessions", headers=UID).json()[0]["provider"] == "anthropic"


def test_llm_failure_returns_structured_error_and_persists_nothing(client_factory):
    c, *_ = client_factory(ollama_error=LLMUnavailable("Cannot reach Ollama"))
    sid = new_session(c)
    r = _post(c, sid, "How do I improve onboarding activation?")
    assert r.status_code == 503 and r.json()["error"]["code"] == "LLM_UNAVAILABLE"
    assert c.get(f"/api/sessions/{sid}", headers=UID).json()["messages"] == []
    c2, *_ = client_factory(ollama_error=LLMTimeout("slow"))
    assert _post(c2, new_session(c2), "How do I improve onboarding activation?").status_code == 504


def test_fallback_provider_used_when_primary_fails(seeded, client_factory):
    seeded.fallback_provider = "anthropic"
    c, ollama, anth = client_factory(ollama_error=LLMUnavailable("down"))
    r = _post(c, new_session(c), "How do I improve onboarding activation?").json()
    assert r["fallback_used"] is True and r["assistant_message"]["provider"] == "anthropic"
    seeded.fallback_provider = ""


def test_essay_skill_repairs_length_and_creates_artifact(client_factory):
    short = "# How to fix activation without more tooltips\n\n" + "Alice Example says cut steps [S1]. " + "word " * 200
    long = "# How to fix activation without more tooltips\n\n## Cut steps\n\n" + "Alice Example says cut steps [S1]. " + "word " * 1200
    c, ollama, _ = client_factory(ollama_fn=lambda m, n: short if n == 1 else long)
    sid = new_session(c)
    r = _post(c, sid, "Write a Ship 30 for 30 essay about onboarding activation").json()["assistant_message"]
    assert r["kind"] == "essay" and r["meta"]["repair_passes"] == 1 and r["meta"]["length_ok"] is True
    assert 1000 <= r["meta"]["word_count"] <= 1500 and r["artifact"]["type"] == "markdown"
    assert "Ship 30" in ollama.calls[0][0]["content"] and "Headline first" in ollama.calls[0][0]["content"]  # skill loaded
    art = c.get(f"/api/artifacts/{r['artifact']['id']}", headers=UID).json()
    assert "## Sources" in art["content"] and "Alice Example" in art["content"] and "<h1>" in art["render_document"]


def test_html_artifact_is_sanitised_on_read(client_factory):
    evil = ('Built it.\n<artifact type="html" title="Plan"><h1 onclick="x()">Plan</h1><script>alert(1)</script>'
            '<style>body{background:url(http://evil.example/x)}</style><p>Alice Example on activation steps</p></artifact>')
    c, *_ = client_factory(ollama_fn=lambda m, n: evil)
    sid = new_session(c)
    r = _post(c, sid, "Create an HTML page about onboarding activation").json()["assistant_message"]
    assert r["kind"] == "artifact" and r["artifact"]["type"] == "html"
    art = c.get(f"/api/artifacts/{r['artifact']['id']}", headers=UID).json()
    doc = art["render_document"]
    assert "<script" not in doc.lower() and "onclick" not in doc and "evil.example" not in doc
    assert "<script>alert(1)</script>" in art["content"]  # raw stays available in the Source tab
    assert c.get(f"/api/artifacts/{art['id']}", headers=UID2).status_code == 404
    dl = c.get(f"/api/artifacts/{art['id']}/download", headers=UID)
    assert "attachment" in dl.headers["content-disposition"] and dl.headers["content-type"].startswith("text/plain")


def test_unparseable_html_artifact_returns_502(client_factory):
    c, *_ = client_factory(ollama_fn=lambda m, n: "Sure, I would make a page but here is just prose.")
    r = _post(c, new_session(c), "Create an HTML page about onboarding activation")
    assert r.status_code == 502 and r.json()["error"]["code"] == "ARTIFACT_PARSE_FAILED"


def test_artifact_followup_uses_conversation_context(client_factory):
    md = 'Made it.\n<artifact type="markdown" title="Checklist">\n# Checklist\n\n- cut steps (Alice Example)\n- test invites\n</artifact>'
    c, ollama, _ = client_factory(ollama_fn=lambda m, n: "Alice says cut steps [S1]." if n == 1 else md)
    sid = new_session(c)
    _post(c, sid, "How do I improve onboarding activation?")
    r = _post(c, sid, "make that a markdown checklist").json()["assistant_message"]
    assert r["kind"] == "artifact"
    assert any("cut steps" in m["content"] for m in ollama.calls[1] if m["role"] == "assistant")


def test_chitchat_needs_no_llm(client_factory):
    c, ollama, _ = client_factory()
    a = _post(c, new_session(c), "hi").json()["assistant_message"]
    assert a["kind"] == "chitchat" and not ollama.calls


def test_empty_knowledge_base_is_reported(settings):
    c, *_ = make_client(settings)  # tables created by app lifespan, nothing ingested
    sid = new_session(c)
    r = _post(c, sid, "How do I improve onboarding activation?")
    assert r.status_code == 503 and r.json()["error"]["code"] == "KB_EMPTY"
    assert c.get("/health/ready").status_code == 503
    c.__exit__(None, None, None)


def test_database_failure_is_a_structured_503(client_factory):
    c, *_ = client_factory()
    sid = new_session(c)
    with c.app.state.engine.begin() as conn:
        conn.execute(text("DROP TABLE messages"))
    r = c.get(f"/api/sessions/{sid}", headers=UID)
    assert r.status_code == 503 and r.json()["error"]["code"] == "DB_UNAVAILABLE"


def test_config_endpoint_and_search_debug(client_factory):
    c, *_ = client_factory()
    cfg = c.get("/api/config").json()
    assert {p["name"] for p in cfg["providers"]} == {"ollama", "anthropic"} and cfg["knowledge_base"]["episodes"] == 2
    s = c.get("/api/search", params={"q": "pricing experiment"}).json()
    assert s["passages"][0]["guest"] == "Bob Sample"


def test_delete_session_cascades(client_factory):
    c, *_ = client_factory()
    sid = new_session(c)
    _post(c, sid, "How do I improve onboarding activation?")
    assert c.delete(f"/api/sessions/{sid}", headers=UID).status_code == 204
    assert c.get(f"/api/sessions/{sid}", headers=UID).status_code == 404


def test_offtopic_after_ontopic_is_not_rescued_by_earlier_context(client_factory):
    c, ollama, _ = client_factory()
    sid = new_session(c)
    _post(c, sid, "How do I improve onboarding activation?")
    n = len(ollama.calls)
    a = _post(c, sid, "best sourdough bread recipe").json()["assistant_message"]
    assert a["kind"] == "refusal" and len(ollama.calls) == n
    # and the refusal does not poison a later legitimate essay request
    e = _post(c, sid, "Write a Ship 30 for 30 essay about activation").json()["assistant_message"]
    assert e["kind"] == "essay"


def test_true_followup_borrows_context(client_factory):
    c, ollama, _ = client_factory()
    sid = new_session(c)
    _post(c, sid, "How do I improve onboarding activation?")
    a = _post(c, sid, "and why does that matter?").json()["assistant_message"]
    assert a["kind"] == "chat" and a["sources"][0]["guest"] == "Alice Example"
