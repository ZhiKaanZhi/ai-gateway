"""Unit tests for OpenAICompatibleBackend — offline, no network.

Uses httpx.MockTransport to simulate the backend wire without a running server or new dependencies.
Covers: correct reply mapping, non-2xx, timeout, malformed body, and structural Protocol fit.
"""

from __future__ import annotations

import json
from typing import Any

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
    backend = _make_backend(httpx.MockTransport(lambda r: _canned_response(body={"choices": []})))
    with pytest.raises(BackendError) as exc_info:
        await backend.complete(CompletionRequest(prompt="hi"))
    assert exc_info.value.is_timeout is False


def test_backend_satisfies_model_backend_protocol() -> None:
    client = httpx.AsyncClient(base_url="http://fake")
    backend = OpenAICompatibleBackend(client, model="m", api_key=None)
    assert isinstance(backend, ModelBackend)


# --- Slice 6: tool calls, context, and the tool menu (D47/D48/D51) ---

_TOOL_CALL_BODY = {
    "model": "test-model",
    "choices": [
        {
            "message": {
                "content": "",
                # Ollama returns `arguments` as a JSON *string*, not an object.
                "tool_calls": [
                    {"function": {"name": "cancel_order", "arguments": '{"order_id": "1111"}'}}
                ],
            }
        }
    ],
}


async def test_tool_call_arguments_string_is_parsed_into_dict() -> None:
    """A tool_calls reply (args as a JSON string) parses into a typed ToolCall with a real dict."""
    backend = _make_backend(httpx.MockTransport(lambda r: _canned_response(body=_TOOL_CALL_BODY)))
    result = await backend.complete(CompletionRequest(prompt="cancel 1111"))
    assert result.tool_call is not None
    assert result.tool_call.name == "cancel_order"
    assert result.tool_call.arguments == {"order_id": "1111"}


async def test_malformed_tool_call_arguments_raises_backend_error() -> None:
    """Non-JSON `arguments` is malformed → BackendError (json.JSONDecodeError ⊂ ValueError)."""
    bad_call = {"function": {"name": "x", "arguments": "{"}}
    body = {
        "model": "test-model",
        "choices": [{"message": {"content": "", "tool_calls": [bad_call]}}],
    }
    backend = _make_backend(httpx.MockTransport(lambda r: _canned_response(body=body)))
    with pytest.raises(BackendError) as exc_info:
        await backend.complete(CompletionRequest(prompt="hi"))
    assert exc_info.value.is_timeout is False


async def test_tool_call_arguments_that_arent_an_object_raise_backend_error() -> None:
    """Valid JSON but not an object (e.g. "[]") is rejected as BackendError, not a 500."""
    bad_call = {"function": {"name": "x", "arguments": "[]"}}
    body = {
        "model": "test-model",
        "choices": [{"message": {"content": "", "tool_calls": [bad_call]}}],
    }
    backend = _make_backend(httpx.MockTransport(lambda r: _canned_response(body=body)))
    with pytest.raises(BackendError) as exc_info:
        await backend.complete(CompletionRequest(prompt="hi"))
    assert exc_info.value.is_timeout is False


async def test_context_is_sent_as_a_system_message() -> None:
    """A request with context puts a system message ahead of the user prompt in the payload."""
    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _canned_response(body=_VALID_BODY)

    backend = _make_backend(httpx.MockTransport(_handler))
    await backend.complete(CompletionRequest(prompt="hi", context="FAQ blob"))

    messages = captured["body"]["messages"]
    assert messages[0] == {"role": "system", "content": "FAQ blob"}
    assert messages[1] == {"role": "user", "content": "hi"}


async def test_tools_are_forwarded_verbatim() -> None:
    """A request with tools puts the menu verbatim on the outbound payload (D47)."""
    captured: dict[str, Any] = {}
    menu = [{"type": "function", "function": {"name": "cancel_order"}}]

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _canned_response(body=_VALID_BODY)

    backend = _make_backend(httpx.MockTransport(_handler))
    await backend.complete(CompletionRequest(prompt="hi", tools=menu))

    assert captured["body"]["tools"] == menu


async def test_no_tools_means_no_tools_key_on_the_payload() -> None:
    """A plain request omits the tools key entirely (only sent when present)."""
    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _canned_response(body=_VALID_BODY)

    backend = _make_backend(httpx.MockTransport(_handler))
    await backend.complete(CompletionRequest(prompt="hi"))

    assert "tools" not in captured["body"]
