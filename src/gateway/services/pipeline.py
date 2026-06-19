"""Request pipeline — the orchestration that ties the seams together.

For each request: check the cache, and on a miss classify, route to a backend, serve, then store.
Composed from the ports + the cache service, all injected at construction. The intent-caching tier
(the showpiece) slots in here in a later slice. Stub only in the harness.
"""

from __future__ import annotations

from gateway.domain.models import CompletionRequest, CompletionResult
from gateway.domain.ports import ComplexityClassifier, ModelRouter
from gateway.services.cache_service import CacheService


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

    async def process(self, request: CompletionRequest) -> CompletionResult:
        """Run the request through the pipeline and return the served completion."""
        raise NotImplementedError
