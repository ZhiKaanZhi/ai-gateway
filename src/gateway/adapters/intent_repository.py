"""pgvector intent repository — implements :class:`IntentRepository`.

Mirrors the pattern of :mod:`gateway.adapters.repository`: raw SQL confined here, Vector() wrapping
at bind boundaries, HNSW cosine index, pool opened by the lifespan. The difference is the search
key: stripped (canonical) prompt embeddings, not full-prompt embeddings, so #1111 and #2222 collapse
to the same candidate (D24). The ``parameters`` column persists what was in the prompt at admission
so the gate's binding check can read it back at serve time (D25, D27).
"""

from __future__ import annotations

from pgvector import Vector
from psycopg_pool import AsyncConnectionPool

from gateway.domain.models import Embedding, IntentCandidate, IntentEntry

# Ranked candidates within the cosine threshold, including age (seconds since stored) and the
# parameters column the gate's binding check reads. LIMIT is passed at query time.
_SEARCH_SQL = """
    SELECT
        response,
        model_used,
        1 - (embedding <=> %s) AS similarity,
        EXTRACT(EPOCH FROM (now() - created_at)) AS age_seconds,
        parameters
    FROM intent_entries
    WHERE 1 - (embedding <=> %s) >= %s
    ORDER BY embedding <=> %s
    LIMIT %s
"""

_STORE_SQL = """
    INSERT INTO intent_entries
        (id, canonical_prompt, response, model_used, embedding, parameters, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


class PgVectorIntentRepository:
    """Intent cache over Postgres + pgvector. Implements ``IntentRepository``."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def search(
        self, embedding: Embedding, threshold: float, limit: int = 5
    ) -> list[IntentCandidate]:
        """Return ranked candidates whose stripped-prompt cosine clears ``threshold``."""
        query = Vector(embedding)
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_SEARCH_SQL, (query, query, threshold, query, limit))
            rows = await cur.fetchall()
        return [
            IntentCandidate(
                response=row[0],
                model_used=row[1],
                similarity=float(row[2]),
                age_seconds=float(row[3]),
                parameters=list(row[4]) if row[4] else [],
            )
            for row in rows
        ]

    async def store(self, entry: IntentEntry) -> None:
        """Persist a canonical intent entry; the embedding binds as a parameter."""
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                _STORE_SQL,
                (
                    entry.id,
                    entry.canonical_prompt,
                    entry.response,
                    entry.model_used,
                    Vector(entry.embedding),
                    entry.parameters,
                    entry.created_at,
                ),
            )
