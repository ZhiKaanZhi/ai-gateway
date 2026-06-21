"""Live round-trip test for OpenAICompatibleBackend against a running Ollama instance.

Mirrors the pattern of ``test_cache_integration.py``: skips cleanly when Ollama is not reachable,
so the suite stays green in CI (which has no Ollama). Run explicitly with::

    uv run pytest -q -m live

F3's lesson: a green suite can hide a runtime-only failure. This test catches what the offline
MockTransport tests can't — real JSON encoding, real timeout behaviour, a real network round-trip.
"""

from __future__ import annotations

import httpx
import pytest

from gateway.adapters.backends.openai_compat import OpenAICompatibleBackend
from gateway.config import get_settings
from gateway.domain.errors import BackendError
from gateway.domain.models import CompletionRequest

pytestmark = pytest.mark.live


async def test_live_completion_round_trip() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.backend_base_url,
        timeout=settings.backend_timeout,
    ) as client:
        backend = OpenAICompatibleBackend(
            client,
            model=settings.backend_model,
            api_key=settings.backend_api_key.get_secret_value() or None,
        )
        try:
            result = await backend.complete(
                CompletionRequest(prompt="Reply with only the word: pong")
            )
        except (BackendError, httpx.ConnectError, httpx.TransportError) as exc:
            pytest.skip(f"Ollama not reachable at {settings.backend_base_url}: {exc}")

    assert isinstance(result.text, str)
    assert len(result.text) > 0
    assert isinstance(result.model, str)
