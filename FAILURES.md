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
