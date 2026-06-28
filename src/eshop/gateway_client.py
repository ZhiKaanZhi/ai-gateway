"""The seam to the gateway — all of the eshop's ``httpx`` is confined here.

Mirrors the gateway's own httpx confinement: the ``AsyncClient`` is injected (built and closed by
the app's lifespan), never owned here. One method, ``chat``, POSTs the message plus the tool menu
and the FAQ-as-context, and parses the reply into a small typed model so no loose dict crosses the
app's own seam. This is the function CI mocks and the live run hits for real.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict

from eshop.tools import FAQ, TOOL_MENU
from gateway.domain.models import ToolCall


class GatewayReply(BaseModel):
    """The slice of the gateway's response the eshop cares about.

    The gateway returns more (tier, similarity, …); ``extra="ignore"`` drops what we don't use.
    ``tool_call`` reuses the gateway's domain type rather than redefining the shape.
    """

    model_config = ConfigDict(extra="ignore")

    response: str
    tool_call: ToolCall | None = None


class GatewayClient:
    """Thin async client over the gateway's ``/v1/chat`` endpoint."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def chat(self, message: str) -> GatewayReply:
        """Send a user message (with the tool menu + FAQ) and return the parsed reply."""
        response = await self._client.post(
            "/v1/chat",
            json={"prompt": message, "tools": TOOL_MENU, "context": FAQ},
        )
        response.raise_for_status()
        return GatewayReply.model_validate(response.json())
