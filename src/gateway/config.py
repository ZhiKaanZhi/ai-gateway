"""Application settings — typed configuration loaded from the environment / ``.env``.

One ``Settings`` object, read once and cached. Defaults match ``docker-compose.yml`` so the app
runs out of the box against the local pgvector container.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Gateway configuration. Override any field via ``GATEWAY_<FIELD>`` env vars or ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
