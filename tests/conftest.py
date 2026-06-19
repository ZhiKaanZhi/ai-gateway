"""Shared fixtures and in-memory fakes.

The fakes exist precisely because the seams are Protocols: a test substitutes a trivial in-memory
implementation for each port, no DB or model required. They satisfy the Protocols structurally
(see ``test_ports.py``), so they are valid stand-ins anywhere the real adapters are.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from gateway.domain.models import (
    CacheEntry,
    CacheHit,
    CompletionRequest,
    CompletionResult,
    Complexity,
    Embedding,
)
from gateway.main import create_app


class FakeEmbeddingProvider:
    """Deterministic, dependency-free ``EmbeddingProvider`` for tests."""

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    async def embed(self, text: str) -> Embedding:
        return [0.0] * self._dim


class FakeCacheRepository:
    """In-memory ``CacheRepository``: stores entries and returns the last one as a hit."""

    def __init__(self) -> None:
        self.entries: list[CacheEntry] = []

    async def lookup(self, embedding: Embedding, threshold: float) -> CacheHit | None:
        if not self.entries:
            return None
        entry = self.entries[-1]
        return CacheHit(response=entry.response, model_used=entry.model_used, similarity=1.0)

    async def store(self, entry: CacheEntry) -> None:
        self.entries.append(entry)


class FakeModelBackend:
    """Echoing ``ModelBackend`` for tests."""

    @property
    def name(self) -> str:
        return "fake"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(text=request.prompt, model=self.name)


class FakeModelRouter:
    """``ModelRouter`` that always returns the one backend it was given."""

    def __init__(self, backend: FakeModelBackend) -> None:
        self._backend = backend

    def select(self, complexity: Complexity) -> FakeModelBackend:
        return self._backend


class FakeComplexityClassifier:
    """``ComplexityClassifier`` that always reports SIMPLE."""

    async def classify(self, prompt: str) -> Complexity:
        return Complexity.SIMPLE


@pytest.fixture
def embeddings() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def repository() -> FakeCacheRepository:
    return FakeCacheRepository()


@pytest.fixture
def backend() -> FakeModelBackend:
    return FakeModelBackend()


@pytest.fixture
def sample_entry() -> CacheEntry:
    return CacheEntry(
        id=uuid4(),
        prompt="hello",
        response="hi",
        model_used="fake",
        embedding=[0.0] * 384,
        created_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the app via ASGI transport.

    ``ASGITransport`` dispatches requests directly and does not run startup/shutdown events;
    once the lifespan wires real resources (the pool), tests needing them will drive it explicitly.
    """
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
