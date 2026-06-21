"""Unit tests for OpenAICompatibleBackend — offline, no network.

Uses httpx.MockTransport to simulate the backend wire without a running server or new dependencies.
Covers: correct reply mapping, non-2xx, timeout, malformed body, and structural Protocol fit.
"""

from __future__ import annotations

import json

import httpx
import pytest

from gateway.adapters.backends.openai_compat import OpenAICompatibleBackend
from gateway.domain.errors import BackendError
from gateway.domain.models import CompletionRequest
from gateway.domain.ports import ModelBackend


def _canned_response(
    *,
    status: int = 200,
    body: object | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response for MockTransport."""
    content = json.dumps(body).encode() if body is not None else b""
    return httpx.Response(status_code=status, content=content)


def _make_backend(handler: httpx.MockTransport) -> OpenAICompatibleBackend:
    client = httpx.AsyncClient(transport=handler, base_url="http://fake")
    return OpenAICompatibleBackend(client, model="test-model", api_key=None)


_VALID_BODY = {
    "model": "test-model",
    "choices": [{"message": {"content": "Hello from the model"}}],
}


async def test_valid_reply_maps_to_completion_result() -> None:
    backend = _make_backend(httpx.MockTransport(lambda r: _canned_response(body=_VALID_BODY)))
    result = await backend.complete(CompletionRequest(prompt="hi"))
    assert result.text == "Hello from the model"
    assert result.model == "test-model"


async def test_non_2xx_raises_backend_error_not_timeout() -> None:
    backend = _make_backend(httpx.MockTransport(lambda r: _canned_response(status=500, body={})))
    with pytest.raises(BackendError) as exc_info:
        await backend.complete(CompletionRequest(prompt="hi"))
    assert exc_info.value.is_timeout is False


async def test_timeout_raises_backend_error_is_timeout() -> None:
    def _raise(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=httpx.Request("POST", "http://fake"))

    backend = _make_backend(httpx.MockTransport(_raise))
    with pytest.raises(BackendError) as exc_info:
        await backend.complete(CompletionRequest(prompt="hi"))
    assert exc_info.value.is_timeout is True


async def test_malformed_body_empty_object_raises_backend_error() -> None:
    backend = _make_backend(httpx.MockTransport(lambda r: _canned_response(body={})))
    with pytest.raises(BackendError) as exc_info:
        await backend.complete(CompletionRequest(prompt="hi"))
    assert exc_info.value.is_timeout is False


async def test_malformed_body_empty_choices_raises_backend_error() -> None:
    backend = _make_backend(
        httpx.MockTransport(lambda r: _canned_response(body={"choices": []}))
    )
    with pytest.raises(BackendError) as exc_info:
        await backend.complete(CompletionRequest(prompt="hi"))
    assert exc_info.value.is_timeout is False


def test_backend_satisfies_model_backend_protocol() -> None:
    client = httpx.AsyncClient(base_url="http://fake")
    backend = OpenAICompatibleBackend(client, model="m", api_key=None)
    assert isinstance(backend, ModelBackend)
