"""Request pipeline — the orchestration that ties the seams together.

For each request: check the cache, and on a miss classify, route to a backend, serve, then store.
Composed from the ports + the cache service, all injected at construction. The intent-caching tier
(the showpiece) slots in here in a later slice.
"""

from __future__ import annotations

import logging

from gateway.domain.models import CacheHit, CompletionRequest, ServedCompletion
from gateway.domain.ports import ComplexityClassifier, ModelRouter
from gateway.services.cache_service import CacheService

_log = logging.getLogger(__name__)


class RequestPipeline:
    """Serves a request through cache -> classify -> route -> backend -> store."""

    def __init__(
        self,
        cache: CacheService,
        classifier: ComplexityClassifier,
        router: ModelRouter,
    ) -> None:
        self._cache = cache
        self._classifier = classifier
        self._router = router

    async def process(self, request: CompletionRequest) -> ServedCompletion:
        """Serve via cache → (on miss) classify → route → backend → best-effort store."""
        result = await self._cache.lookup(request.prompt)  # CacheHit | CacheMiss
        if isinstance(result, CacheHit):
            return ServedCompletion(
                text=result.response,
                model=result.model_used,
                cached=True,
                similarity=result.similarity,
            )
        # CacheMiss — carries the embedding already computed for this prompt; reuse it in store so
        # the prompt is never embedded twice on the hot path.
        complexity = await self._classifier.classify(request.prompt)
        backend = self._router.select(complexity)
        completion = await backend.complete(request)
        try:
            await self._cache.store(
                request.prompt,
                completion.text,
                completion.model,
                embedding=result.embedding,
            )
        except Exception:  # noqa: BLE001 — best-effort write; caller still gets their answer
            _log.warning(
                "cache store failed after generation; returning result uncached", exc_info=True
            )
        return ServedCompletion(
            text=completion.text,
            model=completion.model,
            cached=False,
            similarity=None,
        )
