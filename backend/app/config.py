"""Central configuration. Everything is overridable by environment variable / .env."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "anthropic", "groq"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- database ---
    database_url: str = "postgresql+psycopg://lenny:lenny@db:5432/lenny"

    # --- model selection (switchable without code changes) ---
    llm_provider: ProviderName = "ollama"
    fallback_provider: str = ""  # "", "ollama" or "anthropic"; "" disables fallback
    llm_timeout_s: float = 180.0
    llm_temperature: float = 0.3

    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_num_ctx: int = 8192

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # --- knowledge base ---
    kb_path: str = "data/lennys-podcast-transcripts/episodes"
    kb_repo_url: str = "https://github.com/ChatPRD/lennys-podcast-transcripts"
    auto_ingest: bool = True
    chunk_words: int = 280
    chunk_overlap_turns: int = 1
    retrieval_top_k: int = 6
    max_chunks_per_episode: int = 2
    min_query_coverage: float = 0.5  # idf-weighted share of query terms the best chunk must contain

    # --- misc ---
    log_level: str = "INFO"
    admin_token: str = ""  # enables POST /api/kb/reload when set
    history_messages: int = 6
    rate_limit_per_minute: int = 20  # max messages per user per 60 s; 0 disables the check


@lru_cache
def get_settings() -> Settings:
    return Settings()
