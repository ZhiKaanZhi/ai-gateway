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

**Slice 2 live.** `POST /v1/chat` runs the full cache-aside pipeline end-to-end:
- Semantic cache hit → returns immediately without a model call (`cached: true`, `similarity` reported).
- Cache miss → classified (constant tier, stub), routed, served by `OpenAICompatibleBackend` over
  async httpx (Ollama locally; Groq/OpenAI later is a base-URL + key change), stored reusing the
  miss's embedding, returned (`cached: false`).
- Backend failures surface as 502 (non-2xx / transport) or 504 (timeout).

**Stubbed / pending:** complexity classifier (always returns SIMPLE), multi-backend routing,
intent caching (Slice 3 — the showpiece: three-tier cache with confidence scoring + fallback).

To use the live path, run a local [Ollama](https://ollama.com) and pull the default model:
```bash
ollama pull gemma3:1b
python -m gateway    # Windows-safe SelectorEventLoop launcher
curl -X POST http://localhost:8000/v1/chat -H "Content-Type: application/json" \
     -d '{"prompt": "What is the capital of France?"}'
```
