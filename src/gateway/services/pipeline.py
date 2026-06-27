"""Request pipeline — the orchestration that ties the seams together.

Three-tier cache (exact → semantic → intent), first-hit-wins (D23). Intent hits pass through the
confidence gate; only a gate-pass serves. Any non-hit falls through to classify → route → backend
→ admission-routed store.

Admission routing (D28): paramless answer → semantic store; parameterized → intent store only.
The raw parameterized prompt never enters ``cache_entries``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from gateway.domain.models import (
    CacheHit,
    CacheTier,
    CompletionRequest,
    IntentEntry,
    ServedCompletion,
)
from gateway.domain.ports import (
    ComplexityClassifier,
    EmbeddingProvider,
    IntentExtractor,
    IntentRepository,
    ModelRouter,
)
from gateway.services.cache_service import CacheService
from gateway.services.intent_gate import IntentGate

_log = logging.getLogger(__name__)


class RequestPipeline:
    """Serves a request: exact → semantic → intent cache → (miss) classify → route → store."""

    def __init__(
        self,
        cache: CacheService,
        classifier: ComplexityClassifier,
        router: ModelRouter,
        embeddings: EmbeddingProvider,
        extractor: IntentExtractor,
        intent_repo: IntentRepository,
        intent_gate: IntentGate,
        intent_match_threshold: float,
    ) -> None:
        self._cache = cache
        self._classifier = classifier
        self._router = router
        self._embeddings = embeddings
        self._extractor = extractor
        self._intent_repo = intent_repo
        self._intent_gate = intent_gate
        self._intent_match_threshold = intent_match_threshold

    async def process(self, request: CompletionRequest) -> ServedCompletion:
        """Serve via exact → semantic → intent → (on miss) classify → route → backend → store."""

        # --- Tier 1: exact ---
        exact_hit = await self._cache.exact_lookup(request.prompt)
        if exact_hit is not None:
            return ServedCompletion(
                text=exact_hit.response,
                model=exact_hit.model_used,
                cached=True,
                tier=CacheTier.EXACT,
                similarity=1.0,
            )

        # --- Tier 2: semantic ---
        sem_result = await self._cache.lookup(request.prompt)  # CacheHit | CacheMiss
        if isinstance(sem_result, CacheHit):
            return ServedCompletion(
                text=sem_result.response,
                model=sem_result.model_used,
                cached=True,
                tier=CacheTier.SEMANTIC,
                similarity=sem_result.similarity,
            )

        # --- Tier 3: intent ---
        # sem_result is a CacheMiss carrying the full-prompt embedding (reused for semantic store).
        # We embed the *stripped* canonical form separately for the intent search.
        extracted = self._extractor.extract(request.prompt)
        stripped_embedding = await self._embeddings.embed(extracted.canonical)
        verdict_serve = False
        intent_verdict = None
        try:
            candidates = await self._intent_repo.search(
                stripped_embedding, self._intent_match_threshold
            )
            intent_verdict = await self._intent_gate.evaluate(
                request.prompt, extracted.parameters, candidates
            )
            verdict_serve = intent_verdict.serve
        except Exception:  # noqa: BLE001
            _log.warning("intent tier error; falling through to live", exc_info=True)

        if verdict_serve and intent_verdict is not None and intent_verdict.candidate is not None:
            return ServedCompletion(
                text=intent_verdict.candidate.response,
                model=intent_verdict.candidate.model_used,
                cached=True,
                tier=CacheTier.INTENT,
                similarity=intent_verdict.candidate.similarity,
                confidence=intent_verdict.confidence,
            )

        # --- Live path: classify → route → backend ---
        complexity = await self._classifier.classify(request.prompt)
        backend = self._router.select(complexity)
        completion = await backend.complete(request)

        # --- Action seam (D45): a tool-call reply is an action, not a reusable answer. ---
        # It reflects live, mutable external state (a write, or a read whose value moves), so
        # it is never cached — never stored, thus never matched or re-served. Closes F6.
        if completion.tool_call is not None:
            return ServedCompletion(
                text=completion.text,
                model=completion.model,
                cached=False,
                tier=CacheTier.LIVE,
                tool_call=completion.tool_call,
            )

        # --- Admission routing (D28): paramless → semantic store; parameterized → intent store ---
        try:
            if extracted.parameters:
                # Parameterized: write to the intent store only (stripped canonical + parameters).
                # The raw prompt never enters cache_entries.
                intent_entry = IntentEntry(
                    id=uuid4(),
                    canonical_prompt=extracted.canonical,
                    response=completion.text,
                    model_used=completion.model,
                    embedding=stripped_embedding,
                    parameters=extracted.parameters,
                    created_at=datetime.now(UTC),
                )
                await self._intent_repo.store(intent_entry)
            else:
                # Paramless: write to the semantic store (reusing the miss embedding, D12).
                await self._cache.store(
                    request.prompt,
                    completion.text,
                    completion.model,
                    embedding=sem_result.embedding,
                )
        except Exception:  # noqa: BLE001 — best-effort write; caller still gets their answer
            _log.warning("store failed after generation; returning result uncached", exc_info=True)

        return ServedCompletion(
            text=completion.text,
            model=completion.model,
            cached=False,
            tier=CacheTier.LIVE,
        )
