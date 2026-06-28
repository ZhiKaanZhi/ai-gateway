"""In-memory order store + the tool functions the eshop executes (D46).

A module-level dict stands in for a database — demo-only, no persistence (a real DB is OUT of
this slice). Each tool returns a fixed, templated confirmation string itself (D49): no second
model call, and deliberately no "Anything else?" tail (there is no conversation memory yet, D50).
"""

from __future__ import annotations

# order_id -> status. Mutated in place by the tools.
_ORDERS: dict[str, str] = {"1111": "open", "2222": "open", "3333": "shipped"}


def cancel_order(order_id: str) -> str:
    """Cancel an order and confirm. Returns a not-found message for an unknown id."""
    if order_id not in _ORDERS:
        return f"Order {order_id} not found."
    _ORDERS[order_id] = "cancelled"
    return f"Done — order {order_id} cancelled."


def refund_order(order_id: str) -> str:
    """Refund an order and confirm. Returns a not-found message for an unknown id."""
    if order_id not in _ORDERS:
        return f"Order {order_id} not found."
    _ORDERS[order_id] = "refunded"
    return f"Refunded order {order_id}."


def get_order_status(order_id: str) -> str:
    """Report an order's status. Returns a not-found message for an unknown id."""
    status = _ORDERS.get(order_id)
    if status is None:
        return f"Order {order_id} not found."
    return f"Order {order_id} is {status}."
