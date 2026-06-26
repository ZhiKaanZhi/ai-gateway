# Progress

Milestone log and current state for the ai-gateway build. **Thin by design — the "where we are."**
The *why* behind choices lives in `DECISIONS.md`; agent/flow failures in `FAILURES.md`; the polished, outward-facing summary in `README.md`. Don't duplicate those here.

## Current state

Slice 3 done and green: three-tier cache (exact → semantic → intent) with a confidence gate fully implemented, then hardened post-ship (D32–D34) after a probe found the gate false-serving transforms (F5). The Verifier now fires on **value mismatch** (not the retired confidence band); the eval exercises it on transform cases and still reports 0 gate false serves vs. 8 for the cosine-only baseline. `ruff`, `mypy --strict`, and 50 tests pass. Next is Slice 4 (multi-customer data hygiene, D31; action-intent execution seam, F6).

## Milestones

- [x] **2026-06-19 — Bootstrap.** CLAUDE.md, DECISIONS.md, SETUP.md, docker-compose (Postgres 18 + pgvector), `python-architecture-reviewer` agent, `pgvector-psycopg` skill.
- [x] **2026-06-19 — Harness.** pyproject (uv · Ruff · mypy --strict · pytest), `src/gateway/` skeleton, the 5 seam Protocols, `GET /health` + test, pre-commit, CI, PostToolUse hook.
- [x] **2026-06-19 — Slice 1 — Semantic cache vertical.** fastembed `EmbeddingProvider` + pgvector `CacheRepository` + `cache_service` (`CacheHit | CacheMiss`) + `/cache/lookup` & `/cache/store` + integration test (miss → store → hit across the threshold). Fixed two infra bugs en route (pgvector list-bind, PG18 volume mount) — see `FAILURES.md` F1/F2, `DECISIONS.md` D9–D13.
- [x] **2026-06-21 — Slice 2 — Pipeline skeleton + one real backend.** `RequestPipeline.process` implemented (cache → classify → route → backend → store); `OpenAICompatibleBackend` (httpx, OpenAI chat-completions contract, Ollama as dev default); `BackendError` (D17, 502/504 handler); backend config as masked `SecretStr` (D19); three offline test layers + self-skipping live round-trip (D20) — see `DECISIONS.md` D15–D20.
- [x] **2026-06-21 — Slice 3 — Intent caching** (the showpiece): three-tier cache (exact → semantic → intent), confidence gate + fallback, adversarial eval (gate → 0 false serves; cosine-only baseline → nonzero). 44 tests, `ruff`/`mypy --strict` green. See `DECISIONS.md` D21–D31, `GLOSSARY.md`, `SLICE3_PRD.md`.
- [x] **2026-06-26 — D32–D34 — Intent gate hardening (closes F5).** The Verifier now fires on a value mismatch (cached vs. incoming parameters), with the substring check demoted to reject-fast; retired the base-confidence formula and verify band; `confidence` is the Verifier's score when the model ran, else `None`. The eval gained transform-refuse + value-independent-serve cases (the verifier is now genuinely exercised), plus `evals/verify_live.py` for the real-model check. Named F6 (action-intent reuse hole) for a future slice.
- [ ] **Slice 4 — Multi-customer data hygiene** (committed next slice, D31): delete-old-entries behind `IntentRepository`, background timer, TTL setting. Future refinement: evict-on-bound-refuse (gate already computed the verdict).

## Next step

**Open evaluation item (carry into next session):** the live-model run of `evals/verify_live.py` against `gemma3:1b` (recorded in `FAILURES.md` F5, 2026-06-26) shows the real verifier refuses transforms correctly (0.20–0.40, safe) but **under-scores the value-independent serve-wins** (0.50 / 0.30, below the 0.80 pass) — so the 1B model captures precision but not the recall win. To evaluate: re-run `uv run python evals/verify_live.py` (needs Ollama up) and decide whether to (a) use a stronger verifier model via `GATEWAY_VERIFIER_MODEL`, (b) tune the verify prompt in `src/gateway/adapters/verifier.py`, or (c) lower `intent_verify_pass_threshold` (trades recall for precision risk). The gate *logic* is settled (D32–D34); this is a model/prompt calibration question. Offline contrast still holds: `uv run python -m evals.run_eval` → gate 0 / baseline 8.

Then: Slice 4 (multi-customer data hygiene, D31) and the action-intent execution seam (F6).
