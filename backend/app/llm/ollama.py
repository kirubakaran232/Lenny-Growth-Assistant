import httpx

from .base import LLMNotConfigured, LLMResult, LLMTimeout, LLMUnavailable, ProviderStatus


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float, num_ctx: int):
        self.base_url, self.model, self.timeout, self.num_ctx = base_url.rstrip("/"), model, timeout, num_ctx

    def chat(self, messages, *, max_tokens=1200, temperature=0.3) -> LLMResult:
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": self.num_ctx}}
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"Ollama did not answer within {self.timeout:.0f}s (model {self.model}). "
                             "Try a smaller model or raise LLM_TIMEOUT_S.") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Cannot reach Ollama at {self.base_url}. Is `ollama serve` running? ({e})") from e
        if r.status_code == 404:
            raise LLMNotConfigured(f"Ollama model '{self.model}' is not installed. Run: ollama pull {self.model}")
        if r.status_code >= 400:
            raise LLMUnavailable(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        text = (data.get("message") or {}).get("content", "")
        return LLMResult(text, self.model, {"prompt_tokens": data.get("prompt_eval_count"),
                                            "completion_tokens": data.get("eval_count")})

    def status(self) -> ProviderStatus:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            if r.status_code >= 400:
                return ProviderStatus(self.name, self.model, True, False,
                                      f"Ollama /api/tags returned HTTP {r.status_code}")
            names = {m.get("name", "") for m in r.json().get("models", [])}
        except Exception:  # noqa: BLE001 - health probe must never raise
            return ProviderStatus(self.name, self.model, True, False, f"Ollama unreachable at {self.base_url}")
        if not any(n == self.model or n.split(":")[0] == self.model for n in names):
            return ProviderStatus(self.name, self.model, True, False, f"model not pulled: ollama pull {self.model}")
        return ProviderStatus(self.name, self.model, True, True)
