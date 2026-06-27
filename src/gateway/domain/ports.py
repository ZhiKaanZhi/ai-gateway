"""Ports — the swap seams of the gateway, expressed as ``Protocol``s.

There is deliberately **one Protocol per real seam**, not one per class (that would be the C#
tell CLAUDE.md warns about). Concrete implementations live in :mod:`gateway.adapters` (I/O) and
:mod:`gateway.services` (orchestration); tests substitute in-memory fakes. Structural typing means
an implementation never has to import or inherit these — it just has to fit.

Slice 3 adds three new seams for the intent tier (D29): ``IntentExtractor``, ``IntentRepository``,
and ``Verifier``. Five ports → eight.
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
    ExtractedIntent,
    IntentCandidate,
    IntentEntry,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into a dense vector. Default adapter: fastembed (local ONNX)."""

    async def embed(self, text: str) -> Embedding: ...


@runtime_checkable
class CacheRepository(Protocol):
    """Vector-backed semantic cache store. Default adapter: psycopg 3 + pgvector.

    The similarity gate lives at the call site (the service passes ``threshold``); the repository
    only reports the nearest neighbour that clears it.
    """

    async def lookup(self, embedding: Embedding, threshold: float) -> CacheHit | None: ...

    async def exact_lookup(self, prompt_hash: str) -> CacheHit | None: ...

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


# ---------------------------------------------------------------------------
# Intent tier ports (D29) — three new seams
# ---------------------------------------------------------------------------


@runtime_checkable
class IntentExtractor(Protocol):
    """Strips parameters from a prompt to produce the canonical intent form.

    Returns :class:`ExtractedIntent` containing both the canonical (stripped) prompt and
    the bare parameter values, which are persisted in ``intent_entries`` (D27) so the gate
    can read them back for the binding check (D25).
    """

    def extract(self, prompt: str) -> ExtractedIntent: ...


@runtime_checkable
class IntentRepository(Protocol):
    """Vector store for the intent tier. Default adapter: psycopg 3 + pgvector (D27).

    Searches the *stripped-prompt* embedding space, not the full-prompt space — that is the
    mechanical difference from ``CacheRepository`` that makes #1111 and #2222 collapse to the
    same candidate.
    """

    async def search(
        self, embedding: Embedding, threshold: float, limit: int = 5
    ) -> list[IntentCandidate]: ...

    async def store(self, entry: IntentEntry) -> None: ...

    async def prune_older_than(self, max_age_seconds: float) -> int:
        """Delete intent rows older than ``max_age_seconds``; return the number deleted.

        Age-only TTL cleanup (D38): the background prune timer calls this on a fixed interval and
        logs the returned count as proof it ran. ``max_age_seconds`` matches the gate's staleness
        vocabulary — the same age the gate refuses to serve past (D39).
        """
        ...


@runtime_checkable
class Verifier(Protocol):
    """Judges whether a cached answer is correct for a new question.

    Returns a score in ``[0, 1]``; the **gate** owns the pass cutoff (D26) so the verify band
    is calibrated from the eval set (D30) and not hidden inside the adapter. A rules engine
    could implement this seam instead of a model.
    """

    async def verify(self, question: str, candidate_answer: str) -> float: ...
