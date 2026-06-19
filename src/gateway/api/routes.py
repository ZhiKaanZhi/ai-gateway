"""HTTP handlers — thin. Routes translate between the wire contract and the services; they hold
no business logic of their own.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from gateway.api.schemas import (
    CacheLookupRequest,
    CacheLookupResponse,
    CacheStoreRequest,
    CacheStoreResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
)
from gateway.domain.models import CacheHit
from gateway.services.cache_service import CacheService

router = APIRouter()


def get_cache_service(request: Request) -> CacheService:
    """Hand handlers the singleton wired in the lifespan (composition root). No DI framework."""
    # app.state is typed Any by Starlette; the annotation pins the type back down for callers.
    service: CacheService = request.app.state.cache_service
    return service


CacheServiceDep = Annotated[CacheService, Depends(get_cache_service)]


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness probe. Returns ``{"status": "ok"}`` once the app has started."""
    return HealthResponse()


@router.post("/cache/lookup")
async def cache_lookup(request: CacheLookupRequest, cache: CacheServiceDep) -> CacheLookupResponse:
    """Return a cached answer if a stored prompt clears the similarity gate, else a miss."""
    result = await cache.lookup(request.prompt)
    if isinstance(result, CacheHit):
        return CacheLookupResponse(
            hit=True,
            response=result.response,
            model_used=result.model_used,
            similarity=result.similarity,
        )
    return CacheLookupResponse(hit=False)


@router.post("/cache/store")
async def cache_store(request: CacheStoreRequest, cache: CacheServiceDep) -> CacheStoreResponse:
    """Persist a prompt/response pair for future lookups."""
    await cache.store(request.prompt, request.response, request.model_used)
    return CacheStoreResponse()


@router.post("/v1/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Serve a prompt through the cache/route pipeline.

    Stub: the request pipeline is not implemented in this slice, so this honestly
    answers 501 rather than declaring a contract it does not yet fulfil.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="not implemented")
