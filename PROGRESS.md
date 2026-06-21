# Progress

Milestone log and current state for the ai-gateway build. **Thin by design — the "where we are."**
The *why* behind choices lives in `DECISIONS.md`; agent/flow failures in `FAILURES.md`; the polished, outward-facing summary in `README.md`. Don't duplicate those here.

## Current state

Slice 3 done and green: three-tier cache (exact → semantic → intent) with a confidence gate fully implemented. The gate produces 0 false serves on the adversarial eval set; `ruff`, `mypy --strict`, and 44 tests pass. Next is Slice 4 (multi-customer data hygiene, D31).

## Milestones

- [x] **2026-06-19 — Bootstrap.** CLAUDE.md, DECISIONS.md, SETUP.md, docker-compose (Postgres 18 + pgvector), `python-architecture-reviewer` agent, `pgvector-psycopg` skill.
- [x] **2026-06-19 — Harness.** pyproject (uv · Ruff · mypy --strict · pytest), `src/gateway/` skeleton, the 5 seam Protocols, `GET /health` + test, pre-commit, CI, PostToolUse hook.
- [x] **2026-06-19 — Slice 1 — Semantic cache vertical.** fastembed `EmbeddingProvider` + pgvector `CacheRepository` + `cache_service` (`CacheHit | CacheMiss`) + `/cache/lookup` & `/cache/store` + integration test (miss → store → hit across the threshold). Fixed two infra bugs en route (pgvector list-bind, PG18 volume mount) — see `FAILURES.md` F1/F2, `DECISIONS.md` D9–D13.
- [x] **2026-06-21 — Slice 2 — Pipeline skeleton + one real backend.** `RequestPipeline.process` implemented (cache → classify → route → backend → store); `OpenAICompatibleBackend` (httpx, OpenAI chat-completions contract, Ollama as dev default); `BackendError` (D17, 502/504 handler); backend config as masked `SecretStr` (D19); three offline test layers + self-skipping live round-trip (D20) — see `DECISIONS.md` D15–D20.
- [x] **2026-06-21 — Slice 3 — Intent caching** (the showpiece): three-tier cache (exact → semantic → intent), confidence gate + fallback, adversarial eval (gate → 0 false serves; cosine-only baseline → nonzero). 44 tests, `ruff`/`mypy --strict` green. See `DECISIONS.md` D21–D31, `GLOSSARY.md`, `SLICE3_PRD.md`.
- [ ] **Slice 4 — Multi-customer data hygiene** (committed next slice, D31): delete-old-entries behind `IntentRepository`, background timer, TTL setting. Future refinement: evict-on-bound-refuse (gate already computed the verdict).

## Next step

Slice 3 is active. Eval deliverable: *cosine-only → N false serves; gate → 0*.
