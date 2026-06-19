"""A trivial :class:`ModelBackend` that echoes the prompt back.

Useful as a placeholder backend and as a sanity check for the routing path before any real
provider (via ``httpx``) is wired in. Stub only in the harness slice.
"""

from __future__ import annotations

from gateway.domain.models import CompletionRequest, CompletionResult


class EchoBackend:
    """Returns the prompt unchanged. Implements ``ModelBackend``."""

    @property
    def name(self) -> str:
        return "echo"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise NotImplementedError
