"""The fakes must satisfy the ports structurally, or they are not valid stand-ins.

These ``isinstance`` checks work because the ports are ``runtime_checkable`` Protocols; they guard
against a fake's signature drifting away from its seam.
"""

from __future__ import annotations

from gateway.domain.ports import (
    CacheRepository,
    ComplexityClassifier,
    EmbeddingProvider,
    IntentExtractor,
    IntentRepository,
    ModelBackend,
    ModelRouter,
    Verifier,
)
from tests.conftest import (
    FakeCacheRepository,
    FakeComplexityClassifier,
    FakeEmbeddingProvider,
    FakeIntentExtractor,
    FakeIntentRepository,
    FakeModelBackend,
    FakeModelRouter,
    FakeVerifier,
)


def test_fakes_implement_ports() -> None:
    assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)
    assert isinstance(FakeCacheRepository(), CacheRepository)
    backend = FakeModelBackend()
    assert isinstance(backend, ModelBackend)
    assert isinstance(FakeModelRouter(backend), ModelRouter)
    assert isinstance(FakeComplexityClassifier(), ComplexityClassifier)
    # Slice 3: three new ports
    assert isinstance(FakeIntentExtractor(), IntentExtractor)
    assert isinstance(FakeIntentRepository(), IntentRepository)
    assert isinstance(FakeVerifier(), Verifier)
