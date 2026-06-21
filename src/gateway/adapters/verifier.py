"""Model-backed Verifier — implements :class:`Verifier`.

Asks a cheap model point-blank: "does this cached answer actually answer this question?"
Returns a score in [0, 1]; the **gate** owns the pass cutoff (D26 / D29) so the verify band
is calibrated from the eval set (D30) and not buried in this adapter.

``httpx`` is confined to this adapter — it never escapes into services (same discipline as
``OpenAICompatibleBackend`` and D14 for SQL). The httpx client is injected from the lifespan
composition root so its lifecycle (aclose) is managed there.
"""

from __future__ import annotations

import httpx

_SYSTEM_PROMPT = (
    "You are a strict relevance judge. "
    "Reply with a single number between 0.0 and 1.0 (and nothing else): "
    "how well does the CACHED ANSWER address the QUESTION? "
    "1.0 = fully answers it; 0.0 = completely wrong or irrelevant."
)

_USER_TEMPLATE = "QUESTION: {question}\n\nCACHED ANSWER: {answer}"


class ModelVerifier:
    """Calls a cheap chat model to score whether a cached answer fits a new question.

    Implements ``Verifier``. Returns 0.0 on any parse/transport error (precision bias — when
    in doubt, refuse to serve the cached answer).
    """

    def __init__(self, client: httpx.AsyncClient, model: str, api_key: str | None = None) -> None:
        self._client = client
        self._model = model
        self._headers: dict[str, str] = {}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    async def verify(self, question: str, candidate_answer: str) -> float:
        """Score how well ``candidate_answer`` addresses ``question``. Returns [0, 1]."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_TEMPLATE.format(question=question, answer=candidate_answer),
                },
            ],
            "stream": False,
            "temperature": 0.0,
        }
        try:
            resp = await self._client.post("/chat/completions", json=payload, headers=self._headers)
            resp.raise_for_status()
            body = resp.json()
            text = body["choices"][0]["message"]["content"].strip()
            score = float(text)
            return max(0.0, min(1.0, score))
        except Exception:  # noqa: BLE001 — any failure → refuse (precision bias)
            return 0.0
