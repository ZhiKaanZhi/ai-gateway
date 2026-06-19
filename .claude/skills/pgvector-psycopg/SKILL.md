---
name: pgvector-psycopg
description: Use whenever writing or reviewing psycopg 3 + pgvector code in this project — vector columns, similarity / nearest-neighbour queries, the async connection pool, vector type registration, or index choice (ivfflat vs hnsw). Apply this even when the task only touches the repository/database layer and doesn't say "pgvector" explicitly.
---

# pgvector with psycopg 3 (async)

This is the small set of things that are easy to get wrong and silently break vector storage or search. It is not a psycopg tutorial — it is the gotchas. Append new failures to **Gotchas grows** at the bottom as they surface.

## The non-obvious rules

1. **Register the `vector` type on every connection, or vectors round-trip wrong.** Without registration you get type errors or vectors coming back as strings.
   - sync: `from pgvector.psycopg import register_vector; register_vector(conn)`
   - async: `from pgvector.psycopg import register_vector_async; await register_vector_async(conn)`

2. **With a pool, register in the pool's `configure` callback** so it runs once per pooled connection — not per query. For the async pool the callback is itself async.

3. **Open the async pool in the FastAPI `lifespan`, not in the constructor.** Constructor-opening is deprecated; pass `open=False` and call `await pool.open()` / `await pool.close()`. Never open/close a pool per request.

4. **Pass vectors as parameters — never string-format them into SQL.** With the type registered, a `list[float]` or numpy array binds to `vector` directly. String interpolation is both wrong and an injection footgun.

5. **Distance operators** (this project uses **cosine**):
   - `<=>` cosine distance · `<->` L2 · `<#>` negative inner product.
   - Convention here: `similarity = 1 - (embedding <=> query)`. For nearest neighbours, `ORDER BY embedding <=> query ASC LIMIT k`.

6. **Dimension must match the model.** Column is `vector(384)` for all-MiniLM-L6-v2 / bge-small-en-v1.5. A mismatch fails on insert.

7. **Enable the extension once, before any `vector` column exists:** `CREATE EXTENSION IF NOT EXISTS vector;` (here: `db/init.sql`).

8. **Index choice — pick deliberately:**
   - **hnsw** — better recall/latency, builds without pre-existing data, but uses more memory and builds slower. **Preferred for this MVP** (fewer footguns). Create with the cosine opclass: `USING hnsw (embedding vector_cosine_ops)`.
   - **ivfflat** — must be built *after* data exists, needs a tuned `lists`, set `ivfflat.probes` at query time, and run `ANALYZE`. This is what the .NET prototype used; only use it if you want parity.
   - The index opclass must match the query operator (`vector_cosine_ops` ↔ `<=>`).
   - **Docker build gotcha:** parallel HNSW index builds use shared memory; if a build errors on a larger dataset, raise the container's `shm_size` to at least `maintenance_work_mem`.

9. **Windows:** psycopg async is incompatible with the default ProactorEventLoop. Under uvicorn it's fine; if running asyncio directly, set `WindowsSelectorEventLoopPolicy`.

## Reference pattern (pool + lifespan + nearest-neighbour)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool
from pgvector.psycopg import register_vector_async

async def _configure(conn):
    await register_vector_async(conn)

pool = AsyncConnectionPool(CONNINFO, open=False, configure=_configure)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    yield
    await pool.close()

app = FastAPI(lifespan=lifespan)

async def find_nearest(query_vec: list[float], threshold: float):
    sql = """
        SELECT id, response_text, model_used,
               1 - (embedding <=> %s) AS similarity
        FROM cache_entries
        ORDER BY embedding <=> %s
        LIMIT 1
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, (query_vec, query_vec))
            row = await cur.fetchone()
    if row is None or row[3] < threshold:
        return None          # miss
    return row               # hit
```

Wrap this behind the `CacheRepository` Protocol in `adapters/repository.py`; do not let raw SQL leak into `services/`.

## Gotchas grows

- _(append real failures here as the build surfaces them — feeds `FAILURES.md`)_
