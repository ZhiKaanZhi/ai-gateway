# Progress

Milestone log and current state for the ai-gateway build. **Thin by design — the "where we are."**
The *why* behind choices lives in `DECISIONS.md`; agent/flow failures in `FAILURES.md`; the polished, outward-facing summary in `README.md`. Don't duplicate those here.

## Current state

Slice 2 done and green: `POST /v1/chat` runs the full cache-aside pipeline — cache hit returns without a model call; on a miss, the request is classified, routed, served by `OpenAICompatibleBackend` (httpx, Ollama-compatible), and the result is stored reusing the miss's embedding. Classifier returns a constant tier; router does a genuine one-row table lookup. All three gates (Ruff, `mypy --strict`, 21 tests) pass. Intent caching (the showpiece) is Slice 3.

## Milestones

- [x] **2026-06-19 — Bootstrap.** CLAUDE.md, DECISIONS.md, SETUP.md, docker-compose (Postgres 18 + pgvector), `python-architecture-reviewer` agent, `pgvector-psycopg` skill.
- [x] **2026-06-19 — Harness.** pyproject (uv · Ruff · mypy --strict · pytest), `src/gateway/` skeleton, the 5 seam Protocols, `GET /health` + test, pre-commit, CI, PostToolUse hook.
- [x] **2026-06-19 — Slice 1 — Semantic cache vertical.** fastembed `EmbeddingProvider` + pgvector `CacheRepository` + `cache_service` (`CacheHit | CacheMiss`) + `/cache/lookup` & `/cache/store` + integration test (miss → store → hit across the threshold). Fixed two infra bugs en route (pgvector list-bind, PG18 volume mount) — see `FAILURES.md` F1/F2, `DECISIONS.md` D9–D13.
- [x] **2026-06-21 — Slice 2 — Pipeline skeleton + one real backend.** `RequestPipeline.process` implemented (cache → classify → route → backend → store); `OpenAICompatibleBackend` (httpx, OpenAI chat-completions contract, Ollama as dev default); `BackendError` (D17, 502/504 handler); backend config as masked `SecretStr` (D19); three offline test layers + self-skipping live round-trip (D20) — see `DECISIONS.md` D15–D20.
- [ ] **Slice 3 — Intent caching** (the showpiece): confidence gate + fallback to the normal pipeline.  ← **NEXT**

## Next step

Slice 3 — intent caching: three-tier cache (exact → semantic → intent), confidence scoring, and fallback design. The interview story.
