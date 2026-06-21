"""Intent gate — the service that decides whether to serve a cached intent candidate.

The gate is a service (not a port — it orchestrates seams, like the pipeline and cache service,
per D29). It takes the ranked candidates from ``IntentRepository.search``, combines cheap signals,
and calls the ``Verifier`` only on the uncertain middle band (D26).

The two load-bearing distinctions (from GLOSSARY.md):
  - Intent match ≠ serve. The matcher found a candidate; the gate decides if it's safe.
  - Similarity ≠ confidence. Similarity is an input; confidence is the output.

Threshold constants are injected from config so they can be calibrated against the eval set
(D30) rather than guessed.
"""

from __future__ import annotations

import dataclasses

from gateway.domain.models import IntentCandidate
from gateway.domain.ports import Verifier


@dataclasses.dataclass(frozen=True, slots=True)
class GateVerdict:
    """The gate's serve/refuse decision plus the confidence score it computed."""

    serve: bool
    confidence: float
    candidate: IntentCandidate | None = None


class IntentGate:
    """Combines cheap signals + borderline verification to produce a serve/refuse verdict (D26)."""

    def __init__(
        self,
        verifier: Verifier,
        *,
        margin_min: float,
        staleness_max_seconds: float,
        verify_band_lo: float,
        verify_band_hi: float,
        verify_pass_threshold: float,
    ) -> None:
        self._verifier = verifier
        self._margin_min = margin_min
        self._staleness_max = staleness_max_seconds
        self._band_lo = verify_band_lo
        self._band_hi = verify_band_hi
        self._verify_pass = verify_pass_threshold

    async def evaluate(self, question: str, candidates: list[IntentCandidate]) -> GateVerdict:
        """Evaluate the candidate list against the question. Returns a serve/refuse verdict."""
        if not candidates:
            return GateVerdict(serve=False, confidence=0.0)

        best = candidates[0]

        # --- Cheap signal 1: staleness ---
        if best.age_seconds > self._staleness_max:
            return GateVerdict(serve=False, confidence=0.0)

        # --- Cheap signal 2: top1–top2 margin ---
        margin = (best.similarity - candidates[1].similarity) if len(candidates) > 1 else 1.0
        if margin < self._margin_min:
            return GateVerdict(serve=False, confidence=0.0)

        # --- Cheap signal 3: binding check (D25) ---
        # If the stored answer text contains any of the stored parameters, the answer was
        # built from that specific parameter value — serving it for a different parameter
        # would be wrong. Only refuse when the current request's parameters differ.
        if _answer_is_bound(best):
            return GateVerdict(serve=False, confidence=0.0)

        # --- Combine cheap signals into a base confidence ---
        staleness_score = 1.0 - min(best.age_seconds / self._staleness_max, 1.0)
        base_confidence = 0.5 * best.similarity + 0.3 * staleness_score + 0.2 * margin

        # --- Uncertain middle band: call the Verifier ---
        if self._band_lo <= base_confidence < self._band_hi:
            verify_score = await self._verifier.verify(question, best.response)
            if verify_score < self._verify_pass:
                return GateVerdict(serve=False, confidence=verify_score, candidate=best)
            confidence = 0.7 * verify_score + 0.3 * base_confidence
            return GateVerdict(serve=True, confidence=confidence, candidate=best)

        # --- Clear pass or clear refuse outside the band ---
        if base_confidence >= self._band_hi:
            return GateVerdict(serve=True, confidence=base_confidence, candidate=best)

        return GateVerdict(serve=False, confidence=base_confidence)


def _answer_is_bound(candidate: IntentCandidate) -> bool:
    """Return True if the stored answer text contains any of the stored parameter values.

    A bound answer was generated from that specific parameter — it cannot be safely
    cross-served for a request with different parameters (D25).
    """
    if not candidate.parameters:
        return False
    answer_lower = candidate.response.lower()
    return any(param.lower() in answer_lower for param in candidate.parameters)
