"""Composition root — the one place singletons are built and wired.

The FastAPI ``lifespan`` is where long-lived resources (the psycopg ``AsyncConnectionPool``, the
fastembed model, the cache service) are constructed on startup and torn down on shutdown, then
handed to handlers via ``app.state`` / ``Depends``. No DI framework: plain construction here is the
whole mechanism.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gateway.adapters.embeddings import FastembedEmbeddingProvider
from gateway.adapters.repository import PgVectorCacheRepository, create_cache_pool
from gateway.api.routes import router
from gateway.config import get_settings
from gateway.services.cache_service import CacheService

# Note (Windows): psycopg async can't run on the default ProactorEventLoop. The event-loop policy
# must be set *before* the server builds its loop, which is too early for this module — see
# `gateway.__main__` (the `python -m gateway` launcher) and the conftest fixture for tests.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build singletons on startup, release them on shutdown."""
    settings = get_settings()
    # Load the embedding model once (expensive) and open the pool per the pgvector skill.
    embeddings = FastembedEmbeddingProvider(settings.embedding_model)
    pool = create_cache_pool(settings.conninfo)
    await pool.open()
    repository = PgVectorCacheRepository(pool)
    app.state.cache_service = CacheService(
        embeddings, repository, threshold=settings.semantic_threshold
    )
    try:
        yield
    finally:
        await pool.close()


def create_app() -> FastAPI:
    """Build the FastAPI application. Factory form keeps tests free to construct fresh apps."""
    app = FastAPI(title="ai-gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
