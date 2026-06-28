"""eshop: a tiny demo app that drives the gateway end to end (not part of the gateway).

A separate FastAPI service (port 8001) that owns the business — an in-memory order store, a tool
menu, and an FAQ — and calls the gateway over HTTP. The gateway stays generic: it relays the menu
and executes nothing; the eshop performs the side effect (D46). Demo-only: in-memory dict, no DB,
no auth, curl + console CLI. Business logic and the loose-dict tool menu live here by design;
the gateway's no-business-logic / no-loose-dict rules bind ``src/gateway/`` only.
"""
