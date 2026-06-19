"""Model routing — a concrete :class:`ModelRouter`.

Maps an assessed :class:`Complexity` to the cheapest backend that can serve it. Constructed with
the backends it may choose from. Stub only in the harness slice.
"""

from __future__ import annotations

from collections.abc import Mapping

from gateway.domain.models import Complexity
from gateway.domain.ports import ModelBackend


class CostAwareRouter:
    """Selects a backend by complexity tier. Implements ``ModelRouter``."""

    def __init__(self, backends: Mapping[Complexity, ModelBackend]) -> None:
        self._backends = backends

    def select(self, complexity: Complexity) -> ModelBackend:
        raise NotImplementedError
