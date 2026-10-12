"""Builds providers from settings; implements primary -> fallback selection."""
import logging

from ..config import Settings
from .anthropic_provider import AnthropicProvider
from .base import LLMError, LLMProvider, LLMResult
from .groq_provider import GroqProvider
from .ollama import OllamaProvider

log = logging.getLogger("llm")


class ProviderRegistry:
    def __init__(self, settings: Settings):
        self.s = settings
        self._p: dict[str, LLMProvider] = {
            "ollama": OllamaProvider(settings.ollama_base_url, settings.ollama_model,
                                     settings.llm_timeout_s, settings.ollama_num_ctx),
            "anthropic": AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model,
                                           settings.llm_timeout_s, settings.anthropic_base_url),
            "groq": GroqProvider(settings.groq_api_key, settings.groq_model,
                                 settings.llm_timeout_s),
        }

    def get(self, name: str) -> LLMProvider:
        return self._p[name]

    def names(self) -> list[str]:
        return list(self._p)

    def chat_with_fallback(self, primary: str, messages, **kw) -> tuple[LLMResult, str, bool]:
        """Returns (result, provider_used, fallback_used). Raises the primary error if no fallback works."""
        try:
            return self._p[primary].chat(messages, **kw), primary, False
        except LLMError as primary_err:
            fb = self.s.fallback_provider
            log.warning("primary provider failed", extra={"provider": primary, "error": str(primary_err),
                                                          "code": primary_err.code, "fallback": fb or None})
            if fb and fb != primary and fb in self._p:
                try:
                    return self._p[fb].chat(messages, **kw), fb, True
                except LLMError as fb_err:
                    log.error("fallback provider failed", extra={"provider": fb, "error": str(fb_err)})
            raise primary_err
