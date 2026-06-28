"""The tool menu and the FAQ the eshop hands the gateway (D47, D51).

``TOOL_MENU`` is in the exact OpenAI tool shape; the gateway forwards it verbatim and never
inspects it. ``FAQ`` is a short hardcoded policy blob passed as ``context`` — the gateway injects
it as a system message but keeps every cache key on the question alone (D51). Where this text comes
from is the app's business; a real build would retrieve it (RAG is OUT of this slice).
"""

from __future__ import annotations

from typing import Any


def _order_tool(name: str, description: str) -> dict[str, Any]:
    """Build one OpenAI-shape function tool taking a single ``order_id`` string."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order's id."},
                },
                "required": ["order_id"],
            },
        },
    }


TOOL_MENU: list[dict[str, Any]] = [
    _order_tool("cancel_order", "Cancel the customer's order by id."),
    _order_tool("refund_order", "Refund the customer's order by id."),
    _order_tool("get_order_status", "Look up the current status of an order by id."),
]


FAQ: str = (
    "Store policy FAQ. "
    "Returns: 30 days, unworn, tags on. "
    "Shipping: standard 3-5 business days, free over $50. "
    "Refunds: processed to the original payment method within 5 business days."
)
