"""Unit tests for RequestPipeline against the in-memory fakes — no DB, no model.

Covers all three tiers (exact, semantic, intent) plus the live path and admission routing.
"""

from __future__ import annotations

from gateway.domain.models import (
    CacheTier,
    CompletionRequest,
    Complexity,
    IntentCandidate,
    ServedCompletion,
)
from gateway.services.cache_service import CacheService
from gateway.services.classifier import HeuristicClassifier
from gateway.services.intent_gate import IntentGate
from gateway.services.pipeline import RequestPipeline
from gateway.services.router import CostAwareRouter
from tests.conftest import (
    FakeCacheRepository,
    FakeEmbeddingProvider,
    FakeIntentExtractor,
    FakeIntentRepository,
    FakeModelBackend,
    FakeVerifier,
)


def _make_pipeline(
    embeddings: FakeEmbeddingProvider,
    repository: FakeCacheRepository,
    backend: FakeModelBackend,
    *,
    extractor: FakeIntentExtractor | None = None,
    intent_repo: FakeIntentRepository | None = None,
    verifier_score: float = 0.0,
    sem_similarity: float = 0.0,
) -> RequestPipeline:
    cache = CacheService(embeddings, repository, threshold=0.95)
    classifier = HeuristicClassifier()
    router = CostAwareRouter({c: backend for c in Complexity})
    verifier = FakeVerifier(score=verifier_score)
    gate = IntentGate(
        verifier,
        margin_min=0.05,
        staleness_max_seconds=86400.0,
        verify_band_lo=0.70,
        verify_band_hi=0.85,
        verify_pass_threshold=0.80,
    )
    return RequestPipeline(
        cache,
        classifier,
        router,
        embeddings,
        extractor or FakeIntentExtractor(),
        intent_repo or FakeIntentRepository(),
        gate,
        intent_match_threshold=0.90,
    )


# ---------------------------------------------------------------------------
# Exact tier
# ---------------------------------------------------------------------------


async def test_exact_hit_serves_without_embedding() -> None:
    """Exact tier: a stored entry matching the hash returns without computing an embedding."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)  # no semantic hits
    backend = FakeModelBackend()
    pipeline = _make_pipeline(embeddings, repository, backend)
    cache = CacheService(embeddings, repository, threshold=0.95)

    await cache.store("What is Python?", "A programming language.", "fake")
    embeddings.calls = 0  # reset after the store's embed call

    result = await pipeline.process(CompletionRequest(prompt="What is Python?"))

    assert isinstance(result, ServedCompletion)
    assert result.cached is True
    assert result.tier == CacheTier.EXACT
    assert result.similarity == 1.0
    assert result.text == "A programming language."
    assert embeddings.calls == 0  # no embedding for exact lookup
    assert backend.calls == 0


# ---------------------------------------------------------------------------
# Semantic tier
# ---------------------------------------------------------------------------


async def test_semantic_hit_does_not_call_backend() -> None:
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.99)
    backend = FakeModelBackend()
    pipeline = _make_pipeline(embeddings, repository, backend, sem_similarity=0.99)
    cache = CacheService(embeddings, repository, threshold=0.95)

    await cache.store("What is Python?", "A programming language.", "fake")
    embeddings.calls = 0

    result = await pipeline.process(CompletionRequest(prompt="What is Python paraphrase?"))

    assert isinstance(result, ServedCompletion)
    assert result.cached is True
    assert result.tier == CacheTier.SEMANTIC
    assert result.similarity is not None
    assert backend.calls == 0


# ---------------------------------------------------------------------------
# Intent tier
# ---------------------------------------------------------------------------


def _make_candidate(
    response: str = "Generic return policy: 30 days.",
    parameters: list[str] | None = None,
    similarity: float = 0.95,
    age_seconds: float = 100.0,
) -> IntentCandidate:
    return IntentCandidate(
        response=response,
        model_used="fake",
        similarity=similarity,
        age_seconds=age_seconds,
        parameters=parameters or [],
    )


async def test_intent_serve_sets_tier_and_confidence() -> None:
    """A paramless cached answer clears the gate and returns tier=INTENT."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)  # no semantic hit
    backend = FakeModelBackend()

    candidate = _make_candidate(
        response="Generic return policy: 30 days.",
        parameters=[],  # paramless answer → not bound
        similarity=0.97,
        age_seconds=100.0,
    )
    # Two candidates so margin is computable: top1=0.97, top2=0.80 → margin=0.17 > 0.05
    candidate2 = _make_candidate(similarity=0.80)
    intent_repo = FakeIntentRepository(candidates=[candidate, candidate2])
    extractor = FakeIntentExtractor(canonical="How do I {ACTION} an order?", parameters=[])
    # verifier_score=0.95: the candidate (sim=0.97, age=100s, margin=0.17) lands in the verify
    # band; a high verifier score is needed for the gate to pass (D26).
    pipeline = _make_pipeline(
        embeddings,
        repository,
        backend,
        extractor=extractor,
        intent_repo=intent_repo,
        verifier_score=0.95,
    )

    result = await pipeline.process(CompletionRequest(prompt="How do I return an order?"))

    assert isinstance(result, ServedCompletion)
    assert result.cached is True
    assert result.tier == CacheTier.INTENT
    assert result.confidence is not None
    assert backend.calls == 0


