# ai-gateway

A Python LLM **gateway**: semantic caching + intelligent serving, built with FastAPI,
PostgreSQL + pgvector, and local ONNX embeddings (fastembed). Ports-and-adapters (hexagonal)
architecture, `mypy --strict`, and async all the way down.

See [`SETUP.md`](SETUP.md) to run it, [`CLAUDE.md`](CLAUDE.md) for the architecture, and
[`DECISIONS.md`](DECISIONS.md) for the rationale behind every choice.

## Quick start

```bash
docker compose up -d db    # Postgres 18 + pgvector
uv sync                    # Python 3.13 + all deps from the lockfile
uv run pytest -q
uv run uvicorn gateway.main:app --reload
# GET http://127.0.0.1:8000/health -> {"status": "ok"}
```

## Status

Harness only: the ports-and-adapters skeleton, config, and a live `/health` endpoint.
Service and adapter implementations (semantic cache, pipeline, intent caching, classifier,
router) are typed stubs awaiting their own slices.
