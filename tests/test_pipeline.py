"""Unit tests for RequestPipeline against the in-memory fakes — no DB, no model.

Pins the orchestration contract: a cache hit returns without calling the backend; a cache miss calls
the backend exactly once, stores once, and reuses the miss's embedding (prompt embedded once total).
"""

from __future__ import annotations

from gateway.domain.models import CompletionRequest, Complexity, ServedCompletion
from gateway.services.cache_service import CacheService
from gateway.services.classifier import HeuristicClassifier
from gateway.services.pipeline import RequestPipeline
from gateway.services.router import CostAwareRouter
from tests.conftest import FakeCacheRepository, FakeEmbeddingProvider, FakeModelBackend


def _make_pipeline(
    embeddings: FakeEmbeddingProvider,
    repository: FakeCacheRepository,
    backend: FakeModelBackend,
) -> RequestPipeline:
    cache = CacheService(embeddings, repository, threshold=0.95)
    classifier = HeuristicClassifier()
    router = CostAwareRouter({c: backend for c in Complexity})
    return RequestPipeline(cache, classifier, router)


async def test_cache_hit_does_not_call_backend() -> None:
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.99)
    backend = FakeModelBackend()
    pipeline = _make_pipeline(embeddings, repository, backend)
    cache = CacheService(embeddings, repository, threshold=0.95)

    # Pre-populate the cache so a lookup will hit.
    await cache.store("What is Python?", "A programming language.", "fake")
    embeddings.calls = 0  # reset counter after the store's embed call

    request = CompletionRequest(prompt="What is Python?")
    result = await pipeline.process(request)

    assert isinstance(result, ServedCompletion)
    assert result.cached is True
    assert result.text == "A programming language."
    assert result.model == "fake"
    assert result.similarity is not None
    assert backend.calls == 0  # never reached the model


async def test_cache_miss_calls_backend_once_and_stores() -> None:
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)  # always miss
    backend = FakeModelBackend()
    pipeline = _make_pipeline(embeddings, repository, backend)

    request = CompletionRequest(prompt="Hello world")
    result = await pipeline.process(request)

    assert isinstance(result, ServedCompletion)
    assert result.cached is False
    assert result.similarity is None
    assert backend.calls == 1
    assert len(repository.entries) == 1
    assert repository.entries[0].prompt == "Hello world"


async def test_miss_embeds_prompt_exactly_once() -> None:
    """lookup embeds once; store reuses the miss's embedding — so total embed calls == 1."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)  # always miss
    backend = FakeModelBackend()
    pipeline = _make_pipeline(embeddings, repository, backend)

    await pipeline.process(CompletionRequest(prompt="embed me once"))

    assert embeddings.calls == 1
