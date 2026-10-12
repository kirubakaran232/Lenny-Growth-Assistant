import collections
import logging
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import schemas
from .agent.orchestrator import Orchestrator
from .config import Settings, get_settings
from .db import Artifact, Base, ChatSession, Message, make_engine, utcnow
from .errors import ApiError
from .kb.index import KnowledgeIndex
from .kb.ingest import fetch_transcripts, ingest_path
from .llm.registry import ProviderRegistry
from .logging_setup import request_id_var, setup_logging
from .sanitize import build_sandbox_document, render_markdown

log = logging.getLogger("api")
def _find_frontend() -> Path:
    here = Path(__file__).resolve()
    # repo layout: <root>/backend/app/main.py ; Docker layout: /app/app/main.py with /app/frontend
    for base in (here.parents[2], here.parents[1]):
        if (base / "frontend" / "static" / "index.html").exists():
            return base / "frontend" / "static"
    return here.parents[2] / "frontend" / "static"


FRONTEND = _find_frontend()
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

_RL_LOCK = threading.Lock()
_RL_WINDOWS: dict[str, collections.deque] = {}


def _check_rate_limit(user_id: str, per_minute: int) -> None:
    """Sliding-window rate limiter. Raises ApiError(429) when the user exceeds the limit."""
    if per_minute <= 0:
        return
    now = time.time()
    with _RL_LOCK:
        dq = _RL_WINDOWS.setdefault(user_id, collections.deque())
        while dq and dq[0] < now - 60:
            dq.popleft()
        if len(dq) >= per_minute:
            raise ApiError(429, "RATE_LIMITED",
                           f"Too many requests. Limit is {per_minute} messages per minute.")
        dq.append(now)