async def test_intent_bound_answer_falls_through_to_live() -> None:
    """A bound answer (response contains the stored parameter) is refused → LIVE path."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)
    backend = FakeModelBackend()

    # Answer contains the parameter "1111" — it is bound to that order
    candidate = _make_candidate(
        response="Order 1111 ships on Thursday.",
        parameters=["1111"],
        similarity=0.97,
        age_seconds=100.0,
    )
    candidate2 = _make_candidate(similarity=0.80)
    intent_repo = FakeIntentRepository(candidates=[candidate, candidate2])
    extractor = FakeIntentExtractor(
        canonical="Where is order {ID}?", parameters=["2222"]
    )
    pipeline = _make_pipeline(
        embeddings, repository, backend, extractor=extractor, intent_repo=intent_repo
    )

    result = await pipeline.process(CompletionRequest(prompt="Where is order 2222?"))

    assert result.tier == CacheTier.LIVE
    assert result.cached is False
    assert backend.calls == 1


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------


async def test_cache_miss_calls_backend_once_and_stores() -> None:
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)
    backend = FakeModelBackend()
    pipeline = _make_pipeline(embeddings, repository, backend)

    result = await pipeline.process(CompletionRequest(prompt="Hello world"))

    assert isinstance(result, ServedCompletion)
    assert result.cached is False
    assert result.tier == CacheTier.LIVE
    assert backend.calls == 1
    assert len(repository.entries) == 1
    assert repository.entries[0].prompt == "Hello world"


async def test_miss_embeds_prompt_exactly_once() -> None:
    """lookup embeds the full prompt once; store reuses the miss's embedding — total == 1
    for the full-prompt embedding. The stripped embedding is an additional call."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)
    backend = FakeModelBackend()
    # Paramless extractor: stripped == prompt, so stripped embedding is 1 call
    pipeline = _make_pipeline(embeddings, repository, backend)

    await pipeline.process(CompletionRequest(prompt="embed me once"))

    # semantic lookup (1) + stripped embed for intent tier (1) = 2 total
    # The semantic store reuses the miss embedding, so no extra embed for the store.
    assert embeddings.calls == 2


# ---------------------------------------------------------------------------
# Admission routing (D28)
# ---------------------------------------------------------------------------


async def test_parameterized_prompt_goes_to_intent_store_not_semantic() -> None:
    """Parameterized prompt → intent store only; cache_entries stays empty."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)
    backend = FakeModelBackend()
    intent_repo = FakeIntentRepository()
    extractor = FakeIntentExtractor(canonical="Where is order {ID}?", parameters=["1234"])
    pipeline = _make_pipeline(
        embeddings, repository, backend, extractor=extractor, intent_repo=intent_repo
    )

    await pipeline.process(CompletionRequest(prompt="Where is order 1234?"))

    assert len(repository.entries) == 0  # semantic store untouched
    assert len(intent_repo.entries) == 1
    assert intent_repo.entries[0].parameters == ["1234"]


async def test_paramless_prompt_goes_to_semantic_store() -> None:
    """Paramless prompt → semantic store only; intent store stays empty."""
    embeddings = FakeEmbeddingProvider()
    repository = FakeCacheRepository(similarity=0.0)
    backend = FakeModelBackend()
    intent_repo = FakeIntentRepository()
    extractor = FakeIntentExtractor(canonical="What is Python?", parameters=[])
    pipeline = _make_pipeline(
        embeddings, repository, backend, extractor=extractor, intent_repo=intent_repo
    )

    await pipeline.process(CompletionRequest(prompt="What is Python?"))

    assert len(repository.entries) == 1
    assert len(intent_repo.entries) == 0
