# Failures

Running taxonomy of where an agent, skill, or generated step produced bad output — and why. Evaluating the flow is the actual skill being practiced here, so log the failure, the root cause, and the fix. Thin and honest beats comprehensive.

---

### F1 — `pgvector-psycopg` skill: "a `list[float]` binds to `vector` directly" was wrong
**Surfaced:** Slice 1, the cache integration test — `psycopg.errors.UndefinedFunction: operator does not exist: vector <=> double precision[]`.
**Root cause:** The skill (rule 4) claimed a plain `list[float]` binds to `vector` once the type is registered. It does not: in pgvector ≥0.3 the psycopg dumper is registered only for `numpy.ndarray` and `pgvector.Vector`. A bare `list` falls through to psycopg's array dumper, so the value arrives as `double precision[]` and no `<=>` operator matches. `register_vector_async` fixes reads + the type OID, not list dumping.
**Fix:** Wrap at the bind boundary in `adapters/repository.py` — `Vector(embedding)` for the query and the stored vector — keeping the domain type `list[float]`. Corrected skill rule 4 and added a "Gotchas grows" entry so the next reader doesn't repeat it.
**Lesson:** Trust the skill for *where* the footguns are, but verify binding behaviour against the installed package version, not the prose.

### F2 — `docker-compose.yml`: PG18 volume mounted at `/var/lib/postgresql/data`
**Surfaced:** Slice 1, recreating the DB — container exited (1) with "in 18+, these Docker images store data in a major-version-specific directory… Counter to that, there appears to be PostgreSQL data in /var/lib/postgresql/data (unused mount/volume)".
**Root cause:** PG18 official images (which pgvector/pgvector:pg18 is built on) moved the data dir under a major-version subdir and expect the volume mounted at `/var/lib/postgresql`, not `…/data` (docker-library/postgres#1259). The bootstrap compose used the pre-18 `…/data` mount, so the container refused to start. It had been silently unhealthy; earlier gates only passed because no test touched the DB.
**Fix:** Mount the volume at `/var/lib/postgresql`. Cache is disposable (DECISIONS D2), so `docker compose down -v && up -d` to recreate cleanly.
**Lesson:** `docker compose up -d` returning success ≠ DB healthy. Check container health before trusting the DB leg of a gate.

### F3 — `pgvector-psycopg` skill: "under uvicorn it's fine" on Windows was wrong
**Surfaced:** Slice 1 manual round-trip — the app booted but every pool connection logged `Psycopg cannot use the 'ProactorEventLoop' to run in async mode`, so `/cache/*` couldn't reach the DB.
**Root cause:** Skill rule 9 said the Proactor/psycopg incompatibility only bites when "running asyncio directly," and that uvicorn was fine. Not on Windows: uvicorn's auto loop there is the ProactorEventLoop, which psycopg async rejects. The test suite hid this because conftest's `event_loop_policy` fixture already forced the selector loop — so tests were green while the real server was broken.
**Fix (two false starts before the real one):**
1. Set the policy at `main.py` import — **failed**: the uvicorn CLI creates its loop before importing the app, so the policy lands too late.
2. Set the policy in a launcher before `uvicorn.run` — **also failed**: uvicorn ≥0.36 passes a `loop_factory` to `asyncio.run` that hard-codes `ProactorEventLoop` on Windows (`uvicorn.loops.asyncio`), ignoring the policy entirely.
3. **Worked:** bypass uvicorn's loop selection — `asyncio.run(uvicorn.Server(config).serve(), loop_factory=asyncio.SelectorEventLoop)` in `gateway/__main__.py` (`python -m gateway`), guarded to `win32`. Corrected skill rule 9 to match.
**Lesson:** A green test suite can mask a runtime-only failure when the harness fixes the very thing production must fix itself. Do the manual round-trip — it caught what 8 passing tests didn't. And read the library's actual loop setup before assuming the asyncio policy is the lever.

### F4 — Slice 3 first pass: green gates, but a broken showpiece + real defects the reviewer caught
**Surfaced:** Slice 3 intent caching — `ruff`/`mypy --strict`/`pytest` were all green on the first pass, yet the `python-architecture-reviewer` (and then *running* the eval) found several genuine problems:
1. **`prompt_hash` declared nullable** (`text UNIQUE`, not `text NOT NULL UNIQUE`). The upsert keys on `ON CONFLICT (prompt_hash)`, but `NULL != NULL` in SQL — a null hash would silently insert a duplicate instead of collapsing it. The app never inserts null (the model requires it), so no test caught it; the DDL was a latent landmine.
2. **`evals/` imported `tests.conftest.FakeVerifier`** — eval code depending on the test package; fails outside a dev checkout. Tests passed because `tests/` was on the path.
3. **Private `_configure` imported across adapter modules** (with a `noqa`), plus two pools to the same DB. Collapsed to one shared pool, removing both smells.
4. **The eval headline was silently false.** The offline harness used Jaccard word-overlap as a similarity proxy. Word-overlap never reaches 0.97 for the surface-close cases, so the cosine-only baseline scored **0** false serves — making the showpiece print "baseline 0; gate 0", the *opposite* of the point (D30 is "baseline N; gate 0"). Every gate was green while the deliverable's one headline number was wrong. Fixed by labeling each case with the cosine a real embedder assigns (part of the adversarial design), so the harness reproduces the true contrast (baseline 4; gate 0).
**Root cause:** The quality gates check *type-safety and style*, not *semantic correctness of the artifact*. A green suite proved the code runs, not that the eval proves what it claims or that the schema enforces what the model assumes. Defect (4) only surfaced when the eval was actually *executed*, not asserted.
**Fix:** Addressed all four; re-ran `ruff`/`mypy`/`pytest` (46 pass) **and** the eval CLI to confirm "baseline 4 → gate 0".
**Lesson:** Green gates are necessary, not sufficient. For a *deliverable whose value is a number* (the eval), run it and read the number — don't trust a passing assertion that the headline holds. And run the architecture reviewer before declaring a slice done: it caught the packaging + schema defects the type checker structurally cannot.
