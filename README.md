# ai-gateway

A Python LLM **gateway**: a transparent proxy in front of a model that adds a three-tier
semantic cache (so repeat and paraphrased questions skip the model) and refuses to cache
**actions** (tool calls). Built with FastAPI, PostgreSQL + pgvector, local ONNX embeddings
(fastembed), hexagonal ports-and-adapters, `mypy --strict`, async throughout.

This repo is a learning/portfolio build — the engineering showpiece is the cache's
correctness logic ("similarity ≠ confidence", "intent match ≠ serve", "a tool call is never
cached"), not novelty.

Docs: [`SETUP.md`](SETUP.md) to run it · [`CLAUDE.md`](CLAUDE.md) for architecture/conventions ·
[`DECISIONS.md`](DECISIONS.md) for the rationale behind every choice · [`FAILURES.md`](FAILURES.md)
for the failure taxonomy · [`GLOSSARY.md`](GLOSSARY.md) for the vocabulary.

## What it does

- **Serves repeat questions from cache, three tiers, first hit wins:** exact (hash) →
  semantic (cosine on the full prompt) → intent (cosine on the parameter-stripped prompt,
  behind a confidence gate). A miss falls through to the model and is stored.
- **Gates intent reuse on correctness, not just similarity:** a value-mismatch check plus a
  small-model verifier, biased hard to precision — it refuses a reuse it can't vouch for.
- **Never caches an action:** action-ness is read off the model's *reply* — a **tool call** is
  an action, plain text is a question (never a verb list or a request flag). A tool-call reply
  reflects live mutable state, so it is returned live and stored in neither tier.
- **Stays generic:** the menu of tools and the business logic live in the *app*; the gateway
  relays the menu and executes nothing. Swap the app, swap the business.

A small **eshop** app (orders + a chat box + an FAQ) demonstrates the whole path end to end,
including the cache filling itself on FAQ questions.

## Architecture

    console CLI ──HTTP──► eshop app ──HTTP /v1/chat──► ai-gateway ──HTTP──► Ollama
    (dumb terminal)      │ orders (in-mem) │  prompt + │ 3-tier cache  │   llama3.2:3b
                         │ tool menu       │  tools +  │ → route       │   (backend)
                         │ FAQ text        │  context  │ → backend     │   gemma3:1b
                         │                 │           │ never caches  │   (verifier)
                         │ executes the    │           │ a tool call   │
                         │ tool the model  │           │      │        │
                         │ chose           │           │      ▼        │
                         └─────────────────┘     Postgres 18 + pgvector
                                                 cache_entries · intent_entries

- The **gateway** (`src/gateway/`) is the subject: cache + routing + the action seam. Business-agnostic.
- The **eshop** (`src/eshop/`) is a separate service that *calls* the gateway. It owns the
  tools, the FAQ, and the order store, and executes the tool the model picks.
- **Ollama** serves both models locally (free): `llama3.2:3b` answers/acts, `gemma3:1b` scores
  the intent verifier. Swapping providers is a base-URL + key change (httpx is confined to one adapter).
- **Postgres + pgvector** holds the two cache tables; the cache is disposable.

## Data flow

A **question** (cacheable):

    "what's your return policy?"
      CLI → eshop → gateway
        exact miss → semantic miss → intent miss
        → model answers (FAQ supplied as context; cache key is the question only)
        → STORED
      → next identical/similar ask is served from cache, no model call.

An **action** (never cached):

    "cancel order 1111"
      CLI → eshop → gateway
        model is given the tools menu → replies with a tool call: cancel_order(1111)
        → gateway sees the tool call → returns it LIVE, stores nothing
      eshop executes cancel_order(1111) → order flips to cancelled
      → eshop returns "Done — order 1111 cancelled."
      (re-run → the model is called again; never served from cache)

## Status

Slices 1–6 shipped; `ruff`, `mypy --strict`, and the full suite green (72 tests; the DB-integration
and `-m live` tests self-skip when Postgres/Ollama aren't reachable, so CI stays green offline).

- **Slice 1 — semantic cache vertical:** fastembed embeddings + pgvector store + `/cache/*`.
- **Slice 2 — pipeline + one real backend:** `POST /v1/chat` runs cache → classify → route →
  backend (OpenAI-compatible over httpx, Ollama as the free dev default); 502/504 error contract.
- **Slice 3 — intent caching (the showpiece):** three-tier cache, the confidence gate, an
  adversarial eval (gate → 0 false serves vs a cosine-only baseline). Hardened in D32–D34 so the
  verifier fires on value mismatch and is genuinely exercised.
- **Slice 4 — data hygiene:** age-based TTL cleanup of intent rows via a lifespan background timer.
- **Slice 5 — action seam:** a tool-call reply is detected from the reply and never cached (D43–D45).
- **Slice 6 — eshop e2e:** real tool plumbing — the eshop app, the menu forwarded and tool calls
  parsed, a real model deciding, FAQ-as-context, a console chat client, two-track tests (D46–D53).

> Classifier + router are wired but **inert** (always SIMPLE → the one backend); real multi-model
> routing is deferred (D18).

## Next / parked

- **Conversation + messages (next slice, D50):** multi-turn chat and the cache-key policy it
  forces (what to hash/embed across several messages).
- **Multi-tool calls (D48):** execute more than one action per reply.
- **Model-written confirmations (D49):** a second, uncached, model call to phrase replies.
- **RAG context (D51):** the app retrieves FAQ/policy from its own store instead of a hardcoded blob.
- **Verifier recall (D35):** the 1b verifier fails *safe* (refuses some safe reuse); revisit with a
  judge tuned for answer-correctness, not a bigger general model.
- **Per-business cache isolation:** one shared cache could leak answers across tenants — out of scope so far.

## Quick start

Two host tools only — **Docker** and **uv** (uv fetches Python itself). Full guide in [`SETUP.md`](SETUP.md).

    # 1. Postgres 18 + pgvector
    docker compose up -d db

    # 2. Python 3.13 + deps from the lockfile
    uv sync

    # 3. tests + the gateway
    uv run pytest
    uv run python -m gateway        # Windows-safe launcher; on macOS/Linux uvicorn gateway.main:app --reload also works
    # GET http://127.0.0.1:8000/health -> {"status": "ok"}

Live path + the eshop demo (needs Ollama):

    ollama pull llama3.2:3b         # backend (tool-capable)
    ollama pull gemma3:1b           # intent verifier

    uv run python -m gateway                                  # gateway on :8000
    uv run uvicorn eshop.app:app --port 8001                  # eshop on :8001
    uv run python -m eshop.cli                                # chat with it

    # or curl the eshop directly:
    curl -X POST http://localhost:8001/chat -H "Content-Type: application/json" \
         -d '{"message": "cancel order 1111"}'
