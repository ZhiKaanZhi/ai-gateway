"""Ports — the swap seams of the gateway, expressed as ``Protocol``s.

There is deliberately **one Protocol per real seam**, not one per class (that would be the C#
tell CLAUDE.md warns about). Concrete implementations live in :mod:`gateway.adapters` (I/O) and
:mod:`gateway.services` (orchestration); tests substitute in-memory fakes. Structural typing means
an implementation never has to import or inherit these — it just has to fit.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gateway.domain.models import (
    CacheEntry,
    CacheHit,
    CompletionRequest,
    CompletionResult,
    Complexity,
    Embedding,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into a dense vector. Default adapter: fastembed (local ONNX)."""

    async def embed(self, text: str) -> Embedding: ...


@runtime_checkable
class CacheRepository(Protocol):
    """Vector-backed cache store. Default adapter: psycopg 3 + pgvector.

    The similarity gate lives at the call site (the service passes ``threshold``); the repository
    only reports the nearest neighbour that clears it.
    """

    async def lookup(self, embedding: Embedding, threshold: float) -> CacheHit | None: ...

    async def store(self, entry: CacheEntry) -> None: ...


@runtime_checkable
class ModelBackend(Protocol):
    """A single servable model (a provider/model pair)."""

    @property
    def name(self) -> str: ...

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


@runtime_checkable
class ModelRouter(Protocol):
    """Picks which backend serves a request, given its assessed complexity."""

    def select(self, complexity: Complexity) -> ModelBackend: ...


@runtime_checkable
class ComplexityClassifier(Protocol):
    """Assesses how hard a prompt is, so the router can serve it cost-aware."""

    async def classify(self, prompt: str) -> Complexity: ...
