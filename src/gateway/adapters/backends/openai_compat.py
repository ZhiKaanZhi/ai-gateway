"""OpenAI-compatible model backend — implements :class:`ModelBackend`.

All ``httpx`` is confined here; the pipeline and routes never import it (the same confinement rule
as raw SQL behind the repository, D14). Named for the contract, not the provider: Ollama today,
Groq/OpenAI later is a base-URL + key change in the composition root, not a new adapter.
Non-streaming only (``stream=false``).
"""

from __future__ import annotations

from typing import Any

import httpx

from gateway.domain.errors import BackendError
from gateway.domain.models import CompletionRequest, CompletionResult


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
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
        }
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
            text: str = data["choices"][0]["message"]["content"]
            served_model: str = data.get("model", model)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise BackendError(f"malformed backend response: {exc}", is_timeout=False) from exc

        return CompletionResult(text=text, model=served_model)
