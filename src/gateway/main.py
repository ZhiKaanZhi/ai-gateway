"""Composition root — the one place singletons are built and wired.

The FastAPI ``lifespan`` is where long-lived resources (the psycopg ``AsyncConnectionPool``, the
fastembed model, the assembled pipeline) are constructed on startup and torn down on shutdown,
then handed to handlers via ``app.state`` / ``Depends``. No DI framework: plain construction here
is the whole mechanism.

In the harness slice the lifespan wires nothing yet — it documents the seam and yields. The pool
will be opened here per the ``pgvector-psycopg`` skill (``open=False`` in the constructor, then
``await pool.open()`` / ``await pool.close()`` around the ``yield``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gateway.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build singletons on startup, release them on shutdown."""
    # Startup: open the connection pool, load the embedding model, assemble the pipeline.
    yield
    # Shutdown: close the pool and any other resources opened above.


def create_app() -> FastAPI:
    """Build the FastAPI application. Factory form keeps tests free to construct fresh apps."""
    app = FastAPI(title="ai-gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
