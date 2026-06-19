"""Integration test for the cache vertical against a real Postgres+pgvector.

Exercises the whole slice with real bge-small vectors: store a prompt, then confirm an identical
prompt clears the similarity gate (hit) while an unrelated one falls below it (miss) — both sides of
the threshold boundary. Skipped automatically when no DB is reachable, so the suite stays green in
environments without one (it runs in CI's pgvector service and against local ``docker compose``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from gateway.adapters.embeddings import FastembedEmbeddingProvider
from gateway.adapters.repository import PgVectorCacheRepository, create_cache_pool
from gateway.config import get_settings
from gateway.domain.models import CacheHit, CacheMiss
from gateway.services.cache_service import CacheService

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def cache_service() -> AsyncIterator[CacheService]:
    """A cache service backed by the real adapters; skips the test if the DB is unreachable."""
    settings = get_settings()
    pool = create_cache_pool(settings.conninfo)
    try:
        await pool.open(wait=True, timeout=5.0)
    except Exception as exc:  # noqa: BLE001 — any connect failure means "no DB", so skip
        await pool.close()
        pytest.skip(f"no reachable Postgres+pgvector: {exc}")
    try:
        async with pool.connection() as conn:
            await conn.execute("TRUNCATE cache_entries")
        embeddings = FastembedEmbeddingProvider(settings.embedding_model)
        repository = PgVectorCacheRepository(pool)
        yield CacheService(embeddings, repository, threshold=settings.semantic_threshold)
    finally:
        await pool.close()


async def test_miss_then_store_then_hit(cache_service: CacheService) -> None:
    settings = get_settings()
    prompt = "What is the capital of France?"

    # Cold cache → miss carrying the freshly computed embedding.
    cold = await cache_service.lookup(prompt)
    assert isinstance(cold, CacheMiss)

    await cache_service.store(prompt, "Paris", "test-model")

    # Identical prompt now clears the gate.
    hit = await cache_service.lookup(prompt)
    assert isinstance(hit, CacheHit)
    assert hit.response == "Paris"
    assert hit.model_used == "test-model"
    assert hit.similarity >= settings.semantic_threshold

    # An unrelated prompt stays below the gate → miss.
    miss = await cache_service.lookup("How do I bake sourdough bread at home?")
    assert isinstance(miss, CacheMiss)
