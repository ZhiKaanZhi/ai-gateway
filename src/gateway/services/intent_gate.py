"""Intent gate — the service that decides whether to serve a cached intent candidate.

The gate is a service (not a port — it orchestrates seams, like the pipeline and cache service,
per D29). It takes the ranked candidates from ``IntentRepository.search`` plus the incoming
request's extracted parameters, applies cheap signals, and calls the ``Verifier`` only when the
cached candidate was built for a *different parameter value* than the incoming request — the
**value-mismatch** trigger (D32). The verifier is no longer gated on a confidence band; that band
was structurally unreachable for a clean fresh match and orthogonal to binding (D33).

The two load-bearing distinctions (from GLOSSARY.md):
  - Intent match ≠ serve. The matcher found a candidate; the gate decides if it's safe.
  - Similarity ≠ confidence. Similarity is an input (its own field); confidence is the output —
    and it is the Verifier's score only when the model actually ran, else ``None`` (D34).

Threshold constants are injected from config so they can be calibrated against the eval set
(D30) rather than guessed.
"""

from __future__ import annotations

import dataclasses

from gateway.domain.models import IntentCandidate
from gateway.domain.ports import Verifier


@dataclasses.dataclass(frozen=True, slots=True)
class GateVerdict:
    """The gate's serve/refuse decision plus the confidence it recorded.

    ``confidence`` is the Verifier's score **only when the model ran** (the value-changed,
    non-echoing path); every cheap-signal verdict carries ``None``. ``None`` means "served/refused
    on cheap signals, not model-scored" — **not** low confidence (D34). Similarity is a separate
    axis and lives on ``IntentCandidate`` / ``ServedCompletion``, never folded in here.
    """

    serve: bool
    confidence: float | None = None
    candidate: IntentCandidate | None = None


class IntentGate:
    """Serve/refuse verdict from cheap signals + value-mismatch verification (D32).

    Cheap refusals (no candidates, stale, low margin) and cheap serves (value-independent or
    same-value cached answer) never touch the model. Only a value change with a non-echoing answer
    — a possible transform that no surface test can detect — consults the ``Verifier``.
    """

    def __init__(
        self,
        verifier: Verifier,
        *,
        margin_min: float,
        staleness_max_seconds: float,
        verify_pass_threshold: float,
    ) -> None:
        self._verifier = verifier
        self._margin_min = margin_min
        self._staleness_max = staleness_max_seconds
        self._verify_pass = verify_pass_threshold

    async def evaluate(
        self, question: str, new_parameters: list[str], candidates: list[IntentCandidate]
    ) -> GateVerdict:
        """Decide whether to serve the best candidate for ``question``.

        ``new_parameters`` are the parameters extracted from the *incoming* request; the binding
        risk is judged by comparing them against the cached candidate's stored parameters (D32).
        """
        if not candidates:
            return GateVerdict(serve=False)

        best = candidates[0]

        # --- Cheap signal 1: staleness ---
        if best.age_seconds > self._staleness_max:
            return GateVerdict(serve=False)

        # --- Cheap signal 2: top1–top2 margin ---
        margin = (best.similarity - candidates[1].similarity) if len(candidates) > 1 else 1.0
        if margin < self._margin_min:
            return GateVerdict(serve=False)

        # --- Parameter relationship (D32). Binding risk is a property of the *cached* answer. ---
        cached_params = _normalise(best.parameters)
        if not cached_params:
            # Value-independent: the cached answer never used a parameter → reusable across values.
            return GateVerdict(serve=True, candidate=best)
        if cached_params == _normalise(new_parameters):
            # Same value: the answer was generated for this exact input → safe to serve.
            return GateVerdict(serve=True, candidate=best)

        # Value changed. If the answer echoes a cached (old) value it is bound → reject-fast
        # cheaply, with no model call. Absence of an echo is *not* evidence of independence (it may
        # be a transform, e.g. "Translate 'hello'" → "Hola." reused for "goodbye"), so we ask the
        # Verifier — the only thing that can judge value-dependence a surface test cannot see.
        if _answer_echoes_param(best):
            return GateVerdict(serve=False)

        verify_score = await self._verifier.verify(question, best.response)
        serve = verify_score >= self._verify_pass
        return GateVerdict(serve=serve, confidence=verify_score, candidate=best if serve else None)


def _normalise(parameters: list[str]) -> frozenset[str]:
    """Order-independent, case/whitespace-insensitive view of a parameter list (D32)."""
    return frozenset(p.strip().lower() for p in parameters)


def _answer_echoes_param(candidate: IntentCandidate) -> bool:
    """Return True if the stored answer text contains any of the stored parameter values.

    A reject-fast signal only (D32): an echoed parameter *is* evidence the answer is bound to that
    value (sound to refuse on), but its absence is *not* evidence of independence (a transform
    shares no letters with its input) — so this is never used as a serve signal.
    """
    if not candidate.parameters:
        return False
    answer_lower = candidate.response.lower()
    return any(param.lower() in answer_lower for param in candidate.parameters)
