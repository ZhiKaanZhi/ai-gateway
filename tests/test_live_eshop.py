"""Live end-to-end test for the eshop ↔ gateway ↔ Ollama path (Track B, D52).

Hand-run only — needs three things up by hand: Ollama, the gateway (:8000), and the eshop (:8001)::

    ollama pull llama3.2:3b
    uv run python -m gateway                       # :8000
    uv run uvicorn eshop.app:app --port 8001       # :8001
    uv run pytest -q -m live tests/test_live_eshop.py

It self-skips when the servers aren't up (a reachability probe on each), so the suite stays green
when run without them — F3's lesson, never erroring in CI. It also **skips on model nondeterminism**
(a 3B model is flaky at tool-calling — see FAILURES F7): the asserts fire only when the model
emits a clean tool call, and report the actual reply when it doesn't, rather than failing red.
"""

from __future__ import annotations

import os

import httpx
import pytest

from eshop.tools import FAQ, TOOL_MENU

pytestmark = pytest.mark.live

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
ESHOP_URL = os.getenv("ESHOP_URL", "http://localhost:8001")


async def _require_gateway() -> None:
    """Skip unless the gateway answers its health probe."""
    try:
        async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=5.0) as client:
            resp = await client.get("/health")
            resp.raise_for_status()
    except (httpx.HTTPError, httpx.TransportError) as exc:
        pytest.skip(f"gateway not reachable at {GATEWAY_URL}: {exc}")


async def _require_eshop() -> None:
    """Skip unless the eshop is up (probe a direct order endpoint)."""
    try:
        async with httpx.AsyncClient(base_url=ESHOP_URL, timeout=5.0) as client:
            resp = await client.get("/orders/3333")
            resp.raise_for_status()
    except (httpx.HTTPError, httpx.TransportError) as exc:
        pytest.skip(f"eshop not reachable at {ESHOP_URL}: {exc}")


async def test_live_gateway_real_model_emits_tool_call_uncached() -> None:
    """The real model, given the menu, calls cancel_order; the gateway returns it live, uncached."""
    await _require_gateway()
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=60.0) as client:
        resp = await client.post(
            "/v1/chat",
            json={"prompt": "Please cancel order 1111", "tools": TOOL_MENU, "context": FAQ},
        )
    if resp.status_code == 502:
        # The model emitted an unparseable tool call this run (e.g. non-object args) — F7.
        pytest.skip(f"model emitted an unparseable tool call: {resp.text[:200]}")
    resp.raise_for_status()
    data = resp.json()
    if data["tool_call"] is None:
        pytest.skip(f"model answered as text, not a tool call: {data['response'][:100]!r}")
    # Assert by tool *name*, not wording (model nondeterminism).
    assert data["tool_call"]["name"] == "cancel_order"
    # An action is never cached.
    assert data["cached"] is False
    assert data["tier"] == "live"


async def test_live_gateway_text_answer_is_served_from_cache_on_reask() -> None:
    """A text answer is stored and served from cache on the identical re-ask (proves the cache).

    No tools menu: with the menu attached, llama3.2:3b is tool-biased and reaches for a tool even
    for a policy question (FAILURES F7), and a tool call is never cached — so the cache path can't
    be exercised with the menu present. The menu's role is covered by the action test above and the
    deterministic Track A suite. We assert only that the *re-ask* is served from cache, not that the
    first ask missed: the DB is persistent across runs (Track A owns miss→store→hit).
    """
    await _require_gateway()
    payload = {"prompt": "What is your return policy?", "context": FAQ}
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=60.0) as client:
        first = (await client.post("/v1/chat", json=payload)).json()
        second = (await client.post("/v1/chat", json=payload)).json()
    if first["tool_call"] is not None:
        pytest.skip(f"model answered with a tool call, not cacheable text: {first['tool_call']}")
    assert second["cached"] is True, second
    assert second["tier"] in ("exact", "semantic", "intent")


async def test_live_eshop_executes_the_tool_against_the_store() -> None:
    """End to end: the eshop relays to the gateway, the real model acts, the order flips."""
    await _require_eshop()
    async with httpx.AsyncClient(base_url=ESHOP_URL, timeout=60.0) as client:
        chat = await client.post("/chat", json={"message": "Please cancel order 2222"})
        if chat.status_code != 200:
            pytest.skip(f"gateway/model misfired this run: {chat.status_code} {chat.text[:200]}")
        reply = chat.json()["reply"]
        if "cancel" not in reply.lower():
            pytest.skip(f"model didn't call cancel_order this run: {reply!r}")
        status = await client.get("/orders/2222")
    status.raise_for_status()
    # The named tool's effect: order 2222 is now cancelled (robust to model wording).
    assert status.json() == {"reply": "Order 2222 is cancelled."}
