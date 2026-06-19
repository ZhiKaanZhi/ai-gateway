"""Domain models — the typed vocabulary that crosses the ports.

These are plain data: Pydantic models and enums, no behavior. Keeping them free of loose
``dict``s is what lets the seams in :mod:`gateway.domain.ports` stay honestly typed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

# A dense embedding vector. 384-dim for all-MiniLM-L6-v2 / bge-small-en-v1.5 (see CLAUDE.md),
# but the dimension is enforced at the storage seam, not in the type.
type Embedding = list[float]


class Complexity(StrEnum):
    """How hard a prompt is to serve — the signal the router selects a backend on."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class CompletionRequest(BaseModel):
    """A single inbound request to be served by a model backend."""

    prompt: str
    model: str | None = None


class CompletionResult(BaseModel):
    """What a model backend returns for a :class:`CompletionRequest`."""

    text: str
    model: str


class CacheEntry(BaseModel):
    """A stored prompt/response pair plus its embedding — one row in the cache."""

    id: UUID
    prompt: str
    response: str
    model_used: str
    embedding: Embedding
    created_at: datetime


class CacheHit(BaseModel):
    """A cache lookup that cleared its similarity gate."""

    response: str
    model_used: str
    similarity: float = Field(ge=0.0, le=1.0)


@dataclass(frozen=True, slots=True)
class CacheMiss:
    """A cache lookup that found nothing close enough — carries the embedding it already computed.

    Internal to the service layer (never crosses the API boundary): handing the vector back lets a
    follow-up ``store`` persist without re-embedding the same prompt. A plain frozen dataclass, not
    a Pydantic model, so the 384-float vector isn't re-validated on every miss.
    """

    embedding: Embedding
