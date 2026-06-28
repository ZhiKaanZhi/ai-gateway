"""API-level tests for the eshop app — offline, the gateway client mocked.

The eshop's job is the execute loop: relay a message to the gateway, and if the reply carries a
tool call, run it against the in-memory store and return the templated confirmation (D49); else
return the model's text. These tests mock ``GatewayClient`` so no gateway or model is needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from eshop import store
from eshop.app import create_app, get_gateway_client
from eshop.gateway_client import GatewayReply
from gateway.domain.models import ToolCall

ClientFactory = Callable[[GatewayReply], AsyncClient]


class FakeGatewayClient:
    """Returns a canned reply and records the messages it was asked to relay."""

    def __init__(self, reply: GatewayReply) -> None:
        self._reply = reply
        self.messages: list[str] = []

    async def chat(self, message: str) -> GatewayReply:
        self.messages.append(message)
        return self._reply


@pytest.fixture(autouse=True)
def reset_store() -> Iterator[None]:
    """Restore the in-memory order dict after each test (it's module-level, mutated by tools)."""
    snapshot = dict(store._ORDERS)
    yield
    store._ORDERS.clear()
    store._ORDERS.update(snapshot)


@pytest.fixture
def eshop_app() -> FastAPI:
    return create_app()


@pytest_asyncio.fixture
async def make_client(eshop_app: FastAPI) -> AsyncIterator[ClientFactory]:
    """Yield a builder: given a canned gateway reply, return an HTTP client on a faked app."""
    clients: list[AsyncClient] = []

    def _build(reply: GatewayReply) -> AsyncClient:
        eshop_app.dependency_overrides[get_gateway_client] = lambda: FakeGatewayClient(reply)
        http = AsyncClient(transport=ASGITransport(app=eshop_app), base_url="http://test")
        clients.append(http)
        return http

    yield _build
    for http in clients:
        await http.aclose()
    eshop_app.dependency_overrides.clear()


async def test_tool_call_reply_is_executed_against_the_store(make_client: ClientFactory) -> None:
    """A cancel_order tool call flips the order to cancelled and returns the confirmation (D49)."""
    reply = GatewayReply(
        response="", tool_call=ToolCall(name="cancel_order", arguments={"order_id": "1111"})
    )
    http = make_client(reply)
    response = await http.post("/chat", json={"message": "cancel order 1111"})

    assert response.status_code == 200
    assert response.json() == {"reply": "Done — order 1111 cancelled."}
    # The side effect actually happened.
    status = await http.get("/orders/1111")
    assert status.json() == {"reply": "Order 1111 is cancelled."}


async def test_text_reply_is_returned_as_is(make_client: ClientFactory) -> None:
    """A plain-text reply (e.g. an FAQ answer) is returned untouched — no tool executed."""
    reply = GatewayReply(response="30 days, unworn, tags on.")
    http = make_client(reply)
    response = await http.post("/chat", json={"message": "what's your return policy?"})

    assert response.status_code == 200
    assert response.json() == {"reply": "30 days, unworn, tags on."}


async def test_missing_order_id_falls_back_to_plain_text(make_client: ClientFactory) -> None:
    """The model controls the args dict; a missing order_id yields a fallback, never a crash."""
    reply = GatewayReply(response="", tool_call=ToolCall(name="cancel_order", arguments={}))
    http = make_client(reply)
    response = await http.post("/chat", json={"message": "cancel my order"})

    assert response.status_code == 200
    assert response.json() == {"reply": "Sorry — I couldn't read the order id."}


async def test_direct_order_endpoints(make_client: ClientFactory) -> None:
    """The curl-able order endpoints (D46) wrap the store directly."""
    http = make_client(GatewayReply(response="unused"))

    assert (await http.get("/orders/2222")).json() == {"reply": "Order 2222 is open."}
    assert (await http.post("/orders/2222/refund")).json() == {"reply": "Refunded order 2222."}
    assert (await http.get("/orders/2222")).json() == {"reply": "Order 2222 is refunded."}
    assert (await http.get("/orders/9999")).json() == {"reply": "Order 9999 not found."}
