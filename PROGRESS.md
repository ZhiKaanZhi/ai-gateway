# Progress

Milestone log and current state for the ai-gateway build. **Thin by design — the "where we are."**
The *why* behind choices lives in `DECISIONS.md`; agent/flow failures in `FAILURES.md`; the polished, outward-facing summary in `README.md`. Don't duplicate those here.

## Current state

Slice 4 done and green: age-only TTL cleanup of `intent_entries` (D36–D42) — `IntentRepository.prune_older_than` (one self-selecting `DELETE`), an in-app asyncio background timer started/cancelled in the lifespan, and a `intent_prune_interval_seconds` cadence field (the prune *age* reuses the gate's `intent_staleness_max_seconds`, D39). A failed sweep logs and retries, never crashing the app; autovacuum reclaims the dead tuples (D41). Proven by an integration test (the real DELETE predicate) and a unit test (the timer's raise-and-continue / clean-cancel safety). Builds on Slice 3's three-tier cache (exact → semantic → intent) with the value-mismatch Verifier gate (D32–D34). `ruff`, `mypy --strict`, and the full suite pass. Per-customer erasure stays deferred (D36); next is the F6 action-intent execution seam.

## Milestones

- [x] **2026-06-19 — Bootstrap.** CLAUDE.md, DECISIONS.md, SETUP.md, docker-compose (Postgres 18 + pgvector), `python-architecture-reviewer` agent, `pgvector-psycopg` skill.
- [x] **2026-06-19 — Harness.** pyproject (uv · Ruff · mypy --strict · pytest), `src/gateway/` skeleton, the 5 seam Protocols, `GET /health` + test, pre-commit, CI, PostToolUse hook.
- [x] **2026-06-19 — Slice 1 — Semantic cache vertical.** fastembed `EmbeddingProvider` + pgvector `CacheRepository` + `cache_service` (`CacheHit | CacheMiss`) + `/cache/lookup` & `/cache/store` + integration test (miss → store → hit across the threshold). Fixed two infra bugs en route (pgvector list-bind, PG18 volume mount) — see `FAILURES.md` F1/F2, `DECISIONS.md` D9–D13.
- [x] **2026-06-21 — Slice 2 — Pipeline skeleton + one real backend.** `RequestPipeline.process` implemented (cache → classify → route → backend → store); `OpenAICompatibleBackend` (httpx, OpenAI chat-completions contract, Ollama as dev default); `BackendError` (D17, 502/504 handler); backend config as masked `SecretStr` (D19); three offline test layers + self-skipping live round-trip (D20) — see `DECISIONS.md` D15–D20.
- [x] **2026-06-21 — Slice 3 — Intent caching** (the showpiece): three-tier cache (exact → semantic → intent), confidence gate + fallback, adversarial eval (gate → 0 false serves; cosine-only baseline → nonzero). 44 tests, `ruff`/`mypy --strict` green. See `DECISIONS.md` D21–D31, `GLOSSARY.md`, `SLICE3_PRD.md`.
- [x] **2026-06-26 — D32–D34 — Intent gate hardening (closes F5).** The Verifier now fires on a value mismatch (cached vs. incoming parameters), with the substring check demoted to reject-fast; retired the base-confidence formula and verify band; `confidence` is the Verifier's score when the model ran, else `None`. The eval gained transform-refuse + value-independent-serve cases (the verifier is now genuinely exercised), plus `evals/verify_live.py` for the real-model check. Named F6 (action-intent reuse hole) for a future slice.
- [x] **2026-06-27 — Slice 4 — Multi-customer data hygiene** (D36–D42): age-only TTL cleanup of `intent_entries` — `IntentRepository.prune_older_than` (one `DELETE`), an asyncio background timer (`prune_timer.py`, lifespan-owned), `intent_prune_interval_seconds` cadence; prune age reuses `intent_staleness_max_seconds` (D39); autovacuum reclaims dead tuples (D41); integration + timer-safety unit tests. Per-customer erasure deferred (D36). Future refinement: evict-on-bound-refuse (gate already computed the verdict).

## Next step

**Action-intent execution seam (F6).** The named, unfixed reuse hole: an action intent (cancel/delete/book) that was *executed* once must not be served from cache as if re-run — a cached "done" is not a fresh "it ran." Needs an execution port (the side-effecting call the gate currently has no concept of), a provider call behind it, and "it ran" confirmation semantics so reuse of an action answer is gated on whether the action actually fired, not just whether the text matches. The gate *logic* is settled (D32–D34); offline contrast holds (`uv run python -m evals.run_eval` → gate 0 / baseline 8).

Parked: intent verifier value-independent recall — fails safe, see D35; revisit when a real workload justifies a stronger `GATEWAY_VERIFIER_MODEL`.
