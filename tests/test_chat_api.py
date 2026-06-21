"""API-level tests for POST /v1/chat — offline, no DB, no model.

Uses dependency_overrides to inject a fake-backed pipeline, so the lifespan never runs. Covers the
hit/miss JSON shapes and that BackendError surfaces as the right HTTP status codes (502/504).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gateway.api.routes import get_pipeline
from gateway.domain.errors import BackendError
from gateway.domain.models import CompletionRequest, Complexity, ServedCompletion
from gateway.services.cache_service import CacheService
from gateway.services.classifier import HeuristicClassifier
from gateway.services.pipeline import RequestPipeline
from gateway.services.router import CostAwareRouter
from tests.conftest import FakeCacheRepository, FakeEmbeddingProvider, FakeModelBackend


def _real_pipeline(
    embeddings: FakeEmbeddingProvider,
    repository: FakeCacheRepository,
    backend: FakeModelBackend,
) -> RequestPipeline:
    cache = CacheService(embeddings, repository, threshold=0.95)
    classifier = HeuristicClassifier()
    router = CostAwareRouter({c: backend for c in Complexity})
    return RequestPipeline(cache, classifier, router)


@pytest_asyncio.fixture
async def miss_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client wired to a pipeline with an empty cache — every request is a miss."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)
    backend = FakeModelBackend()
    pipeline = _real_pipeline(embeddings, repository, backend)
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def hit_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client wired to a pipeline with a pre-seeded cache — every request is a hit."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.99)
    backend = FakeModelBackend()
    # Pre-populate so the lookup hits.
    cache = CacheService(embeddings, repository, threshold=0.95)
    await cache.store("What is Python?", "A programming language.", "fake")

    pipeline = _real_pipeline(embeddings, repository, backend)
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def test_miss_returns_200_with_correct_json(miss_client: AsyncClient) -> None:
    response = await miss_client.post("/v1/chat", json={"prompt": "Hello"})
    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is False
    assert data["response"] == "Hello"  # FakeModelBackend echoes the prompt
    assert data["model"] == "fake"
    assert data["similarity"] is None


async def test_hit_returns_200_with_cached_true(hit_client: AsyncClient) -> None:
    response = await hit_client.post("/v1/chat", json={"prompt": "What is Python?"})
    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is True
    assert data["response"] == "A programming language."
    assert data["similarity"] is not None


class _ErrorPipeline:
    """Fake pipeline that always raises BackendError with the given is_timeout."""

    def __init__(self, *, is_timeout: bool) -> None:
        self._is_timeout = is_timeout

    async def process(self, request: CompletionRequest) -> ServedCompletion:
        raise BackendError("simulated failure", is_timeout=self._is_timeout)


@pytest.mark.parametrize(
    ("is_timeout", "expected_status"),
    [(False, 502), (True, 504)],
)
async def test_backend_error_maps_to_correct_http_status(
    app: FastAPI,
    is_timeout: bool,
    expected_status: int,
) -> None:
    error_pipeline = _ErrorPipeline(is_timeout=is_timeout)
    app.dependency_overrides[get_pipeline] = lambda: error_pipeline
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post("/v1/chat", json={"prompt": "fail"})
    app.dependency_overrides.clear()

    assert response.status_code == expected_status
    assert "detail" in response.json()
