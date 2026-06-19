"""pgvector cache repository — implements :class:`CacheRepository`.

All raw SQL lives here, behind the port; it never leaks into the services. Per the
``pgvector-psycopg`` skill: the pool is opened in the lifespan (not the constructor), the ``vector``
type is registered in the pool's ``configure`` callback, vectors bind as parameters (never string
interpolation), and similarity is ``1 - (embedding <=> query)`` against an HNSW cosine index.
Stub only in the harness slice.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from gateway.domain.models import CacheEntry, CacheHit, Embedding


class PgVectorCacheRepository:
    """Vector cache over Postgres + pgvector. Implements ``CacheRepository``."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def lookup(self, embedding: Embedding, threshold: float) -> CacheHit | None:
        raise NotImplementedError

    async def store(self, entry: CacheEntry) -> None:
        raise NotImplementedError
