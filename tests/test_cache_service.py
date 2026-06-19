"""Unit tests for :class:`CacheService` against the in-memory fakes — no DB, no model.

These pin the orchestration contract: lookup embeds once and gates on the threshold; a miss carries
the embedding back; and ``store`` reuses a supplied embedding instead of re-embedding.
"""

from __future__ import annotations

from gateway.domain.models import CacheHit, CacheMiss
from gateway.services.cache_service import CacheService
from tests.conftest import FakeCacheRepository, FakeEmbeddingProvider


async def test_lookup_hit_returns_cachehit() -> None:
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.99)
    service = CacheService(embeddings, repository, threshold=0.95)
    await service.store("hello", "hi", "fake")

    result = await service.lookup("hello")

    assert isinstance(result, CacheHit)
    assert result.response == "hi"
    assert result.similarity == 0.99


async def test_lookup_miss_carries_embedding() -> None:
    embeddings = FakeEmbeddingProvider()
    # Nearest neighbour sits below the gate → a miss even though an entry exists.
    repository = FakeCacheRepository(similarity=0.80)
    service = CacheService(embeddings, repository, threshold=0.95)
    await service.store("hello", "hi", "fake")

    result = await service.lookup("unrelated")

    assert isinstance(result, CacheMiss)
    assert result.embedding == [0.0] * 384


async def test_lookup_embeds_exactly_once() -> None:
    embeddings = FakeEmbeddingProvider()
    service = CacheService(embeddings, FakeCacheRepository(), threshold=0.95)

    await service.lookup("hello")

    assert embeddings.calls == 1


async def test_store_reuses_supplied_embedding() -> None:
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository()
    service = CacheService(embeddings, repository, threshold=0.95)

    await service.store("hello", "hi", "fake", embedding=[0.0] * 384)

    assert embeddings.calls == 0  # supplied embedding → no re-embed
    assert len(repository.entries) == 1
    assert repository.entries[0].prompt == "hello"


async def test_store_embeds_when_no_embedding_supplied() -> None:
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository()
    service = CacheService(embeddings, repository, threshold=0.95)

    await service.store("hello", "hi", "fake")

    assert embeddings.calls == 1
    assert len(repository.entries) == 1
