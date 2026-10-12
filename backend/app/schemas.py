import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


class SessionCreate(BaseModel):
    provider: Literal["ollama", "anthropic"] | None = None
    title: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _small(cls, v):
        if len(json.dumps(v)) > 2048:
            raise ValueError("metadata must be under 2 KB")
        return v


class SessionOut(BaseModel):
    id: str
    title: str
    provider: str
    created_at: datetime
    updated_at: datetime


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    provider: Literal["ollama", "anthropic"] | None = None

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v):
        if not v.strip():
            raise ValueError("content must not be blank")
        return v.strip()


class ArtifactRef(BaseModel):
    id: str
    title: str
    type: str


class MessageOut(BaseModel):
    id: str
    role: str
    kind: str
    content: str
    content_html: str
    sources: list[dict]
    provider: str | None
    model: str | None
    latency_ms: int | None
    meta: dict
    artifact: ArtifactRef | None = None
    created_at: datetime


class SessionDetail(SessionOut):
    messages: list[MessageOut]


class PostMessageOut(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
    fallback_used: bool


class ArtifactOut(BaseModel):
    id: str
    session_id: str
    type: str
    title: str
    content: str
    render_document: str  # sanitised, CSP-wrapped document for <iframe sandbox srcdoc>
    created_at: datetime
