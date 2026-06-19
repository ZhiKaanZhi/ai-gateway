"""Cache orchestration — embed a prompt, then look it up / store it via the repository.

Depends only on the ports (:class:`EmbeddingProvider`, :class:`CacheRepository`), passed in at
construction. No raw SQL here; that stays behind the repository adapter.

A lookup miss returns a :class:`CacheMiss` carrying the embedding it just computed, so a follow-up
``store`` can reuse it instead of embedding the same prompt twice (the pipeline path, Slice 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gateway.domain.models import CacheEntry, CacheHit, CacheMiss, Embedding
from gateway.domain.ports import CacheRepository, EmbeddingProvider


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
            response=response,
            model_used=model_used,
            embedding=embedding,
            created_at=datetime.now(UTC),
        )
        await self._repository.store(entry)
