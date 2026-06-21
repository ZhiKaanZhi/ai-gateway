"""Shared fixtures and in-memory fakes.

The fakes exist precisely because the seams are Protocols: a test substitutes a trivial in-memory
implementation for each port, no DB or model required. They satisfy the Protocols structurally
(see ``test_ports.py``), so they are valid stand-ins anywhere the real adapters are.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
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


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """On Windows, psycopg async needs the selector loop, not the default Proactor (skill gotcha 9).

    pytest-asyncio drives asyncio directly (no uvicorn), so the integration test would otherwise
    fail on the user's Windows box. Honoured by pytest-asyncio for the loops it creates.
    """
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


class FakeEmbeddingProvider:
    """Deterministic, dependency-free ``EmbeddingProvider`` for tests; counts its calls."""

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim
        self.calls = 0

    async def embed(self, text: str) -> Embedding:
        self.calls += 1
        return [0.0] * self._dim


class FakeCacheRepository:
    """In-memory ``CacheRepository``: stores entries, returns the last one if it clears the gate.

    The fake reports a fixed ``similarity`` for the most recent entry and honours ``threshold`` so
    service-level tests can drive both the hit and the miss path.
    """

    def __init__(self, similarity: float = 1.0) -> None:
        self.entries: list[CacheEntry] = []
        self._similarity = similarity

    async def lookup(self, embedding: Embedding, threshold: float) -> CacheHit | None:
        if not self.entries or self._similarity < threshold:
            return None
        entry = self.entries[-1]
        return CacheHit(
            response=entry.response, model_used=entry.model_used, similarity=self._similarity
        )

    async def store(self, entry: CacheEntry) -> None:
        self.entries.append(entry)


class FakeModelBackend:
    """Echoing ``ModelBackend`` for tests; counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "fake"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
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


@pytest.fixture
def app() -> FastAPI:
    """A fresh FastAPI app instance.

    Tests that need ``dependency_overrides`` can mutate this fixture's app before passing it to
    ``AsyncClient`` — the ASGITransport client skips the lifespan, so fakes never need to open a
    real pool or httpx client.
    """
    return create_app()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the app via ASGI transport.

    ``ASGITransport`` dispatches requests directly and does not run startup/shutdown events;
    once the lifespan wires real resources (the pool), tests needing them will drive it explicitly.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
