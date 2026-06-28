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
    ExtractedIntent,
    IntentCandidate,
    IntentEntry,
    ToolCall,
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

    async def exact_lookup(self, prompt_hash: str) -> CacheHit | None:
        for entry in reversed(self.entries):
            if entry.prompt_hash == prompt_hash:
                return CacheHit(
                    response=entry.response, model_used=entry.model_used, similarity=1.0
                )
        return None

    async def store(self, entry: CacheEntry) -> None:
        self.entries.append(entry)


class FakeModelBackend:
    """Echoing ``ModelBackend`` for tests; counts its calls.

    Pass ``tool_call`` to make the backend emit an *action* reply (every ``complete`` returns it),
    so action-seam tests can drive the never-cache path (D45).
    """

    def __init__(self, tool_call: ToolCall | None = None) -> None:
        self.calls = 0
        self._tool_call = tool_call
        self.last_request: CompletionRequest | None = None

    @property
    def name(self) -> str:
        return "fake"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
        self.last_request = request  # lets tests assert what the gateway forwarded (tools/context)
        return CompletionResult(text=request.prompt, model=self.name, tool_call=self._tool_call)


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


class FakeIntentExtractor:
    """``IntentExtractor`` that strips nothing by default (paramless prompts)."""

    def __init__(self, canonical: str | None = None, parameters: list[str] | None = None) -> None:
        self._canonical = canonical
        self._parameters = parameters or []

    def extract(self, prompt: str) -> ExtractedIntent:
        return ExtractedIntent(
            canonical=self._canonical if self._canonical is not None else prompt,
            parameters=self._parameters,
        )


class FakeIntentRepository:
    """In-memory ``IntentRepository``."""

    def __init__(self, candidates: list[IntentCandidate] | None = None) -> None:
        self.entries: list[IntentEntry] = []
        self._candidates = candidates or []

    async def search(
        self, embedding: Embedding, threshold: float, limit: int = 5
    ) -> list[IntentCandidate]:
        return self._candidates[:limit]

    async def store(self, entry: IntentEntry) -> None:
        self.entries.append(entry)

    async def prune_older_than(self, max_age_seconds: float) -> int:
        now = datetime.now(UTC)
        before = len(self.entries)
        self.entries = [
            e for e in self.entries if (now - e.created_at).total_seconds() <= max_age_seconds
        ]
        return before - len(self.entries)


class FakeVerifier:
    """``Verifier`` that returns a fixed score; counts its calls so tests can assert the gate
    only consults the model on the value-mismatch path (D32)."""

    def __init__(self, score: float = 1.0) -> None:
        self._score = score
        self.calls = 0

    async def verify(self, question: str, candidate_answer: str) -> float:
        self.calls += 1
        return self._score


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
        prompt_hash="abc123",
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
