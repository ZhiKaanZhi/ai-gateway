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

---

## Slice 1 — Semantic cache vertical

### D9 — `cache_entries` schema; the app supplies `id` + `created_at`
One row per cached prompt/response: `id uuid PK`, `prompt text`, `response text`, `model_used text`, `embedding vector(384)`, `created_at timestamptz`. The column defaults (`gen_random_uuid()`, `now()`) exist for ad-hoc SQL, but the application sets `id` and `created_at` explicitly in `cache_service.store` — because `CacheEntry` (the domain model crossing the `CacheRepository` port) requires both as non-optional, and generating them app-side avoids an `INSERT … RETURNING` round-trip just to learn values we already hold. `vector(384)` matches the embedding model (D11); a dimension mismatch fails on insert.
**Cost to reverse:** the store is a disposable cache — `docker compose down -v` and recreate. Adding/changing a column is localized to `db/init.sql` + the two SQL statements in `adapters/repository.py`.

### D10 — Semantic similarity threshold default `0.95`
`similarity = 1 - (embedding <=> query)` (cosine); a hit must clear `GATEWAY_SEMANTIC_THRESHOLD`, default `0.95`. The gate lives at the call site (the service passes `threshold` into `CacheRepository.lookup`, per `ports.py`), not baked into SQL — so tuning it never touches the repository. `0.95` is deliberately tight for a *text-answer* cache: a near-paraphrase clears it, but a merely-related prompt does not, keeping false-positive cache hits rare. ~~The intent tier (Slice 3) will gate harder still (`0.97`), because a false positive there fires a *wrong tool call*.~~ **Superseded by D26:** the intent tier's serve decision is not a higher cosine threshold — it is a *confidence verdict* (correctness, not distance). See D26 for the full treatment.
**Cost to reverse:** trivial — one env var; no code or schema change.

### D11 — Embedding model `BAAI/bge-small-en-v1.5` (kept over all-MiniLM-L6-v2)
Slice 1 was specced against `all-MiniLM-L6-v2`, but both it and the existing config default (`bge-small-en-v1.5`) are 384-dim, fastembed/ONNX, CPU-only, and interchangeable at the `vector(384)` schema — so there was no schema reason to switch. Kept the standing config default to avoid churn; bge-small also tends to edge MiniLM on retrieval benchmarks, which suits a semantic cache. The model is config-driven (`GATEWAY_EMBEDDING_MODEL`), loaded **once** in the lifespan (never per request), and called off the event loop via `anyio.to_thread.run_sync` (fastembed is synchronous).
**Cost to reverse:** swap one env var — *provided* the replacement is also 384-dim. A different dimension means changing `vector(N)` and re-embedding the cache (which, being disposable, just means dropping it).

### D12 — `CacheService.lookup` returns `CacheHit | CacheMiss`, not `CacheHit | None`
The miss case carries the embedding the service just computed (`CacheMiss(embedding=...)`), so a follow-up `store` can reuse it instead of embedding the same prompt twice — the lookup-then-store flow the pipeline will run in Slice 2. A bare `None` can't carry that. The **ports are unchanged**: `CacheRepository.lookup` still returns `CacheHit | None` (the repository only reports the nearest neighbour clearing the gate); this richer shape is purely service-level, where we're free to evolve from the stub. `CacheMiss` is a frozen dataclass (not Pydantic) so the 384-float vector isn't re-validated on every miss, and it never crosses the API boundary — the route maps it to `{"hit": false}`.
**Cost to reverse:** localized to `cache_service.py` + its callers (the two routes); the ports and adapters are untouched.

