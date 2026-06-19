"""Complexity classification — a concrete :class:`ComplexityClassifier`.

A heuristic (length / keyword) classifier is the planned default; a model-backed one can replace
it behind the same port. Stub only in the harness slice.
"""

from __future__ import annotations

from gateway.domain.models import Complexity


class HeuristicClassifier:
    """Assesses prompt complexity from cheap local signals. Implements ``ComplexityClassifier``."""

    async def classify(self, prompt: str) -> Complexity:
        raise NotImplementedError
