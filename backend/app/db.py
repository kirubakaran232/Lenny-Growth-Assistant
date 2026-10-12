"""SQLAlchemy models. JSON columns use the generic JSON type (JSONB on Postgres is a later optimisation)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)  # anonymous browser id
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    provider: Mapped[str] = mapped_column(String(20))
    user_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at")
    artifacts: Mapped[list["Artifact"]] = relationship(
        cascade="all, delete-orphan", order_by="Artifact.created_at")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    kind: Mapped[str] = mapped_column(String(16), default="chat")  # chat|essay|artifact|refusal|chitchat
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    session: Mapped[ChatSession] = relationship(back_populates="messages")


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(12))  # markdown | html
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)  # raw model output; sanitised on read
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_slug: Mapped[str] = mapped_column(String(200), index=True)
    guest: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(400))
    youtube_url: Mapped[str] = mapped_column(String(300), default="")
    publish_date: Mapped[str] = mapped_column(String(20), default="")
    chunk_index: Mapped[int] = mapped_column(Integer)
    start_ts: Mapped[str] = mapped_column(String(12), default="00:00:00")
    start_seconds: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)


def make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