### D13 — `docker-compose.yml` volume mounts `/var/lib/postgresql` (not `…/data`) for PG18
PG18 images store data in a major-version subdirectory and expect the volume at `/var/lib/postgresql`; the pre-18 `…/data` mount makes the container exit on start (docker-library/postgres#1259). Corrected during Slice 1 — see `FAILURES.md` F2. The HNSW index choice itself is unchanged (D3).
**Cost to reverse:** trivial — one line in compose; recreate the disposable volume.

### D14 — Similarity ranking stays in SQL, not the service
The nearest-neighbour search **and** its threshold gate live in the `lookup` query (`ORDER BY embedding <=> %s … WHERE 1 - (embedding <=> %s) >= %s`), not in the service. This is not business logic leaking into SQL — it *is* the search operation, and it's the only place that can use the HNSW index. Pulling ranking app-side would force loading every row and a full-table scan in Python, discarding the index that is the whole point of pgvector. The real layer boundary isn't "ranking vs. orchestration", it's the `CacheRepository` port: all raw SQL is confined to `adapters/repository.py`, so the service depends on the port, not the query, and the entire vector store is swappable (pgvector → a dedicated vector DB) without the service knowing. The service still owns the *policy* — it passes the `threshold` and decides what a hit/miss means downstream (D12); the repository owns the *mechanism*.
**Cost to reverse:** n/a — this is the architecture, not a tunable. Changing the store is an adapter swap behind the port (see D2's scaling note).

---

## Slice 2 — Pipeline skeleton + one real backend

### D15 — The pipeline returns a new `ServedCompletion`, not a `CompletionResult`
`RequestPipeline.process` returns `ServedCompletion{text, model, cached: bool, similarity: float | None}`; the route maps it to `ChatResponse`. `ChatResponse` needs `cached` + `similarity`, but a `ModelBackend` has no concept of caching, so that metadata must not touch `CompletionResult` or the `ModelBackend` port — the same separation move as D12 (caching is the *service's* concern, not the backend's). The ports and `CompletionRequest`/`CompletionResult` are unchanged.
**Cost to reverse:** trivial — localized to `domain/models.py`, `services/pipeline.py`, and the one route; nothing else depends on the shape.

### D16 — Real backend `OpenAICompatibleBackend` over httpx; Ollama is the free dev default
`adapters/backends/openai_compat.py` implements `ModelBackend` against the OpenAI chat-completions contract. **All `httpx` is confined to this adapter** — the pipeline and routes never import it (the same confinement rule as raw SQL behind the repository, D14). It is named for the *contract*, not the provider, so Groq/OpenAI later is a base-URL + key change, not a new adapter. The `httpx.AsyncClient` is owned by the composition root: built in the `main.py` lifespan with the configured `base_url` + timeout, injected into the backend, and `aclose()`d on shutdown (mirroring the psycopg pool's open/close). The dev target is local Ollama's OpenAI-compatible endpoint — free, no key.
**Cost to reverse:** low — a new provider is config (base URL + key + model); a different *contract* is a new adapter behind the unchanged `ModelBackend` port.

### D17 — Backend failure contract: explicit timeout, no retries, `BackendError`, best-effort store
(1) The timeout is explicit and configurable (`GATEWAY_BACKEND_TIMEOUT`), never httpx's implicit default. (2) No retries this slice. (3) The adapter raises a domain `BackendError(is_timeout: bool)` (in `domain/errors.py`) on a transport error/timeout, a non-2xx response, or a malformed body (no `choices`); `httpx` never escapes the adapter. One FastAPI exception handler in `create_app` maps `BackendError` → 504 when `is_timeout` else 502 (Starlette types the handler arg as `Exception`; it's narrowed back to `BackendError` so `mypy --strict` passes). (4) A cache **store** failure *after* a successful generation is logged and swallowed — best-effort cache-aside write, the caller still gets their answer; a cache **lookup** failure still propagates. (5) Non-streaming only (`stream: false`).
**Cost to reverse:** low — retries/backoff or a richer error taxonomy are additive inside the adapter + handler; callers depend only on `BackendError`'s two-way split.

### D18 — Stubs stay behaviour-real: constant classifier, genuine one-row routing table
The classifier returns a constant tier (`Complexity.SIMPLE`); the router does a genuine lookup against a `Complexity -> ModelBackend` table built in the composition root with **every** tier pointing at the single backend. Adding a real tier later is one enum value + one row; an unmapped tier fails loudly (raises), never mis-routes. This keeps the seams exercised end-to-end now, so Slice 3 fills the bodies behind unchanged ports.
**Cost to reverse:** n/a — these are the stub bodies later slices replace in place behind `ComplexityClassifier` / `ModelRouter`.

### D19 — Backend config; the API key is a masked secret from day one
Four `GATEWAY_`-prefixed, `.env`-overridable settings: `backend_base_url` (default local Ollama OpenAI-compatible endpoint), `backend_model` (default `gemma3:1b` — must be `ollama pull`ed), `backend_api_key` as a masked `SecretStr` (blank default → the adapter omits the auth header), and `backend_timeout`. Masking stays on even in dev so a stray log or settings dump never leaks a live key once the endpoint points at a paid provider.
**Cost to reverse:** trivial — env vars; no code or schema change.

### D20 — Tests: three offline layers plus one self-skipping live round-trip
Offline (no DB, no model): a pipeline test over the fakes (hit serves without calling the backend; miss calls it once and stores once, reusing the miss embedding), an adapter test over `httpx.MockTransport` (canned reply maps correctly; non-2xx / timeout / malformed each raise `BackendError` with the right `is_timeout`; structural `isinstance` against `ModelBackend`), and a `/v1/chat` API test via `dependency_overrides` (hit/miss JSON; `BackendError` → 502, timeout → 504). One live round-trip mirrors the DB integration test: it talks to a running Ollama if reachable and skips cleanly otherwise. The default suite stays fully green with no DB and no model, and Ollama stays out of CI (it isn't reachable there).
**Cost to reverse:** n/a — additive test coverage.

---

## Slice 3 — Intent caching (the showpiece)

### D21 — Cached unit = text completion
The unit cached by the intent tier is the same as the other tiers: a plain text completion. Tool/action caching is explicitly out of scope. The wrong-tool-call scenario is kept only as the *motivating story* for why the gate biases to precision (a wrong cached *action* would be worse than a wrong cached sentence), but building real tool execution is a separate, much larger subsystem.
**Cost to reverse:** high — a tool-call unit is a new subsystem. Unnecessary: the precision machinery is demonstrated on text and the narrative transfers.

### D22 — Cache parameter-independent answers only (Option A)
The intent tier caches answers whose correctness does **not** depend on the parameter — return policy, refund window, integration guides. Parameters are used by the gate to **refuse** reuse, never to slot-fill. The valuable case is *expensive* recurring answers, not cheap FAQ.
**Cost to reverse:** medium — slot-filling adds a template + live-refetch path and reopens D21.

### D23 — Tier order: exact → semantic → intent, first-hit-wins
Exact and semantic short-circuit on match. **Intent short-circuits only on match + confidence-pass; otherwise it falls through to the full pipeline.** The control flow is all in `RequestPipeline.process`.
**Cost to reverse:** low — control flow in the pipeline, no stored data.

### D24 — Intent match = vector search on parameter-stripped prompts
The match key is the *canonical* (parameter-stripped) form of the prompt; the bare parameters are stored alongside the answer in `intent_entries`. This is the mechanical reason the intent tier sees "same intent" where the semantic tier saw "different prompt." Open-set (no maintained intent catalog); the "hottest intentions" emerge from what recurs.
**Cost to reverse:** medium — a closed-set classifier changes the match key + store, but stays behind the intent seam.

### D25 — Gate refuses based on whether the answer used the parameter, not on exact-parameter-match
Generic answer → reusable across parameters → serve. Parameter-bound answer (the stored answer text contains the parameter it was built from) → refuse on mismatch with the incoming request's parameters → go live. This is "Option B" from the design options.
**Cost to reverse:** low — gate-internal policy.

### D26 — Confidence = cheap signals + borderline verification (supersedes the D10 parenthetical)
Cheap signals: top1–top2 match **margin**, **staleness** of the cached entry (age), structural **binding check** (D25 — does the stored answer text contain the stored parameter?). On the *uncertain middle band*, a cheap model is asked "does this cached answer actually answer this new question?" — serve only on a precision-biased pass. **Confidence is a correctness verdict, not a distance.** This is the answer to D10's now-struck-through parenthetical: the intent tier does not use a higher cosine threshold. See also `GLOSSARY.md`.
**Cost to reverse:** low — dropping the verify step or a signal is a policy change; no schema/port impact.

### D27 — The intent tier gets its own store (`intent_entries`)
A new table separate from `cache_entries`: `canonical_prompt`, `response`, `model_used`, `embedding vector(384)`, `parameters text[]`, `created_at`. Its own HNSW cosine index. `cache_entries` is untouched. The `parameters` column is persisted at admission so the gate's binding check (D25) can read it back at serve time without re-extracting from the answer text. This store doubles as the long-TTL global "hottest intentions" store; the semantic store stays the per-deployment cache.
**Cost to reverse:** medium — schema + a repo method; disposable cache, stays behind the seam.

### D28 — Admission routes writes by extraction
Paramless answer → semantic store (`cache_entries`, as today). Parameterized → intent store **only** (stripped canonical form + parameters); the raw parameterized prompt **never** enters `cache_entries`. No write-time binding check — the read gate (D26) handles binding/staleness. This closes the cross-serve hole created by the gateless semantic tier running first.
**Cost to reverse:** low — a branch at the store call site.

### D29 — Three new ports; the gate is a service
`IntentExtractor` (prompt → canonical stripped form + parameters), `IntentRepository` (search stripped embedding → ranked candidates with age + parameters; store), `Verifier` (`verify(question, candidate_answer) -> float` — a score the gate thresholds, so D26's verify band is calibrated from the eval set and not hidden in the adapter). The gate is a *service* (like the pipeline and cache service) — it orchestrates seams, it isn't one. `EmbeddingProvider` is reused for the stripped vector. Five ports → eight; all in `domain/ports.py`.
**Cost to reverse:** low — collapsing `Verifier` back into a model call is deleting one Protocol + one adapter.

### D30 — The showpiece deliverable is a measured eval
A small adversarial labeled set: (cached entry, new query, expected serve/refuse). Score the gate as **two separate rates — false serves (dangerous) and false refuses (wasteful)**. Run the same set through a **cosine-only baseline** (serve if similarity ≥ `GATEWAY_COSINE_BASELINE_THRESHOLD`, default 0.97 — literally the D10 collapsed idea). The headline: *cosine-only → N false serves; gate → 0*. The set is also the instrument that **calibrates** the D26 thresholds.
**Cost to reverse:** n/a — test/eval asset.

### D31 — Multi-customer data hygiene is OUT this slice; cleanup is the committed next slice
Bound answers are written per D28 but never cross-served; on synthetic single-tenant data they're harmless dead weight. Cleanup (delete-old-entries behind `IntentRepository`, a background timer, a TTL setting) is **designed, not built**, and recorded in `PROGRESS.md` as the next slice. "Evict-on-bound-refuse" is noted as a future free self-clean (the gate already computed the verdict at refuse time).
**Cost to reverse:** low — TTL/eviction is a column + sweep; per-tenant scoping is larger but stays behind the `IntentRepository` seam.

### D32 — Verifier fires on parameter mismatch, not a confidence band; substring check demoted to reject-fast
The gate now receives the incoming request's parameters and compares them (normalised sets) against the matched candidate's stored parameters. **Value-independent** answer (cached params empty) or **same value** (cached == new) → serve on cheap signals, no model call. **Value changed** → if the stored answer echoes a differing parameter, **reject-fast** (cheap refuse, never a serve); otherwise the answer may be a **transform** (it replaces the input rather than echoing it — e.g. "Translate 'hello'" → "Hola." reused for "goodbye"), which no surface test can detect, so the **Verifier** is asked and serves only on a precision-biased pass. This implements D25's stated-but-unbuilt "refuse on mismatch with the incoming request's parameters" and supersedes D26's verifier *trigger* (the borderline-confidence band, which was orthogonal to binding and structurally unreachable for a clean fresh match). The substring test survives only as reject-fast: an echoed parameter *is* evidence of binding (sound to refuse on), but its absence is *not* evidence of independence (unsound to serve on).
**Cost to reverse:** low — gate-internal policy plus one signature argument (the incoming parameters, already extracted in the pipeline). No schema change.

### D33 — Retire the base-confidence formula and the verify band (supersedes D26's confidence blend)
`base_confidence = 0.5·sim + 0.3·staleness + 0.2·margin` and the `[verify_band_lo, verify_band_hi)` band are deleted. For a single fresh candidate the formula evaluates to `0.50 + 0.5·sim` (≥ 0.85 for any `sim ≥ 0.70`), so the band only ever fired on already-doubtful matches and never on the confident-looking transforms that are the actual risk — confidence and binding are orthogonal. With the trigger moved to parameter mismatch (D32), the formula and band have no remaining job. The code is removed rather than left inert (dead config/logic reads as live and invites re-enablement — the InDermaCare drift trap); git retains the exact bytes and this entry retains the rationale. Config `intent_verify_band_lo/hi` removed; `intent_verify_pass_threshold`, `intent_margin_min`, `intent_staleness_max_seconds` retained.
**Cost to reverse:** low — the formula and band are reconstructable from this entry and `git show 06bd393` in minutes; two config fields and two constructor params.

### D34 — `confidence` is the Verifier's score when the model ran, else `None`
`GateVerdict.confidence` and `ServedCompletion.confidence` are `float | None`. The model's verify score is recorded only when the Verifier actually ran (the value-changed, non-echoing path); every cheap-signal verdict (paramless serve, same-value serve, stale/margin/reject-fast refuse) carries `None`. **`None` means "served on cheap signals, not model-scored" — not low confidence.** Similarity keeps its own separate field; folding it into `confidence` would re-merge the two axes the whole slice exists to separate (similarity ≠ confidence; GLOSSARY.md). Docstrings on both fields pin this so a future reader cannot misread `None` as `0.0`.
**Cost to reverse:** low — a field type and its bookkeeping; no schema or port change.

### D35 (DEFER) — Intent verifier stays on the cheap local model; value-independent recall is a known, fail-safe limitation
gemma3:1b captures precision (transforms 0.20-0.40, refused) but under-scores value-independent reuse
(serve-wins 0.50 / 0.30, below the 0.80 pass). One verify-prompt reframe (relevance ->
answer-correctness) was attempted and did not cleanly separate the classes on the 1B model, so the
original prompt stands. The scores are not threshold-separable - a serve-win at 0.30 sits below a
transform at 0.40 - so lowering intent_verify_pass_threshold is ruled out; it would reintroduce a
false serve. (The reframe attempt made this worse, not better: it pushed two transforms across the
0.80 pass to 0.80 / 0.87 while a serve-win still scored 0.75 - a precision regression, reverted; the
six scores are in FAILURES.md F5.) The gap fails safe (a wasted live call, never a wrong answer);
gate logic (D32-D34) is unaffected. Revisit only when a real workload justifies a stronger verifier
model (GATEWAY_VERIFIER_MODEL) or a prompt tuned to the model actually shipped - not the disposable
1B.
**Update (2026-06-27) — `gemma3:4b` tried, does not help.** The "stronger model" lever above was
tested directly (env override, both prompt variants; six scores per variant in FAILURES.md F5). 4b
did not separate the classes on either prompt and was *worse* than 1b: it confidently false-serves the
currency-conversion transform (€9.20 → 0.95 / 1.00) and false-refuses the universal return-policy
serve-win (→ 0.00). Conclusion: capacity alone is not the fix — a bigger general model is not
automatically a better answer-correctness verifier here. Revisit now means a verifier *trained or
tuned for this judgement*, not merely a larger one; the disposable local models (1b, 4b) both fail.
The deferral and its fail-safe rationale are unchanged. `phi4-mini` was also tried and is *not
evaluable* — it ignores the bare-float output contract and emits prose, so every case falls to the
0.0 fallback (F5). **Verdict across the tested set: `gemma3:1b` on the shipped relevance prompt is the
best available** — the only configuration that refused all four transforms with zero false-serves
while honoring the contract (4b confidently false-serves the convert transform at 0.95/1.00; phi4-mini
breaks the contract). The model already shipped is the safest choice; this validates the deferral
rather than reopening it.
**Cost to reverse:** trivial - a config/model swap; the port and eval already support it.

### D36 — Slice 4 is age-only TTL cleanup of `intent_entries`; per-customer erasure deferred
Slice 4 deletes intent rows past an age threshold and nothing else — no schema change, no tenant column. Per-customer ("right to be forgotten") deletion is deferred to its own slice, not for size but because `intent_entries` is the deliberately global, cross-customer store (D27/D24): one customer's canonical row is meant to serve every customer. Scoping *reads* by tenant would kill that cross-serve (the tier's reason to exist); scoping *deletes* alone hits provenance ambiguity (who owns a canonical row A created and B reuses?). "Multi-customer" is the motivation — a shared store accumulates everyone's intentions — not a per-customer feature this slice. Synthetic single-tenant data (D31) means near-term erasure need is zero; the hole is named, not faked (cf. F6).
**Cost to reverse:** low — a `customer_id` column is additive and nothing here blocks it; the provenance/scoping tension is captured so the future slice starts from the problem, not a blank page.

### D37 — Deletion runs on an in-app asyncio background timer (not on-write, not pg_cron)
A background task started in the lifespan wakes on a fixed interval and runs the prune. On-write pruning (delete inside every `store()`) was rejected: it is race-safe (one self-selecting `DELETE`; deleting an already-gone row is a no-op) but taxes every write, does redundant scan/lock work under load on the serving path, and never cleans on a quiet day. pg_cron was rejected: tidy operationally but adds a Postgres extension (init.sql only creates `vector`) and hides the logic outside the codebase being demoed.
**Cost to reverse:** low — moving the same `DELETE` to pg_cron later is a config change; the repo method and SQL stay.

### D38 — One method `prune_older_than(max_age_seconds: float) -> int` on `IntentRepository`
The seam gains exactly one method, named for its single job, returning the deleted rowcount (Postgres gives it for free) so the timer can log proof it ran and the test can assert "deleted 1, fresh survives." No generic `delete(criteria)` API — D36 cut the tenant axis, so there is nothing to generalise over; a criteria engine for one `DELETE` is the over-engineering trap. The argument is `max_age_seconds`, matching the gate's `staleness_max_seconds` vocabulary.
**Cost to reverse:** low — renaming or adding a parameter is local to the Protocol + one adapter; nothing else calls it.

### D39 — Prune age reuses `intent_staleness_max_seconds`; no separate TTL field
One global age, and it is the gate's existing staleness setting, not a new constant. The gate already refuses any candidate older than `intent_staleness_max_seconds` (verified: `intent_gate.py`, cheap-signal #1), so "stop serving it" and "delete it" are the same fact — a second age constant could only drift from the first (the config-drift failure logged earlier). Reusing it also means raising staleness later keeps rows kept-and-servable together automatically. A dedicated `intent_ttl_seconds` is deferred until a real need (e.g. a serve-window-vs-retention grace buffer) appears.
**Cost to reverse:** low — adding `intent_ttl_seconds` (default = staleness) is additive; the method already takes an age argument, so only the timer's call site changes.

### D40 — Fixed sweep interval `intent_prune_interval_seconds` (default 3600); a failed sweep never crashes the app
The cadence is its own config field defaulting to hourly — unlike the age (D39) it has nothing to anchor to; it is just "how much already-unservable weight to tolerate between cleans," and a fixed honest number beats a clever divisor. The loop wraps the prune in try/except: success logs the count, exception logs and continues (a failed sweep skips that round and retries next interval, never propagating), and shutdown cancels the task and awaits it so `CancelledError` ends the loop cleanly rather than as a crash. A *persistently* failing sweep degrades to no-cleanup — the log line is the only signal — acceptable for a disposable cache, the thing to watch if this becomes load-bearing.
**Cost to reverse:** low — interval is one config value; the try/log/sleep shape is contained in the timer function.

### D41 — Rely on autovacuum for dead-tuple/HNSW reclamation; escalation levers documented, not built
A `DELETE` only marks rows dead; the space and the dead HNSW index nodes are reclaimed by `VACUUM`. Stock `pgvector/pgvector:pg18` runs autovacuum at defaults (verified: no override in docker-compose or init.sql), which covers a small disposable cache deleting day-old rows. No vacuum runs in the sweep: a manual `VACUUM` fights psycopg's transaction model (it cannot run inside a transaction) and churns the table hourly for a problem we don't have. Correctness is unaffected — a deleted row is never returned, only briefly traversed-and-skipped until autovacuum cleans it. If this ever runs hot, the escalation order is documented: first tune this one table (`ALTER TABLE intent_entries SET (autovacuum_vacuum_scale_factor = …)`), then a plain manual `VACUUM` in the sweep on an autocommit connection — never a scheduled `VACUUM FULL` (it rewrites the table under a lock that blocks everything).
**Cost to reverse:** low — the table tuning is one `ALTER TABLE`; a manual vacuum is a few lines on an autocommit connection. Nothing here blocks either.

### D42 — Two tests prove the slice: integration for the DELETE, unit for the timer's failure safety
They cover different claims; neither is redundant. Integration (marked `integration`, self-skips when no DB, TRUNCATEs first, like the cache test): store one entry backdated via `store()` (`created_at` = now − 48h) and one fresh, call `prune_older_than(86400)`, assert it returns 1 and a direct SELECT finds only the fresh row — proving the `WHERE created_at < now() − interval` predicate, which a fake cannot. (Verify via SELECT, not search: both rows carry a zero embedding and cosine distance on a zero vector is NaN, so search would misbehave.) Unit (fake repo whose `prune_older_than` raises once): assert the loop logs and continues rather than propagating, and stops cleanly on cancel — backing D40's safety promise, which the integration test never exercises. Assert behaviour (continues after a raise, stops on cancel; rowcount; fresh survives), not timing or log strings.
**Cost to reverse:** low — tests are additive; tightening or merging them touches only the test files.

### D43 — Action detection lives in the model's reply, not the request or the prompt text
A request is an *action* (must run, never reuse) iff the model's reply is a **tool call**; a *question* (cacheable) iff the reply is **text**. Decided by observing the model's output, never by reading the user's input: no `kind` field on the request (a transparent proxy only sees raw user text — there is no app-declared intent to trust), no verb list and no prompt classifier ("contains 'cancel'" ≠ "is an action"; "what does cancelling cost?" is a question — the surface-proxy-for-a-semantic-property trap this project exists to kill). The cache tiers are dumb lookups; only the model, on the live path, ever decides to call a tool. **Supersedes** the originally-planned in-gateway `ActionExecutor` port: the gateway is a proxy, the model emits the tool call and the *app* executes it — the gateway never performs a side effect, it only refuses to cache one.
**Cost to reverse:** low — detection is read off a reply field; an app-declared hint or a classifier backstop could be added later behind the same branch without removing anything.

### D44 — The reply carries a structured tool call, threaded to the caller (the "Complete" shape)
`CompletionResult`, `ServedCompletion`, and the wire `ChatResponse` each gain `tool_call: ToolCall | None` (`ToolCall{name: str, arguments: dict[str, Any]}`), default `None`. Present ⇒ the model acted. A bare boolean flag was rejected: the *cache* only needs one bit ("don't store"), but the *app* needs the actual `cancel_order(1111)` to execute, so the structured call is threaded all the way to the wire. The shape mirrors the OpenAI tool-call contract the `openai_compat` backend already speaks — real-enough, not invented. All fields default `None`, so every existing caller and construction site is unchanged.
**Cost to reverse:** low — additive optional fields; deleting them and the guard reverts to text-only.

### D45 — A tool-call reply is never cached; the rule closes F6
In `RequestPipeline.process`, immediately after `backend.complete` and **before** the admission-store block, a guard returns early when `completion.tool_call is not None`, skipping the store entirely (the reply is written to neither `cache_entries` nor `intent_entries`). Because such a reply is never stored, it can never be matched and re-served, so the F6 hole (a cached value-free "Done." re-served for a different order that never ran) is structurally impossible. The deeper rationale generalises beyond writes: a tool-call reply reflects **live, mutable external state** (the orders DB), so it is not reusable static knowledge — this covers reads (`get_order_status`, whose answer changes as the order progresses) as well as writes (`cancel_order`). **Accepted cost:** a tool that happens to read genuinely static data is also never cached; we deliberately do *not* classify "is this tool's output stable?", because that is the same can't-tell-from-the-surface trap as D43. Static, cacheable content must therefore be produced as **text** by the model (optionally from app-injected context), never via a tool.
**Cost to reverse:** low — remove the guard; the store block runs for every reply again.

### D46 — The eshop is a minimal runnable app, not a test-only harness
Slice 6 needs a real model to actually call a tool against real (if in-memory) state. The eshop is built as a **runnable FastAPI app** — `POST /chat` plus a few order endpoints (`cancel_order` / `refund_order` / `get_order_status`) over an in-memory dict, no DB, no UI, no auth — so it is curl-able and demoable, not just green tests. Chosen over a test-only harness (the cheaper option) because the value of this slice includes a thing you can poke by hand. The eshop is a **separate service** that calls the gateway over HTTP: the app owns the business (orders, tool menu, FAQ) and executes tools; the gateway stays generic and never performs a side effect (D43). A thin console chat client drives the app's `/chat` for demos.
**Cost to reverse:** low — the store + tool menu + execute loop are the substance; swapping the HTTP shell for a harness (or back) leaves them intact.

### D47 — The tools menu crosses as an opaque passthrough, not a typed model
`ChatRequest` and `CompletionRequest` gain `tools: list[dict[str, Any]] | None` (and `context: str | None`, see D51). The app builds the menu in the exact OpenAI tool shape; the gateway forwards it verbatim into the model payload and **never inspects it**. A typed `ToolSpec` model was rejected: the gateway only types what it *inspects*, and it inspects the model's *reply* (the typed `ToolCall`, D44), not the menu it merely relays. This is consistent with the one loose-dict exception already shipped — `ToolCall.arguments: dict[str, Any]` — for the same reason (per-tool shapes can't be statically typed). Trade-off named: it widens the loose-dict surface CLAUDE.md warns against, and a malformed menu fails at the model rather than at the gateway boundary — acceptable for an app you control.
**Cost to reverse:** low — wrap the menu in a typed `ToolSpec` later behind the same seam; nothing else moves.

### D48 — Parse only the first tool call; multi-tool is a future feature
`openai_compat` reads `choices[0].message.tool_calls[0]`, `json.loads` its `function.arguments` (Ollama returns it as a JSON **string**, confirmed live) into the typed `ToolCall(name, arguments: dict)`. Additional tool calls in the same reply are **ignored**; malformed argument JSON raises `BackendError` (the existing bad-response path). A real parallel-action request ("cancel 1111 and refund 2222") therefore silently drops the second action — an accepted limitation for a thin cancel/refund/status shop, not an oversight.
**Future:** widen the `tool_call` field to a list and execute several actions per turn.
**Cost to reverse:** low — widen the field; the parse already sees the full list.

### D49 — Templated confirmation reply; no second model call
After the app executes the tool, it returns a **fixed confirmation string** itself (e.g. `f"Done — order {order_id} cancelled."`) — no second round-trip to the model. Plain text, deliberately **without** an "Anything else?" tail: with no conversation memory yet (D50), inviting a follow-up would be a promise the system can't keep. A model-written reply (sending the tool result back for the model to phrase) is nicer for a real product but must *also* bypass the cache, because it describes live mutable state — the same reason actions aren't cached (D45).
**Future:** model-written confirmation via a second, explicitly uncached, model call.
**Cost to reverse:** low — add the second call behind the execute step.

### D50 — Single-message only; conversation memory is the next slice
The request carries one user message; the gateway does not assemble prior turns. None of Slice 6's scenarios need history, and adding it pulls in the cache-key problem (what do you hash/embed when there are several messages — the last? the transcript?), which is a slice of its own.
**Future:** conversation/messages support + a cache-key policy for multi-turn.
**Cost to reverse:** low — purely additive; nothing here blocks it.

### D51 — Question and injected context are separate fields; the cache keys only on the question
The FAQ/policy text the model needs is sent as a distinct `context` field, **not** glued onto the prompt. The gateway injects it as a system message for the model, but every cache key (exact hash + semantic/intent embedding) is computed on `prompt` alone — which the pipeline already does, so the split is what keeps it correct. Folding context into the prompt would let two different questions sharing the same large FAQ look near-identical to the matcher and false-serve each other. For Slice 6 the app supplies `context` from a **hardcoded FAQ**; where that text comes from is the app's business.
**Future:** real RAG — the app retrieves relevant context from its own DB/file/vector store and fills `context`. App-side; the gateway's `context` seam is unchanged.
**Cost to reverse:** low — additive field; remove it to revert to prompt-only.

### D52 — Two-track e2e tests: deterministic fakes in CI, a self-skipping live run by hand
Every scenario (exact / semantic / intent reuse-vs-refuse / action-never-cached / FAQ self-populate) runs in CI against a **fake backend** returning canned replies — fast and deterministic, proving the gateway's *logic* and the app's execute loop. A separate `-m live` run uses the real `llama3.2:3b` to prove the *model* actually emits the tool call; it self-skips when the servers aren't up and never runs in CI (per F3). The two answer different questions — verification (the wiring) vs validation (the model isn't lying), the F4/F5 lesson. The live action assertion checks that a tool *named* `cancel_order` was called, not the exact wording, so model nondeterminism doesn't flag false failures.
**Cost to reverse:** low — it's test code.

### D53 — Backend model swapped to llama3.2:3b for tool support
The live probe showed Ollama rejects tools on the old default: `gemma3:1b does not support tools`. `GATEWAY_BACKEND_MODEL` default changes to `llama3.2:3b`, which emits proper OpenAI `tool_calls` (verified live, `finish_reason: "tool_calls"`, `arguments` returned as a JSON string). This is the config-only swap the backend was designed for (D16). The **verifier** stays `gemma3:1b` (F5/D35: measured best-of-set; tool-incapability is irrelevant to its bare-float scoring job, and stronger general models false-served the dangerous direction).
**Cost to reverse:** trivial — one env/default value.
