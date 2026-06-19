"""``python -m gateway`` — the run entrypoint that owns process-wide runtime setup.

The one thing this does that ``uvicorn gateway.main:app`` cannot: it runs the server on a
``SelectorEventLoop`` on Windows. psycopg async refuses the ProactorEventLoop, and uvicorn
hard-codes Proactor on Windows (``uvicorn.loops.asyncio``) regardless of the asyncio policy — so we
bypass uvicorn's loop selection and drive ``Server.serve()`` on a loop we build ourselves. Off
Windows this path is unused and ``uvicorn gateway.main:app`` works directly.
"""

from __future__ import annotations

import asyncio
import sys

import uvicorn

from gateway.config import get_settings


def main() -> None:
    settings = get_settings()
    config = uvicorn.Config("gateway.main:app", host=settings.host, port=settings.port)
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        # Force a selector loop; uvicorn's own factory would hand us Proactor here.
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        server.run()


if __name__ == "__main__":
    main()
