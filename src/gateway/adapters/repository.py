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

# Exact lookup: prompt_hash is UNIQUE so this is a point-query — no ordering or limit needed.
_EXACT_LOOKUP_SQL = """
    SELECT response, model_used
    FROM cache_entries
    WHERE prompt_hash = %s
"""

# Upsert: ON CONFLICT on prompt_hash collapses identical normalized prompts (D21).
# Refreshing created_at on conflict keeps the entry "fresh" and avoids stale exact hits.
_STORE_SQL = """
    INSERT INTO cache_entries (id, prompt, prompt_hash, response, model_used, embedding, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (prompt_hash)
    DO UPDATE SET
        response   = EXCLUDED.response,
        model_used = EXCLUDED.model_used,
        created_at = EXCLUDED.created_at
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

    async def exact_lookup(self, prompt_hash: str) -> CacheHit | None:
        """Return the stored entry for this normalized-prompt hash, or ``None``."""
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_EXACT_LOOKUP_SQL, (prompt_hash,))
            row = await cur.fetchone()
        if row is None:
            return None
        response, model_used = row
        # Exact hits have similarity = 1.0 by definition (same normalized string).
        return CacheHit(response=response, model_used=model_used, similarity=1.0)

    async def store(self, entry: CacheEntry) -> None:
        """Upsert a cache entry; the embedding binds as a parameter (never interpolated)."""
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                _STORE_SQL,
                (
                    entry.id,
                    entry.prompt,
                    entry.prompt_hash,
                    entry.response,
                    entry.model_used,
                    Vector(entry.embedding),
                    entry.created_at,
                ),
            )
