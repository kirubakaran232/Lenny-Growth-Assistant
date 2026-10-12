"""Groq LLM provider — uses the OpenAI-compatible /openai/v1/chat/completions endpoint."""
import httpx

from .base import LLMNotConfigured, LLMResult, LLMTimeout, LLMUnavailable, ProviderStatus


class GroqProvider:
    name = "groq"
    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model: str, timeout: float):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, messages, *, max_tokens: int = 1200, temperature: float = 0.3) -> LLMResult:
        if not self.api_key:
            raise LLMNotConfigured("GROQ_API_KEY is not set. Add it to .env or switch LLM_PROVIDER.")
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            r = httpx.post(
                f"{self.BASE_URL}/chat/completions",
                json=body,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"Groq API timed out after {self.timeout:.0f}s") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Cannot reach Groq API: {e}") from e

        if r.status_code in (401, 403):
            raise LLMNotConfigured("Groq rejected the API key (401/403). Check GROQ_API_KEY.")
        if r.status_code >= 400:
            raise LLMUnavailable(f"Groq API returned HTTP {r.status_code}: {r.text[:200]}")

        data = r.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        model_used = data.get("model", self.model)
        return LLMResult(text, model_used, usage)

    def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(self.name, self.model, False, False, "GROQ_API_KEY not set")
        if not self.api_key.startswith("gsk_"):
            return ProviderStatus(self.name, self.model, False, False,
                                  "GROQ_API_KEY looks invalid (expected gsk_… format)")
        return ProviderStatus(self.name, self.model, True, True)