def _bootstrap_kb(app: FastAPI) -> None:
    """Runs in a background thread so the API is up immediately while a first-time ingest runs."""
    s: Settings = app.state.settings
    idx: KnowledgeIndex = app.state.index
    try:
        idx.state = "ingesting"
        fetch_transcripts(s)
        with app.state.SessionLocal() as db:
            ingest_path(db, Path(s.kb_path), s)
            idx.load(db)
    except Exception as e:  # noqa: BLE001
        idx.state, idx.error = "error", f"{type(e).__name__}: {e}"
        log.exception("knowledge base bootstrap failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        app.state.settings = settings
        app.state.engine = make_engine(settings.database_url)
        app.state.SessionLocal = sessionmaker(app.state.engine, expire_on_commit=False)
        app.state.db_ok = False
        for attempt in range(1, 6):  # the DB container may still be starting
            try:
                Base.metadata.create_all(app.state.engine)
                app.state.db_ok = True
                break
            except Exception as e:  # noqa: BLE001
                log.warning("database not ready", extra={"attempt": attempt, "error": str(e)[:200]})
                time.sleep(2)
        app.state.index = KnowledgeIndex()
        app.state.providers = ProviderRegistry(settings)
        app.state.orchestrator = Orchestrator(settings, app.state.index, app.state.providers)
        if app.state.db_ok:
            with app.state.SessionLocal() as db:
                app.state.index.load(db)
            if app.state.index.size == 0 and settings.auto_ingest:
                threading.Thread(target=_bootstrap_kb, args=(app,), daemon=True).start()
        else:
            log.error("starting without database; /health/ready will report not ready")
        log.info("startup complete", extra={"provider": settings.llm_provider, "fallback": settings.fallback_provider or None,
                                            "kb_chunks": app.state.index.size})
        yield

    app = FastAPI(title="Lenny Growth Assistant", version="1.0.0", lifespan=lifespan)

    # ---------- middleware ----------
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        t0 = time.time()
        try:
            response = await call_next(request)
        finally:
            ms = int((time.time() - t0) * 1000)
            request_id_var.reset(token)
        request_id_var.set(rid)
        response.headers["X-Request-ID"] = rid
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api") or request.url.path.startswith("/health"):
            response.headers["Cache-Control"] = "no-store"
            log.info("request", extra={"method": request.method, "path": request.url.path,
                                       "status": response.status_code, "ms": ms})
        return response

    # ---------- error handlers ----------
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return JSONResponse(e.body(), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        details = [{"field": ".".join(str(x) for x in err["loc"][1:]), "message": err["msg"]} for err in e.errors()]
        return JSONResponse(ApiError(422, "VALIDATION_ERROR", "Request validation failed.", details).body(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        return JSONResponse(ApiError(e.status_code, "HTTP_ERROR", str(e.detail)).body(), status_code=e.status_code)

    @app.exception_handler(DBAPIError)
    async def _db(_: Request, e: DBAPIError):
        log.error("database error", extra={"error": str(e.orig)[:300]})
        return JSONResponse(ApiError(503, "DB_UNAVAILABLE", "The database is unavailable. Please retry shortly.").body(), status_code=503)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        log.exception("unhandled error")
        return JSONResponse(ApiError(500, "INTERNAL_ERROR", "Unexpected server error.").body(), status_code=500)

    # ---------- dependencies ----------
    def get_db(request: Request):
        with request.app.state.SessionLocal() as db:
            yield db

    def user_id_header(x_user_id: str = Header(default="")) -> str:
        if not schemas.USER_ID_RE.match(x_user_id):
            raise ApiError(400, "MISSING_USER_ID", "Send a pseudonymous X-User-Id header (8-64 chars: letters, digits, _ or -).")
        return x_user_id

    def owned_session(sid: str, db: Session, user_id: str) -> ChatSession:
        s = db.get(ChatSession, sid)
        if not s or s.user_id != user_id:  # same response for missing and foreign sessions
            raise ApiError(404, "SESSION_NOT_FOUND", "Session not found.")
        return s

    def msg_out(m: Message, art: Artifact | None = None) -> schemas.MessageOut:
        html = render_markdown(m.content, link_citations=True) if m.role == "assistant" else ""
        return schemas.MessageOut(
            id=m.id, role=m.role, kind=m.kind, content=m.content, content_html=html, sources=m.sources or [],
            provider=m.provider, model=m.model, latency_ms=m.latency_ms, meta=m.meta or {}, created_at=m.created_at,
            artifact=schemas.ArtifactRef(id=art.id, title=art.title, type=art.type) if art else None)

    # ---------- health ----------
    @app.get("/health", tags=["ops"])
    def health():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["ops"])
    def ready(request: Request):
        st = request.app.state
        checks: dict = {}
        try:
            with st.SessionLocal() as db:
                db.execute(text("SELECT 1"))
            checks["database"] = {"ok": True}
        except Exception as e:  # noqa: BLE001
            checks["database"] = {"ok": False, "error": str(e)[:200]}
        idx = st.index
        checks["knowledge_base"] = {"ok": idx.size > 0, "state": idx.state, "chunks": idx.size,
                                    "episodes": idx.episodes, "error": idx.error}
        checks["llm"] = {n: st.providers.get(n).status().__dict__ for n in st.providers.names()}
        ok = checks["database"]["ok"] and checks["knowledge_base"]["ok"]
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)

    # ---------- config ----------
    @app.get("/api/config", tags=["config"])
    def config(request: Request):
        st = request.app.state
        return {"default_provider": settings.llm_provider, "fallback_provider": settings.fallback_provider or None,
                "providers": [st.providers.get(n).status().__dict__ for n in st.providers.names()],
                "knowledge_base": {"state": st.index.state, "chunks": st.index.size, "episodes": st.index.episodes}}

    # ---------- sessions ----------
    @app.post("/api/sessions", response_model=schemas.SessionOut, status_code=201, tags=["sessions"])
    def create_session(body: schemas.SessionCreate, request: Request, db: Session = Depends(get_db),
                       user_id: str = Depends(user_id_header)):
        s = ChatSession(user_id=user_id, title=body.title or "New chat", provider=body.provider or settings.llm_provider,
                        user_metadata={"user_agent": request.headers.get("user-agent", "")[:200],
                                       "accept_language": request.headers.get("accept-language", "")[:50], **body.metadata})
        db.add(s)
        db.commit()
        log.info("session created", extra={"session_id": s.id, "provider": s.provider})
        return s

    @app.get("/api/sessions", response_model=list[schemas.SessionOut], tags=["sessions"])
    def list_sessions(db: Session = Depends(get_db), user_id: str = Depends(user_id_header)):
        return db.query(ChatSession).filter_by(user_id=user_id).order_by(ChatSession.updated_at.desc()).limit(100).all()

    @app.get("/api/sessions/{sid}", response_model=schemas.SessionDetail, tags=["sessions"])
    def get_session(sid: str, db: Session = Depends(get_db), user_id: str = Depends(user_id_header)):
        s = owned_session(sid, db, user_id)
        arts = {a.message_id: a for a in s.artifacts}
        return schemas.SessionDetail(id=s.id, title=s.title, provider=s.provider, created_at=s.created_at,
                                     updated_at=s.updated_at, messages=[msg_out(m, arts.get(m.id)) for m in s.messages])

    @app.delete("/api/sessions/{sid}", status_code=204, tags=["sessions"])
    def delete_session(sid: str, db: Session = Depends(get_db), user_id: str = Depends(user_id_header)):
        db.delete(owned_session(sid, db, user_id))
        db.commit()

    @app.post("/api/sessions/{sid}/messages", response_model=schemas.PostMessageOut, tags=["chat"])
    def post_message(sid: str, body: schemas.MessageIn, db: Session = Depends(get_db),
                     user_id: str = Depends(user_id_header)):
        s = owned_session(sid, db, user_id)
        _check_rate_limit(user_id, settings.rate_limit_per_minute)
        provider = body.provider or s.provider
        if db.query(Message).filter_by(session_id=s.id).count() == 0 and s.title == "New chat":
            s.title = body.content[:60]
        history = list(s.messages)
        # attempt a lazy reload if the index is empty (e.g. DB was down at boot)
        request_index(db)
        result = request_orchestrator().handle(history, body.content, provider)
        now = utcnow()
        um = Message(session_id=s.id, role="user", kind="chat", content=body.content, created_at=now)
        am = Message(session_id=s.id, role="assistant", kind=result.kind, content=result.text,
                     sources=result.sources, provider=result.provider, model=result.model,
                     latency_ms=result.latency_ms, created_at=now + timedelta(milliseconds=1),
                     meta={**result.meta, "intent": result.route.intent if result.route else None,
                           "fallback_used": result.fallback_used})
        db.add_all([um, am])
        db.flush()
        art = None
        if result.artifact:
            art = Artifact(session_id=s.id, message_id=am.id, type=result.artifact.type,
                           title=result.artifact.title, content=result.artifact.content)
            db.add(art)
        if body.provider:
            s.provider = body.provider
        s.updated_at = utcnow()
        db.commit()
        return schemas.PostMessageOut(user_message=msg_out(um), assistant_message=msg_out(am, art),
                                      fallback_used=result.fallback_used)

    # helpers bound late so tests can swap app.state components
    def request_orchestrator() -> Orchestrator:
        return app.state.orchestrator

    def request_index(db: Session) -> KnowledgeIndex:
        idx = app.state.index
        if idx.size == 0 and idx.state not in ("ingesting",) and time.time() - idx.last_load_attempt > 30:
            try:
                idx.load(db)
            except Exception:  # noqa: BLE001
                log.exception("lazy index reload failed")
        return idx

    # ---------- artifacts ----------
    def owned_artifact(aid: str, db: Session, user_id: str) -> Artifact:
        a = db.get(Artifact, aid)
        if not a or not db.get(ChatSession, a.session_id) or db.get(ChatSession, a.session_id).user_id != user_id:
            raise ApiError(404, "ARTIFACT_NOT_FOUND", "Artifact not found.")
        return a

    @app.get("/api/artifacts/{aid}", response_model=schemas.ArtifactOut, tags=["artifacts"])
    def get_artifact(aid: str, db: Session = Depends(get_db), user_id: str = Depends(user_id_header)):
        a = owned_artifact(aid, db, user_id)
        try:
            doc = build_sandbox_document(a.type, a.content)
        except Exception as e:  # noqa: BLE001
            log.exception("artifact render failed", extra={"artifact_id": a.id})
            raise ApiError(500, "ARTIFACT_RENDER_FAILED", "This artifact could not be rendered safely.") from e
        return schemas.ArtifactOut(id=a.id, session_id=a.session_id, type=a.type, title=a.title, content=a.content,
                                   render_document=doc, created_at=a.created_at)

    @app.get("/api/artifacts/{aid}/download", tags=["artifacts"])
    def download_artifact(aid: str, db: Session = Depends(get_db), user_id: str = Depends(user_id_header)):
        a = owned_artifact(aid, db, user_id)
        slug = re.sub(r"[^a-z0-9]+", "-", a.title.lower()).strip("-")[:60] or "artifact"
        ext = "html" if a.type == "html" else "md"
        return PlainTextResponse(a.content, headers={"Content-Disposition": f'attachment; filename="{slug}.{ext}"'})

    # ---------- knowledge base ----------
    @app.get("/api/search", tags=["knowledge-base"])
    def search(q: str = Query(min_length=2, max_length=300), k: int = Query(5, ge=1, le=20)):
        res = app.state.index.search(q, k, settings.max_chunks_per_episode)
        return {"query": q, "best_coverage": res.best_coverage, "passages": [
            {"guest": p.guest, "title": p.title, "timestamp": p.timestamp, "url": p.deep_link, "score": p.score,
             "coverage": p.coverage, "text": p.text[:500]} for p in res.passages]}

    @app.post("/api/kb/reload", tags=["knowledge-base"])
    def reload_kb(db: Session = Depends(get_db), x_admin_token: str = Header(default="")):
        if not settings.admin_token or x_admin_token != settings.admin_token:
            raise ApiError(403, "FORBIDDEN", "Reload is disabled or the admin token is wrong.")
        return {"chunks": app.state.index.load(db)}

    # ---------- frontend ----------
    if not FRONTEND.exists():
        log.error("frontend directory not found", extra={"path": str(FRONTEND)})
    if FRONTEND.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")

        @app.get("/", include_in_schema=False)
        def index_page():
            return FileResponse(FRONTEND / "index.html")

    return app