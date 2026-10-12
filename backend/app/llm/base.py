"""Provider-agnostic LLM interface and error taxonomy."""
from dataclasses import dataclass, field
from typing import Protocol


class LLMError(Exception):
    """Base class. `code` maps 1:1 to an API error code."""
    code = "LLM_ERROR"
    http_status = 502


class LLMNotConfigured(LLMError):
    code, http_status = "LLM_NOT_CONFIGURED", 503


class LLMUnavailable(LLMError):
    code, http_status = "LLM_UNAVAILABLE", 503


class LLMTimeout(LLMError):
    code, http_status = "LLM_TIMEOUT", 504


@dataclass
class LLMResult:
    text: str
    model: str
    usage: dict = field(default_factory=dict)


@dataclass
class ProviderStatus:
    name: str
    model: str
    configured: bool
    available: bool
    reason: str = ""


class LLMProvider(Protocol):
    name: str
    model: str

    def chat(self, messages: list[dict], *, max_tokens: int = 1200, temperature: float = 0.3) -> LLMResult: ...
    def status(self) -> ProviderStatus: ...
