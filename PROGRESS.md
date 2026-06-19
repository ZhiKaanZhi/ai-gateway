# Progress

Milestone log and current state for the ai-gateway build. **Thin by design — the "where we are."**
The *why* behind choices lives in `DECISIONS.md`; agent/flow failures in `FAILURES.md`; the polished, outward-facing summary in `README.md`. Don't duplicate those here.

## Current state

Slice 1 done and green: the semantic-cache vertical is live end-to-end — fastembed `EmbeddingProvider`, pgvector `CacheRepository`, `CacheService`, and `POST /cache/lookup` + `/cache/store`, wired in the lifespan. Classifier / router / backends remain typed stubs. Gates (Ruff, `mypy --strict`, pytest incl. a DB integration test) pass.

## Milestones

- [x] **2026-06-19 — Bootstrap.** CLAUDE.md, DECISIONS.md, SETUP.md, docker-compose (Postgres 18 + pgvector), `python-architecture-reviewer` agent, `pgvector-psycopg` skill.
- [x] **2026-06-19 — Harness.** pyproject (uv · Ruff · mypy --strict · pytest), `src/gateway/` skeleton, the 5 seam Protocols, `GET /health` + test, pre-commit, CI, PostToolUse hook.
- [x] **2026-06-19 — Slice 1 — Semantic cache vertical.** fastembed `EmbeddingProvider` + pgvector `CacheRepository` + `cache_service` (`CacheHit | CacheMiss`) + `/cache/lookup` & `/cache/store` + integration test (miss → store → hit across the threshold). Fixed two infra bugs en route (pgvector list-bind, PG18 volume mount) — see `FAILURES.md` F1/F2, `DECISIONS.md` D9–D13.
- [ ] **Slice 2 — Pipeline skeleton** wired end-to-end + one real `ModelBackend`.  ← **NEXT**
- [ ] **Slice 3 — Intent caching** (the showpiece): confidence gate + fallback to the normal pipeline.

## Next step

Slice 2 — the request-pipeline skeleton end-to-end plus one real `ModelBackend`.
