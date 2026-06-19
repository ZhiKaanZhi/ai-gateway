"""Cache orchestration — embed a prompt, then look it up / store it via the repository.

Depends only on the ports (:class:`EmbeddingProvider`, :class:`CacheRepository`), passed in at
construction. No raw SQL here; that stays behind the repository adapter.
"""

from __future__ import annotations

from gateway.domain.models import CacheHit
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

    async def lookup(self, prompt: str) -> CacheHit | None:
        """Return a cached response whose similarity clears the threshold, else ``None``."""
        raise NotImplementedError

    async def store(self, prompt: str, response: str, model_used: str) -> None:
        """Embed and persist a freshly served response for future lookups."""
        raise NotImplementedError
