"""The eshop FastAPI app — composition root mirrors the gateway's (lifespan + app.state + Depends).

``POST /chat`` relays the user's message to the gateway; if the reply carries a tool call, the app
executes it against the in-memory store and returns the templated confirmation (D49); otherwise it
returns the model's text (a cached-or-live answer, e.g. from the FAQ). A few direct order endpoints
make the store curl-able by hand (D46). The gateway never performs the side effect — the app does.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel

from eshop import store
from eshop.gateway_client import GatewayClient

# Each tool maps to a store function of the same name; all take a single order_id (D48 single-call).
_TOOL_DISPATCH: dict[str, Callable[[str], str]] = {
    "cancel_order": store.cancel_order,
    "refund_order": store.refund_order,
    "get_order_status": store.get_order_status,
}

router = APIRouter()


class ChatMessage(BaseModel):
    """A single user message into the eshop's chat box (D50: one message, no history)."""

    message: str


class ChatReply(BaseModel):
    """What the eshop says back — a confirmation, an answer, or a fallback string."""

    reply: str


class OrderReply(BaseModel):
    """The result of a direct order operation (the templated store string)."""

    reply: str


def get_gateway_client(request: Request) -> GatewayClient:
    """Hand handlers the gateway client wired in the lifespan (composition root)."""
    client: GatewayClient = request.app.state.gateway_client
    return client


GatewayClientDep = Annotated[GatewayClient, Depends(get_gateway_client)]


@router.post("/chat")
async def chat(body: ChatMessage, gateway: GatewayClientDep) -> ChatReply:
    """Relay to the gateway; execute a tool call against the store, else return the model's text."""
    reply = await gateway.chat(body.message)

    if reply.tool_call is not None:
        func = _TOOL_DISPATCH.get(reply.tool_call.name)
        if func is None:
            return ChatReply(reply=f"Sorry — I don't know how to {reply.tool_call.name}.")
        # The model controls the arguments dict, so read order_id defensively — never splat it.
        order_id = reply.tool_call.arguments.get("order_id")
        if not order_id or not isinstance(order_id, str):
            return ChatReply(reply="Sorry — I couldn't read the order id.")
        return ChatReply(reply=func(order_id))

    return ChatReply(reply=reply.response)


@router.get("/orders/{order_id}")
async def order_status(order_id: str) -> OrderReply:
    """Read an order's status directly (D46)."""
    return OrderReply(reply=store.get_order_status(order_id))


@router.post("/orders/{order_id}/cancel")
async def order_cancel(order_id: str) -> OrderReply:
    """Cancel an order directly (D46)."""
    return OrderReply(reply=store.cancel_order(order_id))


@router.post("/orders/{order_id}/refund")
async def order_refund(order_id: str) -> OrderReply:
    """Refund an order directly (D46)."""
    return OrderReply(reply=store.refund_order(order_id))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the gateway httpx client on startup, close it on shutdown (httpx stays at the seam)."""
    base_url = os.getenv("ESHOP_GATEWAY_URL", "http://localhost:8000")
    client = httpx.AsyncClient(base_url=base_url, timeout=60.0)
    app.state.gateway_client = GatewayClient(client)
    try:
        yield
    finally:
        await client.aclose()


def create_app() -> FastAPI:
    """Build the eshop FastAPI app. Factory form keeps tests free to construct fresh apps."""
    app = FastAPI(title="eshop", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
