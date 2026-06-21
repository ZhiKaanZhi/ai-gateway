"""Cache orchestration — embed a prompt, then look it up / store it via the repository.

Depends only on the ports (:class:`EmbeddingProvider`, :class:`CacheRepository`), passed in at
construction. No raw SQL here; that stays behind the repository adapter.

A lookup miss returns a :class:`CacheMiss` carrying the embedding it just computed, so a follow-up
``store`` can reuse it instead of embedding the same prompt twice (the pipeline path, Slice 2).

Slice 3 adds ``exact_lookup``: normalize the prompt to a SHA-256 hash and do a point-query with
no embedding computation — the cheapest possible cache read.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from gateway.domain.models import CacheEntry, CacheHit, CacheMiss, Embedding
from gateway.domain.ports import CacheRepository, EmbeddingProvider


def _normalize_and_hash(prompt: str) -> str:
    """Normalize whitespace + case, then SHA-256 hex-digest.

    Normalisation is intentionally minimal: NFKC unicode, lower-cased, whitespace collapsed.
    The exact tier catches literal/near-literal repeats; paraphrases fall through to semantic.
    """
    normalized = unicodedata.normalize("NFKC", prompt).lower()
    normalized = " ".join(normalized.split())
    return hashlib.sha256(normalized.encode()).hexdigest()


class CacheService:
    """Coordinates embedding + vector lookup/store behind the cache ports."""

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        repository: CacheRepository,
        *,
        threshold: float,
    ) -> None:
        self._embeddings = embeddings
        self._repository = repository
        self._threshold = threshold

    async def exact_lookup(self, prompt: str) -> CacheHit | None:
        """Return a cached response for this exact (normalized) prompt, or ``None``.

        No embedding is computed — this is a hash point-query, the cheapest possible read.
        """
        prompt_hash = _normalize_and_hash(prompt)
        return await self._repository.exact_lookup(prompt_hash)

    async def lookup(self, prompt: str) -> CacheHit | CacheMiss:
        """Return a cached response whose similarity clears the threshold, else a miss.

        The miss carries the computed embedding so a subsequent :meth:`store` need not re-embed.
        """
        embedding = await self._embeddings.embed(prompt)
        hit = await self._repository.lookup(embedding, self._threshold)
        return hit if hit is not None else CacheMiss(embedding=embedding)

    async def store(
        self,
        prompt: str,
        response: str,
        model_used: str,
        *,
        embedding: Embedding | None = None,
    ) -> None:
        """Embed (unless an embedding is supplied) and persist a response for future lookups."""
        if embedding is None:
            embedding = await self._embeddings.embed(prompt)
        entry = CacheEntry(
            id=uuid4(),
            prompt=prompt,
            prompt_hash=_normalize_and_hash(prompt),
            response=response,
            model_used=model_used,
            embedding=embedding,
            created_at=datetime.now(UTC),
        )
        await self._repository.store(entry)
