"""Hand-run real-model check of the Verifier (eval "b") — not pytest.

The offline harness (``evals/run_eval.py``) proves the gate *routes* correctly **given** a competent
verifier — it mocks the score. This script proves the real verifier *is* competent: that the live
model scores a **transform-bound** answer for a changed value **low** ("Hola." for "goodbye") and a
**value-independent** parameterised answer **high** ("...within 30 days." for a different order). It
is the F4 lesson made operational — verification (the gate routes) is not validation (the model is
actually right). If the model scores "Hola." high, the model is the weak link and you see it here.

Self-skips when the verifier endpoint is unreachable (mirrors ``tests/test_backend_live.py``). Run::

    uv run python evals/verify_live.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

# Allow direct invocation (`python evals/verify_live.py`) as well as `python -m evals.verify_live`:
# the former puts evals/ on sys.path, not the project root, so the `evals` package import fails.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.dataset import EVAL_CASES  # noqa: E402
from gateway.adapters.verifier import ModelVerifier  # noqa: E402
from gateway.config import get_settings  # noqa: E402


async def _main() -> int:
    # Windows consoles default to cp1252; the arrows and the cached answers (€, ≈) are UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

    settings = get_settings()
    # Only the value-changed, non-echoing cases reach the Verifier — they carry a verify_score.
    cases = [c for c in EVAL_CASES if c.verify_score is not None]

    async with httpx.AsyncClient(
        base_url=settings.verifier_base_url,
        timeout=settings.verifier_timeout,
    ) as client:
        # ModelVerifier swallows transport errors and returns 0.0, so probe reachability directly.
        try:
            await client.get("/models")
        except (httpx.ConnectError, httpx.TransportError) as exc:
            print(f"SKIP: verifier model not reachable at {settings.verifier_base_url}: {exc}")
            return 0

        verifier = ModelVerifier(
            client,
            settings.verifier_model,
            settings.verifier_api_key.get_secret_value() or None,
        )

        print(f"\n=== Live Verifier check ({settings.verifier_model}) ===")
        print("expect refuse → want a LOW score; expect serve → want a HIGH score\n")
        print(f"{'id':<22} {'expect':<7} {'score':>6}  question → cached answer")
        print("-" * 88)
        for case in cases:
            score = await verifier.verify(case.new_question, case.cached_answer)
            print(
                f"{case.id:<22} {case.expected:<7} {score:>6.2f}  "
                f"{case.new_question!r} → {case.cached_answer!r}"
            )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
