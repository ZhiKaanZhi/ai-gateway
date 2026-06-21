"""API contract — the Pydantic models that define request/response shapes over HTTP.

Kept separate from :mod:`gateway.domain.models` on purpose: the wire contract and the internal
domain vocabulary are allowed to evolve independently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from gateway.domain.models import CacheTier


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: Literal["ok"] = "ok"


class ChatRequest(BaseModel):
    """A client request to serve a prompt through the gateway."""

    prompt: str
    model: str | None = None


class ChatResponse(BaseModel):
    """The gateway's answer, annotated with how it was served.

    ``tier`` records which cache tier answered (exact/semantic/intent/live).
    ``similarity`` is the cosine distance input for semantic/intent hits.
    ``confidence`` is the gate's correctness verdict for intent hits — see GLOSSARY.md and D26.
    """

    response: str
    model: str
    cached: bool
    tier: CacheTier
    similarity: float | None = None
    confidence: float | None = None


class CacheLookupRequest(BaseModel):
    """Ask the cache whether a semantically similar prompt has been answered before."""

    prompt: str


class CacheLookupResponse(BaseModel):
    """Result of a cache lookup. On a miss every detail field is ``None``."""

    hit: bool
    response: str | None = None
    model_used: str | None = None
    similarity: float | None = None


class CacheStoreRequest(BaseModel):
    """Persist a prompt/response pair (with the model that produced it) for future lookups."""

    prompt: str
    response: str
    model_used: str


class CacheStoreResponse(BaseModel):
    """Acknowledgement that an entry was stored."""

    stored: bool = True
