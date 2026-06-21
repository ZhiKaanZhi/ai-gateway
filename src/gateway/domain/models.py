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


class CacheTier(StrEnum):
    """Which tier of the three-tier cache served the request (D23)."""

    EXACT = "exact"
    SEMANTIC = "semantic"
    INTENT = "intent"
    LIVE = "live"


class CompletionRequest(BaseModel):
    """A single inbound request to be served by a model backend."""

    prompt: str
    model: str | None = None


class CompletionResult(BaseModel):
    """What a model backend returns for a :class:`CompletionRequest`."""

    text: str
    model: str


class CacheEntry(BaseModel):
    """A stored prompt/response pair plus its embedding — one row in the semantic cache."""

    id: UUID
    prompt: str
    prompt_hash: str
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


# ---------------------------------------------------------------------------
# Intent tier models (D24, D27, D29)
# ---------------------------------------------------------------------------


class ExtractedIntent(BaseModel):
    """The result of stripping parameters from a prompt.

    ``canonical`` is the parameter-free form used as the intent-match key;
    ``parameters`` are the bare values that were stripped out, persisted alongside
    the cached answer so the gate's binding check (D25) can read them back.
    """

    canonical: str
    parameters: list[str]


class IntentEntry(BaseModel):
    """One row in the ``intent_entries`` table (D27)."""

    id: UUID
    canonical_prompt: str
    response: str
    model_used: str
    embedding: Embedding
    parameters: list[str]
    created_at: datetime


class IntentCandidate(BaseModel):
    """A ranked candidate returned by :class:`IntentRepository.search`.

    ``parameters`` comes from the stored column — the values that were in the
    prompt when the answer was originally generated, needed by the gate's
    binding check (D25).
    """

    response: str
    model_used: str
    similarity: float = Field(ge=0.0, le=1.0)
    age_seconds: float = Field(ge=0.0)
    parameters: list[str]


class ServedCompletion(BaseModel):
    """What the pipeline returns: a completion plus how it was served.

    ``tier`` records which cache tier (or the live backend) answered.
    ``similarity`` is the cosine distance input (semantic / intent match).
    ``confidence`` is the gate's correctness verdict for intent hits — a different
    thing from similarity; see GLOSSARY.md and D26.
    """

    text: str
    model: str
    cached: bool
    tier: CacheTier
    similarity: float | None = None
    confidence: float | None = None
