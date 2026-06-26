"""Eval harness for the intent gate (D30).

Scores the gate against the adversarial labeled set (evals/dataset.py) as two separate rates:
  - False serves (dangerous): gate served when it should have refused
  - False refuses (wasteful): gate refused when it should have served

Also runs a cosine-only baseline (serve if similarity >= cosine_baseline_threshold) and reports
both side by side. The headline: cosine-only → N false serves; gate → 0.

The Verifier is mocked per-case from each case's ``verify_score`` (the score the model would return
*if* the gate reaches it — the value-changed, non-echoing path, D32). The transform cases script a
low score so the gate refuses; the value-independent-but-parameterised cases script a high score so
the gate serves. Cheap-path cases (paramless, same-value, echo reject-fast) never reach the verifier
and ignore the score. To prove the gate *routes* correctly given a competent verifier — and that the
real verifier *is* competent — run ``evals/verify_live.py`` against a live model.

Usage (offline — no DB or live model required; thresholds are loaded from config):
    uv run python -m evals.run_eval
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from evals.dataset import EVAL_CASES, EvalCase
from gateway.config import get_settings
from gateway.domain.models import IntentCandidate
from gateway.services.intent_gate import IntentGate


class _ScriptedVerifier:
    """Offline ``Verifier`` returning a per-case constant score — no live model needed.

    Defined locally (not imported from ``tests``) so ``evals`` never depends on the test package.
    """

    def __init__(self, score: float) -> None:
        self._score = score

    async def verify(self, question: str, candidate_answer: str) -> float:
        return self._score


# ---------------------------------------------------------------------------
# Cosine-only baseline (the "D10 collapsed idea")
# ---------------------------------------------------------------------------


def _cosine_only_verdict(case: EvalCase, similarity: float, threshold: float) -> str:
    """Serve if similarity >= threshold, ignoring the gate entirely."""
    return "serve" if similarity >= threshold else "refuse"


# ---------------------------------------------------------------------------
# Scoring
#
# Similarity comes from each case's labeled ``cosine`` (the score a real bge-small embedder
# assigns the pair) — see EvalCase. Driving both the gate and the baseline from the same labeled
# cosine lets the offline harness reproduce the real contrast without loading the model.
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    case_id: str
    expected: str
    gate_verdict: str
    baseline_verdict: str
    similarity: float
    note: str

    @property
    def gate_correct(self) -> bool:
        return self.gate_verdict == self.expected

    @property
    def baseline_correct(self) -> bool:
        return self.baseline_verdict == self.expected

    @property
    def gate_false_serve(self) -> bool:
        return self.expected == "refuse" and self.gate_verdict == "serve"

    @property
    def gate_false_refuse(self) -> bool:
        return self.expected == "serve" and self.gate_verdict == "refuse"

    @property
    def baseline_false_serve(self) -> bool:
        return self.expected == "refuse" and self.baseline_verdict == "serve"


async def _run_gate(case: EvalCase, gate: IntentGate) -> str:
    candidate = IntentCandidate(
        response=case.cached_answer,
        model_used="eval",
        similarity=case.cosine,
        age_seconds=60.0,  # fresh
        parameters=case.cached_parameters,
    )
    verdict = await gate.evaluate(case.new_question, case.new_parameters, [candidate])
    return "serve" if verdict.serve else "refuse"


async def run_eval() -> list[EvalResult]:
    settings = get_settings()
    results: list[EvalResult] = []
    for case in EVAL_CASES:
        # Per-case verifier: the score the model returns on the value-changed, non-echoing path.
        gate = IntentGate(
            _ScriptedVerifier(score=case.verify_score if case.verify_score is not None else 0.0),
            margin_min=settings.intent_margin_min,
            staleness_max_seconds=settings.intent_staleness_max_seconds,
            verify_pass_threshold=settings.intent_verify_pass_threshold,
        )
        gate_verdict = await _run_gate(case, gate)
        baseline_verdict = _cosine_only_verdict(
            case, case.cosine, settings.cosine_baseline_threshold
        )
        results.append(
            EvalResult(
                case_id=case.id,
                expected=case.expected,
                gate_verdict=gate_verdict,
                baseline_verdict=baseline_verdict,
                similarity=case.cosine,
                note=case.note,
            )
        )
    return results


def _print_report(results: list[EvalResult]) -> None:
    print("\n=== Intent Gate Eval (D30) ===\n")
    print(f"{'ID':<30} {'Expect':<8} {'Sim':>5}  {'Gate':<8} {'Baseline':<8} {'Gate OK':<8}")
    print("-" * 80)
    for r in results:
        ok = "OK" if r.gate_correct else "WRONG"
        print(
            f"{r.case_id:<30} {r.expected:<8} {r.similarity:>5.2f}  "
            f"{r.gate_verdict:<8} {r.baseline_verdict:<8} {ok}"
        )

    gate_false_serves = sum(r.gate_false_serve for r in results)
    gate_false_refuses = sum(r.gate_false_refuse for r in results)
    baseline_false_serves = sum(r.baseline_false_serve for r in results)

    print("\n--- Summary ---")
    print(f"Total cases:              {len(results)}")
    print(f"Gate false serves:        {gate_false_serves}  (dangerous)")
    print(f"Gate false refuses:       {gate_false_refuses}  (wasteful)")
    print(f"Cosine-only false serves: {baseline_false_serves}  (the D10 baseline)")
    print()
    if gate_false_serves == 0:
        print("HEADLINE: gate -> 0 false serves")
    else:
        print(f"gate produced {gate_false_serves} false serve(s) -- thresholds need tuning")
    if baseline_false_serves > gate_false_serves:
        print(
            f"gate beats cosine-only baseline "
            f"({baseline_false_serves} -> {gate_false_serves} false serves)"
        )
    print()


def main() -> None:
    results = asyncio.run(run_eval())
    _print_report(results)
    gate_false_serves = sum(r.gate_false_serve for r in results)
    sys.exit(0 if gate_false_serves == 0 else 1)


if __name__ == "__main__":
    main()
