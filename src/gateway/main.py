"""Composition root — the one place singletons are built and wired.

The FastAPI ``lifespan`` is where long-lived resources (the psycopg ``AsyncConnectionPool``, the
fastembed model, the httpx client, the request pipeline) are constructed on startup and torn down
on shutdown, then handed to handlers via ``app.state`` / ``Depends``. No DI framework: plain
construction here is the whole mechanism.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gateway.adapters.backends.openai_compat import OpenAICompatibleBackend
from gateway.adapters.embeddings import FastembedEmbeddingProvider
from gateway.adapters.intent_repository import PgVectorIntentRepository
from gateway.adapters.repository import PgVectorCacheRepository, create_cache_pool
from gateway.adapters.verifier import ModelVerifier
from gateway.api.routes import router
from gateway.config import get_settings
from gateway.domain.errors import BackendError
from gateway.domain.models import Complexity
from gateway.services.cache_service import CacheService
from gateway.services.classifier import HeuristicClassifier
from gateway.services.intent_extractor import RegexIntentExtractor
from gateway.services.intent_gate import IntentGate
from gateway.services.pipeline import RequestPipeline
from gateway.services.prune_timer import run_prune_loop
from gateway.services.router import CostAwareRouter

# Note (Windows): psycopg async can't run on the default ProactorEventLoop. The event-loop policy
# must be set *before* the server builds its loop, which is too early for this module — see
# `gateway.__main__` (the `python -m gateway` launcher) and the conftest fixture for tests.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build singletons on startup, release them on shutdown."""
    settings = get_settings()

    # --- Embeddings (shared: used by both the semantic cache and the intent tier) ---
    embeddings = FastembedEmbeddingProvider(settings.embedding_model)

    # --- Shared vector pool (one pool, both tables: cache_entries + intent_entries) ---
    # The two stores live in the same database and share the vector-type registration, so a single
    # pool serves both — the separation that matters is the repository seam, not the connection.
    pool = create_cache_pool(settings.conninfo)
    await pool.open()

    # --- Semantic cache ---
    repository = PgVectorCacheRepository(pool)
    cache_service = CacheService(embeddings, repository, threshold=settings.semantic_threshold)
    app.state.cache_service = cache_service

    # --- Intent store (same pool, different table) ---
    intent_repository = PgVectorIntentRepository(pool)

    # --- Intent extractor (stateless, no I/O) ---
    extractor = RegexIntentExtractor()

    # --- Verifier (cheap model call via a separate httpx client) ---
    verifier_client = httpx.AsyncClient(
        base_url=settings.verifier_base_url,
        timeout=settings.verifier_timeout,
    )
    verifier_key = settings.verifier_api_key.get_secret_value() or None
    verifier = ModelVerifier(verifier_client, settings.verifier_model, verifier_key)

    # --- Intent gate ---
    intent_gate = IntentGate(
        verifier,
        margin_min=settings.intent_margin_min,
        staleness_max_seconds=settings.intent_staleness_max_seconds,
        verify_pass_threshold=settings.intent_verify_pass_threshold,
    )

    # --- Backend (httpx client owned here; aclose()d on shutdown) ---
    client = httpx.AsyncClient(
        base_url=settings.backend_base_url,
        timeout=settings.backend_timeout,
    )
    key = settings.backend_api_key.get_secret_value() or None
    backend = OpenAICompatibleBackend(client, settings.backend_model, key)

    # --- Classifier + router (every Complexity tier → the one backend, D18) ---
    classifier = HeuristicClassifier()
    router_ = CostAwareRouter({c: backend for c in Complexity})

    # --- Pipeline on app.state so routes can reach it ---
    app.state.pipeline = RequestPipeline(
        cache_service,
        classifier,
        router_,
        embeddings,
        extractor,
        intent_repository,
        intent_gate,
        settings.intent_match_threshold,
    )

    # --- Background prune timer: age-only TTL cleanup of intent_entries (D37, D40) ---
    # Started last, immediately before the guarded block, so the finally below always tears it down.
    # The age reuses the gate's staleness setting (D39); the cadence is its own config field (D40).
    prune_task = asyncio.create_task(
        run_prune_loop(
            intent_repository,
            interval_seconds=settings.intent_prune_interval_seconds,
            max_age_seconds=settings.intent_staleness_max_seconds,
        )
    )

    try:
        yield
    finally:
        # Stop the prune timer before closing the pool it borrows connections from. cancel() only
        # requests; awaiting it lets an in-flight sweep unwind cleanly (D40).
        prune_task.cancel()
        with suppress(asyncio.CancelledError):
            await prune_task
        await client.aclose()
        await verifier_client.aclose()
        await pool.close()


async def _on_backend_error(request: Request, exc: Exception) -> JSONResponse:
    """Map BackendError to 504 (timeout) or 502 (any other backend failure)."""
    # Starlette types the handler's second arg as Exception; narrow back for mypy --strict.
    assert isinstance(exc, BackendError)
    status_code = 504 if exc.is_timeout else 502
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


def create_app() -> FastAPI:
    """Build the FastAPI application. Factory form keeps tests free to construct fresh apps."""
    app = FastAPI(title="ai-gateway", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.add_exception_handler(BackendError, _on_backend_error)
    return app


app = create_app()
