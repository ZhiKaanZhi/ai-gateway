"""Integration test for the intent-tier age prune against a real Postgres+pgvector.

Proves the ``WHERE created_at < now() - interval`` predicate that a fake cannot: store one backdated
row (48 h old) and one fresh row, prune at a 24 h age, and confirm exactly the stale row is gone.
Skipped automatically when no DB is reachable, so the suite stays green without one (it runs in CI's
pgvector service and against local ``docker compose``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from gateway.adapters.intent_repository import PgVectorIntentRepository
from gateway.adapters.repository import create_cache_pool
from gateway.config import get_settings
from gateway.domain.models import IntentEntry

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[AsyncConnectionPool]:
    """A real pool with a truncated ``intent_entries``; skips the test if the DB is unreachable.

    Yields the pool itself (not a repo) because the verifying SELECT below needs its own connection.
    """
    settings = get_settings()
    pool = create_cache_pool(settings.conninfo)
    try:
        await pool.open(wait=True, timeout=5.0)
    except Exception as exc:  # noqa: BLE001 — any connect failure means "no DB", so skip
        await pool.close()
        pytest.skip(f"no reachable Postgres+pgvector: {exc}")
    try:
        async with pool.connection() as conn:
            await conn.execute("TRUNCATE intent_entries")
        yield pool
    finally:
        await pool.close()


def _entry(created_at: datetime, dim: int) -> IntentEntry:
    """A minimal intent row; the embedding is irrelevant to the age prune, so use zeros."""
    return IntentEntry(
        id=uuid4(),
        canonical_prompt="what is the capital of {country}",
        response="(paris)",
        model_used="test-model",
        embedding=[0.0] * dim,
        parameters=[],
        created_at=created_at,
    )


async def test_prune_removes_stale_keeps_fresh(pool: AsyncConnectionPool) -> None:
    settings = get_settings()
    repo = PgVectorIntentRepository(pool)

    now = datetime.now(UTC)
    await repo.store(_entry(now - timedelta(hours=48), settings.embedding_dim))  # stale
    await repo.store(_entry(now, settings.embedding_dim))  # fresh

    deleted = await repo.prune_older_than(86400.0)  # 24 h
    assert deleted == 1

    # Verify the survivor by direct SELECT, not search(): both rows carry a zero embedding and
    # cosine distance on a zero vector is NaN, so search would misbehave.
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT count(*) FROM intent_entries")
        row = await cur.fetchone()
    assert row is not None and row[0] == 1
