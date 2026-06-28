"""OpenAI-compatible model backend — implements :class:`ModelBackend`.

All ``httpx`` is confined here; the pipeline and routes never import it (the same confinement rule
as raw SQL behind the repository, D14). Named for the contract, not the provider: Ollama today,
Groq/OpenAI later is a base-URL + key change in the composition root, not a new adapter.
Non-streaming only (``stream=false``).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from gateway.domain.errors import BackendError
from gateway.domain.models import CompletionRequest, CompletionResult, ToolCall


class OpenAICompatibleBackend:
    """Talks the OpenAI chat-completions contract over httpx. Implements ``ModelBackend``.

    The ``AsyncClient`` is injected from the composition root (built with ``base_url`` + timeout,
    closed on shutdown) — the backend never owns or creates its own client.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        model: str,
        api_key: str | None,
    ) -> None:
        self._client = client
        self._model = model
        self._api_key = api_key

    @property
    def name(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """POST to /chat/completions; map the reply to CompletionResult.

        Raises BackendError on transport/timeout, non-2xx, or malformed body.
        httpx never escapes this method.
        """
        model = request.model or self._model
        # Injected context (e.g. an FAQ) rides as a system message before the user prompt (D51).
        messages: list[dict[str, Any]] = []
        if request.context:
            messages.append({"role": "system", "content": request.context})
        messages.append({"role": "user", "content": request.prompt})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        # The tool menu is forwarded verbatim — the gateway never inspects it (D47).
        if request.tools:
            payload["tools"] = request.tools
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        try:
            response = await self._client.post("/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise BackendError(f"backend timed out: {exc}", is_timeout=True) from exc
        except httpx.HTTPError as exc:
            raise BackendError(f"backend transport error: {exc}", is_timeout=False) from exc

        if response.status_code // 100 != 2:
            raise BackendError(f"backend returned {response.status_code}", is_timeout=False)

        try:
            data: dict[str, Any] = response.json()
            served_model: str = data.get("model", model)
            message: dict[str, Any] = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls")
            if tool_calls:
                # An action: parse the first call only (D48). Ollama returns `arguments` as a JSON
                # *string*, so it must be decoded into the dict ToolCall expects.
                call = tool_calls[0]["function"]
                arguments = json.loads(call["arguments"])
                if not isinstance(arguments, dict):
                    # Valid JSON but not an object (e.g. "[]") — ToolCall would raise a pydantic
                    # ValidationError, which isn't in the except tuple below. Reject here instead.
                    raise BackendError(
                        "malformed backend response: tool arguments are not an object",
                        is_timeout=False,
                    )
                return CompletionResult(
                    text=message.get("content") or "",
                    model=served_model,
                    tool_call=ToolCall(name=call["name"], arguments=arguments),
                )
            text: str = message["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # json.JSONDecodeError is a ValueError subclass → malformed `arguments` lands here too.
            raise BackendError(f"malformed backend response: {exc}", is_timeout=False) from exc

        return CompletionResult(text=text, model=served_model)
