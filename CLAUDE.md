# CLAUDE.md

Project memory for this repo. Read at the start of every session and inherited by every subagent. Kept deliberately tight — every line here is paid on every turn.

## What this is

A Python LLM **gateway** (semantic caching + intelligent serving), built primarily with Claude Code. It is a **portfolio / learning asset optimized for legibility and maintainability**, not a product to ship to a market. The goal is to demonstrate that AI-assisted engineering can produce idiomatic, type-safe, defensible code.

## Prime directive: the .NET prototype is a reference, never a template

A previous `.NET/C#` prototype of this gateway exists and may be in context. **Use it only to understand _what the system does_ and _which decisions were made_ — never to copy _how it is structured_.** C# structure ported literally into Python is the single biggest quality risk here. Keep the *thinking* (dependency inversion, swappable backends, a testable core); express it in *idiomatic Python*.

## Stack (locked)

FastAPI + uvicorn · httpx (async outbound) · Pydantic v2 + pydantic-settings · PostgreSQL 18 + pgvector · psycopg 3 (async) + psycopg_pool · fastembed (ONNX, 384-dim MiniLM/bge-small) · uv · Ruff · mypy --strict · pytest + pytest-asyncio · Docker Compose.

## Architecture

**Ports-and-adapters (hexagonal).** A gateway's whole job is adapting one client interface to many swappable backends — hexagonal is the correct fit, defensible in an interview. Organize around the *ports* (the seams that matter), **not** technical layers.

```
src/gateway/
  main.py        # FastAPI app + lifespan = composition root (wire singletons here)
  config.py      # Pydantic Settings
  api/           # routes.py (thin handlers) + schemas.py (Pydantic = the API contract)
  domain/        # models.py + ports.py (the Protocols)
  services/      # orchestration: pipeline.py, cache_service.py, classifier.py, router.py
  adapters/      # concrete impls: embeddings.py (fastembed), repository.py (psycopg/pgvector), backends/
tests/           # conftest.py provides fakes implementing the Protocols
```

**Protocols live only at real swap seams** (don't create one per class): `EmbeddingProvider`, `CacheRepository`, `ModelBackend`, `ModelRouter`, `ComplexityClassifier`. `BillingService` / `QualityChecker` are Protocols with NoOp defaults.

## Do NOT write C# in Python (the tells that turn this into a negative signal)

- One interface (Protocol) per class. → Protocols only at the seams above.
- A DI container / service locator. → FastAPI `Depends()` + a composition root in `lifespan`. No framework.
- Deep inheritance hierarchies. → Composition and plain functions.
- `Manager` / `Helper` / `AbstractFactory` ceremony and `AbstractSingletonProxyFactoryBean`-style names. → Plain names: `embeddings.py`, `repository.py`, `pipeline.py`.
- Getters/setters and underscore-everything encapsulation. → Plain attributes; Pydantic models for data.
- Everything-is-a-`dict` (the opposite failure). → Typed Pydantic models / dataclasses at every boundary; no loose dicts crossing seams; no stray `Any`.
- Sync I/O in an async app. → async all the way down (httpx, psycopg async). Never block the event loop.

## Quality gates (non-negotiable)

`mypy --strict`, `ruff check`, and `pytest` **must pass**. Type errors are build failures — strict typing is the compile-time safety net that separates "maintainable" from "only AI can read it." These run in pre-commit and CI (and via hooks during a session), so don't re-litigate them by hand.

## Scope — hold this line

- **CORE (build):** semantic cache (embeddings + pgvector + `lookup`/`store`); request-pipeline skeleton (steps may be stubs); **intent caching** (confidence scoring + fallback) — the showpiece.
- **Second layer (only if time):** complexity classifier + cost-aware router + multi-provider backends.
- **Stubs (NoOp default):** billing, quality checker, escalation.
- **Explicitly OUT:** Kafka / real-time feature pipeline, A/B testing, multi-tenancy, tool registry, the "become an AI provider" billing/business layer. (These are in the old .NET roadmap — that strategy is superseded. Do not re-introduce them.)
- **`src/eshop/` is a demo app, not part of the gateway:** it may hold business logic and its own loose-dict tool menu. The gateway's rules (no business logic, no loose dicts crossing seams except the named exceptions) bind `src/gateway/` only.

Scope creep is the known failure mode. The version that gets *finished and defended* beats the sprawling one.

## Intent caching = the interview story

Three-tier cache: exact → semantic → intent. Each tier has a confidence gate; the **intent tier needs the strongest gate**, because a false positive triggers a *wrong tool call* (worse than a wrong text answer). The deliberate design of confidence scoring + fallback is the differentiating story. Build it last in CORE and write it up in `DECISIONS.md`.

The intent gate decides reuse by **parameter relationship** (D32, revised post-ship): value-independent or same-value answers serve on cheap signals; on a value mismatch, an echoed old value is a cheap **reject-fast**, and a non-echoing answer (a possible *transform* — `"Translate 'hello'"` → `"Hola."`) is judged by the **Verifier**. The old substring-binding-check is reject-fast only, never a serve signal — see F5 for why a surface test can't detect transform-binding.

**Actions are never cached** (D43–D45, closes F6): action-ness is detected from the model's *reply* — a **tool call** is an action, plain text is a question — never from a verb-list or a request flag. A tool-call reply is stored in neither tier, so it can never be matched or re-served.

## Working discipline

- **`DECISIONS.md`** — append every architectural decision + its rationale. Source of truth, interview-ready.
- **`FAILURES.md`** — when an agent or skill produces bad output, log what failed and why. This is the running failure taxonomy; evaluating the flow is the actual skill being practiced here.
- **Keep agents/skills in sync with the code.** Verify `.claude/` definitions against what's actually in the repo, not against earlier design docs. Flag drift the moment you see it.
