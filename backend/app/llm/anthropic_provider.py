import httpx

from .base import LLMNotConfigured, LLMResult, LLMTimeout, LLMUnavailable, ProviderStatus


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float, base_url: str = "https://api.anthropic.com"):
        self.api_key, self.model, self.timeout, self.base_url = api_key, model, timeout, base_url.rstrip("/")

    def chat(self, messages, *, max_tokens=1200, temperature=0.3) -> LLMResult:
        if not self.api_key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY is not set. Add it to .env or switch LLM_PROVIDER=ollama.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "messages": convo}
        if system:
            body["system"] = system
        try:
            r = httpx.post(f"{self.base_url}/v1/messages", json=body, timeout=self.timeout,
                           headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"Anthropic API timed out after {self.timeout:.0f}s") from e
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Cannot reach Anthropic API: {e}") from e
        if r.status_code in (401, 403):
            raise LLMNotConfigured("Anthropic rejected the API key (401/403). Check ANTHROPIC_API_KEY.")
        if r.status_code >= 400:
            raise LLMUnavailable(f"Anthropic API returned HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return LLMResult(text, data.get("model", self.model), data.get("usage", {}))

    def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(self.name, self.model, False, False, "ANTHROPIC_API_KEY not set")
        if not self.api_key.startswith("sk-ant-"):
            return ProviderStatus(self.name, self.model, False, False,
                                  "ANTHROPIC_API_KEY looks invalid (expected sk-ant-… format)")
        return ProviderStatus(self.name, self.model, True, True)  # no network probe: avoids spending tokens
