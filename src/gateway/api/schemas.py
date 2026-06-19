"""API contract — the Pydantic models that define request/response shapes over HTTP.

Kept separate from :mod:`gateway.domain.models` on purpose: the wire contract and the internal
domain vocabulary are allowed to evolve independently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: Literal["ok"] = "ok"


class ChatRequest(BaseModel):
    """A client request to serve a prompt through the gateway."""

    prompt: str
    model: str | None = None


class ChatResponse(BaseModel):
    """The gateway's answer, annotated with how it was served."""

    response: str
    model: str
    cached: bool
    similarity: float | None = None
