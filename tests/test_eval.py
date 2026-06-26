"""Pytest entry-point for the D30 eval.

Runs the adversarial labeled set through the gate and asserts the showpiece headline:
  cosine-only baseline → several false serves;  gate → 0.

The labeled set carries a per-case ``cosine`` (the score a real bge-small embedder assigns each
pair), so the offline run reproduces the real contrast without loading the model.
"""

from __future__ import annotations

import pytest
from evals.run_eval import run_eval


@pytest.mark.asyncio
async def test_gate_false_serves_zero() -> None:
    """Gate must produce zero false serves on the adversarial set (D30) — the dangerous error."""
    results = await run_eval()
    false_serves = [r for r in results if r.gate_false_serve]
    assert false_serves == [], f"Gate produced {len(false_serves)} false serve(s): " + ", ".join(
        r.case_id for r in false_serves
    )


@pytest.mark.asyncio
async def test_baseline_produces_false_serves() -> None:
    """The cosine-only baseline must false-serve the surface-close cases (the contrast, D30).

    This is the headline exhibit: the baseline serves the #1111-for-#2222 family because their
    cosine is ~0.97+, while the gate refuses them (reject-fast on an echoed value, or — for a
    transform — because the Verifier scores the reuse low).
    """
    results = await run_eval()
    baseline_false_serves = [r for r in results if r.baseline_false_serve]
    gate_false_serves = [r for r in results if r.gate_false_serve]
    assert len(baseline_false_serves) >= 1, "Eval set no longer exercises the false-serve failure."
    assert len(baseline_false_serves) > len(gate_false_serves), (
        "Gate must beat the cosine-only baseline on false serves (the dangerous axis)."
    )


@pytest.mark.asyncio
async def test_gate_serves_surface_distant_cases() -> None:
    """Gate must serve the surface-distant, answer-same cases the baseline misses.

    These are paramless, generic answers worded very differently from the cached prompt: cosine
    sits below the 0.97 baseline (so the baseline false-refuses), but the gate serves them because
    they are unbound and fresh — generalizing across phrasing, which the baseline cannot.
    """
    results = await run_eval()
    gate_false_refuses = [r for r in results if r.gate_false_refuse]
    assert gate_false_refuses == [], (
        f"Gate refused serve-able cases: {', '.join(r.case_id for r in gate_false_refuses)}"
    )
