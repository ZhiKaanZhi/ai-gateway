"""Application settings — typed configuration loaded from the environment / ``.env``.

One ``Settings`` object, read once and cached. Defaults match ``docker-compose.yml`` so the app
runs out of the box against the local pgvector container.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Gateway configuration. Override any field via ``GATEWAY_<FIELD>`` env vars or ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- HTTP server (used by `python -m gateway`) ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- PostgreSQL (defaults mirror docker-compose.yml) ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "gateway"
    db_password: str = "gateway"
    db_name: str = "gateway"

    # --- Embeddings (local ONNX via fastembed) ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # --- Cache similarity gates (1 - cosine distance). Intent tier needs the strongest gate. ---
    semantic_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    intent_threshold: float = Field(default=0.97, ge=0.0, le=1.0)

    # --- Model backend (OpenAI-compatible; local Ollama is the free dev default) ---
    backend_base_url: str = "http://localhost:11434/v1"
    backend_model: str = "gemma3:1b"  # run `ollama pull gemma3:1b`
    # Masked so a stray log or settings dump never leaks a live key once the URL points at a paid
    # provider. Blank default → the adapter omits the auth header entirely.
    backend_api_key: SecretStr = SecretStr("")
    backend_timeout: float = 30.0

    @property
    def conninfo(self) -> str:
        """libpq connection string for psycopg / the async pool."""
        return (
            f"host={self.db_host} port={self.db_port} "
            f"user={self.db_user} password={self.db_password} dbname={self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached after first read)."""
    return Settings()
