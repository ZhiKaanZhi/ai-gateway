"""The fakes must satisfy the ports structurally, or they are not valid stand-ins.

These ``isinstance`` checks work because the ports are ``runtime_checkable`` Protocols; they guard
against a fake's signature drifting away from its seam.
"""

from __future__ import annotations

from gateway.domain.ports import (
    CacheRepository,
    ComplexityClassifier,
    EmbeddingProvider,
    ModelBackend,
    ModelRouter,
)
from tests.conftest import (
    FakeCacheRepository,
    FakeComplexityClassifier,
    FakeEmbeddingProvider,
    FakeModelBackend,
    FakeModelRouter,
)


def test_fakes_implement_ports() -> None:
    assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)
    assert isinstance(FakeCacheRepository(), CacheRepository)
    backend = FakeModelBackend()
    assert isinstance(backend, ModelBackend)
    assert isinstance(FakeModelRouter(backend), ModelRouter)
    assert isinstance(FakeComplexityClassifier(), ComplexityClassifier)
