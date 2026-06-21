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

    # --- Cache similarity gate (1 - cosine distance). ---
    semantic_threshold: float = Field(default=0.95, ge=0.0, le=1.0)

    # --- Intent tier: candidate retrieval threshold (on stripped-prompt vectors). ---
    # Not a "tighter gate" than semantic — it searches a *different* space (canonical prompts).
    # Lower than semantic because stripping parameters shifts the embedding distribution.
    # See D26 + GLOSSARY.md: confidence (the gate) is distinct from similarity (this threshold).
    intent_match_threshold: float = Field(default=0.90, ge=0.0, le=1.0)

    # --- Eval baseline (D30): cosine-only baseline serves if similarity >= this. ---
    # This is the "D10 collapsed idea" — the thing the intent gate proves is insufficient.
    cosine_baseline_threshold: float = Field(default=0.97, ge=0.0, le=1.0)

    # --- Intent gate signals (D26). Calibrate from the eval set, not by guessing. ---
    # margin_min: top1–top2 similarity difference required for a clear match.
    intent_margin_min: float = Field(default=0.05, ge=0.0, le=1.0)
    # staleness_max_seconds: entries older than this are always refused.
    intent_staleness_max_seconds: float = Field(default=86400.0, gt=0.0)  # 24 h default
    # verify_band_lo/hi: base-confidence band where the Verifier is called.
    intent_verify_band_lo: float = Field(default=0.70, ge=0.0, le=1.0)
    intent_verify_band_hi: float = Field(default=0.85, ge=0.0, le=1.0)
    # verify_pass_threshold: Verifier score required to serve (precision-biased).
    intent_verify_pass_threshold: float = Field(default=0.80, ge=0.0, le=1.0)

    # --- Model backend (OpenAI-compatible; local Ollama is the free dev default) ---
    backend_base_url: str = "http://localhost:11434/v1"
    backend_model: str = "gemma3:1b"  # run `ollama pull gemma3:1b`
    # Masked so a stray log or settings dump never leaks a live key once the URL points at a paid
    # provider. Blank default → the adapter omits the auth header entirely.
    backend_api_key: SecretStr = SecretStr("")
    backend_timeout: float = 30.0

    # --- Verifier model (cheap model used by the intent gate's borderline verify step) ---
    # Defaults to the same backend — a separate cheaper model can be configured independently.
    verifier_base_url: str = "http://localhost:11434/v1"
    verifier_model: str = "gemma3:1b"
    verifier_api_key: SecretStr = SecretStr("")
    verifier_timeout: float = 10.0

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
