"""HTTP handlers — thin. Routes translate between the wire contract and the services; they hold
no business logic of their own.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from gateway.api.schemas import ChatRequest, ChatResponse, HealthResponse

router = APIRouter()


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness probe. Returns ``{"status": "ok"}`` once the app has started."""
    return HealthResponse()


@router.post("/v1/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Serve a prompt through the cache/route pipeline.

    Stub: the request pipeline is not implemented in the harness slice, so this honestly
    answers 501 rather than declaring a contract it does not yet fulfil.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="not implemented")
