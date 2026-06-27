# Setup

Goal: anyone can clone this repo and have it running in a few minutes, on macOS, Linux, or Windows, without "works on my machine."

The whole stack is designed so the host prerequisites collapse to **two tools**. Everything else is either containerized (Postgres + pgvector) or managed by `uv` (Python itself, the virtualenv, dependencies, the lockfile).

---

## What you install on your machine

| Tool | Why | Install |
|---|---|---|
| **Docker** (+ Compose v2) | Runs Postgres with the pgvector extension. The extension ships **inside the image** — you never compile or install it yourself. | [Docker Desktop](https://www.docker.com/products/docker-desktop/) (macOS/Windows) or Docker Engine + the `docker compose` plugin (Linux) |
| **uv** | Installs the correct Python version, creates the venv, resolves and installs all dependencies from the lockfile. You do **not** need Python pre-installed. | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh`  ·  Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`  ·  or `brew install uv` |
| Git | Clone the repo. | system package manager |

Use the **standalone uv installer** (above), not `pip install uv` — installing uv via pip needs a Python you may not have yet (circular), while the standalone installer needs neither Python nor Rust.

### What you explicitly do NOT install

- **No local PostgreSQL**, and **no compiling pgvector** (`make install`) — it's in the Docker image.
- **No pyenv / poetry / pip / virtualenv juggling** — `uv` replaces all of them.
- **No PyTorch / CUDA** — embeddings use `fastembed` (ONNX, CPU). The model (~90 MB for MiniLM) downloads automatically on first run, so the first start needs network access.

---

## Run it

```bash
git clone <repo-url> ai-gateway && cd ai-gateway

# 1. Start Postgres + pgvector (extension auto-enabled by db/init.sql)
docker compose up -d db

# 2. Install Python + all dependencies from the lockfile
uv sync            # uv reads .python-version, fetches that Python, installs deps

# 3. Run tests / the app
uv run pytest
uv run python -m gateway          # the run entrypoint (see Windows note below)
```

> Run the app with `python -m gateway`, not `uvicorn gateway.main:app`, on **Windows**: the launcher forces a selector event loop, which psycopg async requires there (see Notes). On macOS/Linux `uvicorn gateway.main:app --reload` also works.

That's the entire end-user path. `uv sync` is reproducible across machines because of `uv.lock`.

---

## The dependency manifest (what gets installed, exactly)

For transparency and for bootstrapping from scratch, these are the locked dependencies. Once `pyproject.toml` + `uv.lock` exist, contributors just run `uv sync` — they don't run these.

```bash
uv python pin 3.13          # writes .python-version

# runtime
uv add fastapi "uvicorn[standard]" httpx pydantic pydantic-settings \
       "psycopg[binary,pool]" pgvector fastembed

# dev / quality gates
uv add --dev ruff mypy pytest pytest-asyncio
```

| Package | Role |
|---|---|
| `fastapi`, `uvicorn[standard]` | async web framework + ASGI server |
| `httpx` | async outbound HTTP to the LLM providers |
| `pydantic`, `pydantic-settings` | typed request/response/domain models + config from env |
| `psycopg[binary,pool]` | Postgres driver (psycopg 3) + async connection pool |
| `pgvector` | registers the `vector` type with psycopg so vectors round-trip |
| `fastembed` | local ONNX embeddings (all-MiniLM-L6-v2 / bge-small, 384-dim) |
| `ruff` | lint + format |
| `mypy` | strict type checking — the "compiler" / maintainability backbone |
| `pytest`, `pytest-asyncio` | tests, incl. async |

---

## Verify the environment

```bash
# pgvector extension is enabled in the DB
docker compose exec db psql -U gateway -d gateway \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
# → vector | 0.x.x

# toolchain works
uv run ruff check .
uv run mypy src
uv run pytest -q
```

---

## Notes

- **Postgres version:** pinned to `pg18` in `docker-compose.yml` — the latest major, so the longest support runway (Postgres has no LTS track; every major gets 5 years from its release, so newest = longest-supported). Minor bumps (`18.x`) are seamless; a *major* bump changes the on-disk format and needs `pg_upgrade` or dump/restore — but since this store is a disposable cache, `docker compose down -v` and recreate is fine.
- **Windows + async psycopg:** psycopg's async is incompatible with the default ProactorEventLoop, and uvicorn hard-codes Proactor on Windows — so launch with `python -m gateway`, which runs the server on a SelectorEventLoop instead. (Tests handle this via an `event_loop_policy` fixture.) See the `pgvector-psycopg` skill, rule 9, and `FAILURES.md` F3.
- **Enabling the extension:** done once via `db/init.sql`, which Postgres runs on first container start. If you reset the volume, it re-runs.
- **Schema changes need a volume reset (gotcha):** `db/init.sql` runs **only when the `pgdata` volume is empty** (first init), and it uses `CREATE TABLE IF NOT EXISTS`. So editing the schema and running a plain `docker compose up -d` does **nothing** to an existing volume — the old schema persists. Symptom: integration tests fail with `UndefinedColumn` / missing-table against a DB that "should" be current (e.g. a stale `cache_entries` without `prompt_hash`, or no `intent_entries`). Fix: `docker compose down -v && docker compose up -d` to recreate the volume so init.sql re-runs (`down` alone keeps the volume; the `-v` is the point). Verify with `docker compose exec db psql -U gateway -d gateway -c "\dt"`. Safe here because the store is a disposable cache.
