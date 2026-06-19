# Decisions

Architectural decisions and their rationale. Append, don't rewrite. Each entry records *why* and — because the design optimizes for legibility and changeability — *what it costs to reverse*. This is the source of truth for "why did you choose X over Y" questions.

---

### D1 — Ports-and-adapters (hexagonal), not technical layering
A gateway's entire job is adapting one client interface to many swappable backends, which is exactly what hexagonal is for. Organize around the ports (the real seams), not group-by-type folders. The C#/.NET prototype's technical layering is *not* carried over — only its thinking (dependency inversion, swappable backends, testable core) is.
**Cost to reverse:** high, but unlikely to need to — this is the structural backbone everything else hangs off.

### D2 — PostgreSQL 18 + pgvector
Postgres has **no LTS track**; every major is supported 5 years from its release, so the latest major (18) has the longest remaining runway *and* is mature by mid-2026. pgvector publishes maintained images through pg18. Keeping Postgres+pgvector (rather than a separate vector DB) keeps the stack small and defensible at this scale.
**Cost to reverse:** minor version bumps (`18.x`) are seamless. A *major* downgrade/upgrade changes the on-disk format (needs `pg_upgrade` or dump/restore) — but the store is a disposable cache, so `docker compose down -v` and recreate is fine. Moving off pgvector entirely (to a dedicated vector store at large scale) is an **adapter swap behind `CacheRepository`**, not a rewrite — see the scaling note below.

### D3 — HNSW (cosine) as the default vector index
Preferred over ivfflat because it builds without pre-existing data and, crucially for a high-churn TTL **cache**, absorbs incremental inserts without the centroid drift that forces periodic ivfflat rebuilds. Created with `vector_cosine_ops` to match the `<=>` cosine operator and the `similarity = 1 - distance` convention.
**Cost to reverse:** trivial — `DROP INDEX` + `CREATE INDEX ... USING ivfflat (...)`. No app code, schema, or data change; the query operator is identical for both. At MVP scale you can even run with no index (exact scan, 100% recall) and add one when scans get slow. (ivfflat is the .NET prototype's choice if parity is ever wanted.)

### D4 — Python 3.13 pinned
Pinned one minor *behind* the newest deliberately, for maximum wheel coverage across `fastembed`/`psycopg` — the "runs for everyone" goal. For an I/O-bound async gateway the interpreter minor version barely affects throughput, so this is not a performance decision.
**Cost to reverse:** trivial — one line in `.python-version` / `requires-python`, then rerun tests; uv fetches the interpreter.

### D5 — Raw SQL via psycopg 3 + a thin repository, no ORM
The pgvector similarity query is custom SQL; a thin repository is cleaner and faster than fighting an ORM over vector ops. SQLAlchemy 2.0 async is the fallback if ORM familiarity is ever wanted.
**Cost to reverse:** localized to `adapters/repository.py` behind the `CacheRepository` port; service layer is unaffected.

---

### What actually governs scaling (read before changing any pin above)
None of the version/index pins above is the scaling lever. Two things are:
1. **Async, I/O-bound design** — the gateway waits on LLM APIs and the DB, so throughput comes from async + connection pooling + horizontal replicas behind a load balancer, not from the Postgres/Python version.
2. **The ports** — `EmbeddingProvider`, `CacheRepository` (→ vector store), and `ModelBackend` are the seams that let the heavy pieces be swapped (local→hosted embeddings, pgvector→dedicated vector DB, one→many providers) without touching service logic.

So the pins are leaf-level and reversible; the future-flexibility lives in the architecture, which is already fixed. Don't churn the pins under pressure.

---

### D6 — `src/` layout + hatchling build backend
The package lives under `src/gateway/` (not top-level `gateway/`) so tests run against the *installed* package, never accidentally against the source tree on `sys.path` — the standard guard against "passes locally, breaks on install." `hatchling` is the build backend: PEP 621-native, zero extra config beyond naming the wheel package, and widely understood (legibility goal). `uv` drives it; `pythonpath = ["src"]` in pytest keeps the dev loop fast without an editable-install step in every shell.
**Cost to reverse:** trivial — swap the `[build-system]` table; no app code changes.

### D7 — Five Protocols, only at the swap seams
`domain/ports.py` defines exactly five `Protocol`s — `EmbeddingProvider`, `CacheRepository`, `ModelBackend`, `ModelRouter`, `ComplexityClassifier` — one per place a component is genuinely meant to be swapped. They are `runtime_checkable` so tests can assert fakes fit structurally. Concrete impls neither import nor inherit them (structural typing), which is the deliberate anti-pattern to the C# "interface-per-class" tell. `BillingService`/`QualityChecker` (NoOp) from CLAUDE.md are **deferred, not dropped** — they'll be added in the same commit as the service that first consumes them, so a port never lands without a caller.
**Cost to reverse:** adding/removing a seam is localized to `ports.py` + that adapter; the service layer depends on the Protocol, not the concrete type.

### D8 — Harness-first: skeleton with typed stubs, no behavior
This slice builds only the wiring — composition root, config, routes, ports, and typed stubs whose bodies `raise NotImplementedError` — plus the toolchain, tests, CI, and the in-session quality hook. The single live path is `GET /health`. Rationale: prove the architecture and the `mypy --strict` + ruff + pytest gates end-to-end *before* any logic exists, so every subsequent slice (semantic cache → pipeline → intent caching) lands on a green, type-checked floor.
**Cost to reverse:** n/a — this is the starting point; later slices fill the stubs in place behind the existing seams.
