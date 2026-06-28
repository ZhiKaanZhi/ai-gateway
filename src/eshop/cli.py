"""A dumb console chat client for the eshop — ``python -m eshop.cli`` (demo toy, untested).

Read a line, POST it to the eshop's ``/chat``, print the reply, repeat until ``quit``. No state, no
history, no logic: all brains stay in the gateway and the app (D50). The eshop URL comes from
``ESHOP_URL`` (default ``http://localhost:8001``).
"""

from __future__ import annotations

import os

import httpx


def main() -> None:
    base_url = os.getenv("ESHOP_URL", "http://localhost:8001")
    print("eshop chat — type 'quit' to exit.")
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        while True:
            try:
                message = input("you > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not message:
                continue
            if message.lower() == "quit":
                break
            try:
                response = client.post("/chat", json={"message": message})
                response.raise_for_status()
                print(f"shop> {response.json()['reply']}")
            except httpx.HTTPError as exc:
                print(f"shop> (error talking to the eshop: {exc})")


if __name__ == "__main__":
    main()
