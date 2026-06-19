"""pgvector cache repository — implements :class:`CacheRepository`.

All raw SQL lives here, behind the port; it never leaks into the services. Per the
``pgvector-psycopg`` skill: the pool is opened in the lifespan (not the constructor), the ``vector``
type is registered in the pool's ``configure`` callback, vectors bind as parameters (never string
interpolation), and similarity is ``1 - (embedding <=> query)`` against an HNSW cosine index.
"""

from __future__ import annotations

from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from gateway.domain.models import CacheEntry, CacheHit, Embedding

# Nearest neighbour by cosine distance, gated by the threshold in SQL so the repository genuinely
# "reports the nearest neighbour that clears it" (the port's contract). similarity is the
# 1 - distance convention (skill rule 5). The WHERE doesn't change behaviour vs. a Python-side
# check — ORDER BY distance puts the max-similarity row first, so if it fails the gate none clears.
_LOOKUP_SQL = """
    SELECT response, model_used, 1 - (embedding <=> %s) AS similarity
    FROM cache_entries
    WHERE 1 - (embedding <=> %s) >= %s
    ORDER BY embedding <=> %s
    LIMIT 1
"""

_STORE_SQL = """
    INSERT INTO cache_entries (id, prompt, response, model_used, embedding, created_at)
    VALUES (%s, %s, %s, %s, %s, %s)
"""


async def _configure(conn: AsyncConnection) -> None:
    """Pool ``configure`` hook: register ``vector`` once per pooled connection (skill rule 2)."""
    await register_vector_async(conn)


def create_cache_pool(conninfo: str) -> AsyncConnectionPool:
    """Build the cache's async pool, unopened.

    ``open=False`` per the skill: the caller (the lifespan, or a test) owns ``open()``/``close()``.
    """
    return AsyncConnectionPool(conninfo, open=False, configure=_configure)


class PgVectorCacheRepository:
    """Vector cache over Postgres + pgvector. Implements ``CacheRepository``."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def lookup(self, embedding: Embedding, threshold: float) -> CacheHit | None:
        """Return the nearest neighbour if it clears ``threshold``, else ``None`` (a miss)."""
        # pgvector's psycopg dumper covers Vector / numpy only, not plain list — wrap at the bind
        # boundary so a list[float] doesn't fall through to psycopg's `double precision[]` dumper.
        query = Vector(embedding)
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_LOOKUP_SQL, (query, query, threshold, query))
            row = await cur.fetchone()
        if row is None:
            return None  # nothing cleared the gate → a miss
        response, model_used, similarity = row
        return CacheHit(response=response, model_used=model_used, similarity=similarity)

    async def store(self, entry: CacheEntry) -> None:
        """Persist a cache entry; the embedding binds as a parameter (never interpolated)."""
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                _STORE_SQL,
                (
                    entry.id,
                    entry.prompt,
                    entry.response,
                    entry.model_used,
                    Vector(entry.embedding),
                    entry.created_at,
                ),
            )
