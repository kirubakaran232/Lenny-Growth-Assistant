import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base, make_engine
from app.kb.ingest import ingest_path
from app.llm.base import LLMNotConfigured, LLMResult, LLMUnavailable, ProviderStatus
from app.llm.registry import ProviderRegistry
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "episodes"
UID = {"X-User-Id": "user-test-0001"}
UID2 = {"X-User-Id": "user-test-0002"}


class FakeProvider:
    def __init__(self, name, fn=None, error=None):
        self.name, self.model, self.fn, self.error, self.calls = name, f"fake-{name}", fn, error, []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return LLMResult(self.fn(messages, len(self.calls)), self.model, {})

    def status(self):
        return ProviderStatus(self.name, self.model, True, self.error is None)


class FakeRegistry(ProviderRegistry):
    def __init__(self, settings, ollama, anthropic):
        self.s, self._p = settings, {"ollama": ollama, "anthropic": anthropic}


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, database_url=f"sqlite:///{tmp_path}/t.db", auto_ingest=False, log_level="WARNING", rate_limit_per_minute=0)


@pytest.fixture
def seeded(settings):
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        ingest_path(db, FIXTURES, settings)
    engine.dispose()
    return settings


def make_client(settings, ollama_fn=None, ollama_error=None, anthropic_fn=None, anthropic_error=None):
    ollama = FakeProvider("ollama", ollama_fn or (lambda m, n: "Alice Example says activation drives retention [S1]."), ollama_error)
    anth = FakeProvider("anthropic", anthropic_fn or (lambda m, n: "Claude says [S1]."), anthropic_error)
    app = create_app(settings)
    client = TestClient(app)
    client.__enter__()
    app.state.providers = FakeRegistry(settings, ollama, anth)
    app.state.orchestrator.providers = app.state.providers
    return client, ollama, anth


@pytest.fixture
def client_factory(seeded):
    made = []

    def _make(**kw):
        c, o, a = make_client(seeded, **kw)
        made.append(c)
        return c, o, a

    yield _make
    for c in made:
        c.__exit__(None, None, None)


def new_session(client, headers=UID, **body):
    r = client.post("/api/sessions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]
