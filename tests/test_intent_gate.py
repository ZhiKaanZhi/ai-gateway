"""Unit tests for IntentGate and RegexIntentExtractor — no DB, no model."""

from __future__ import annotations

import pytest

from gateway.domain.models import IntentCandidate
from gateway.services.intent_extractor import RegexIntentExtractor
from gateway.services.intent_gate import IntentGate, _answer_is_bound
from tests.conftest import FakeVerifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gate(verifier_score: float = 0.0) -> IntentGate:
    return IntentGate(
        FakeVerifier(score=verifier_score),
        margin_min=0.05,
        staleness_max_seconds=3600.0,
        verify_band_lo=0.70,
        verify_band_hi=0.85,
        verify_pass_threshold=0.80,
    )


def _candidate(
    response: str = "Generic answer.",
    parameters: list[str] | None = None,
    similarity: float = 0.97,
    age_seconds: float = 100.0,
) -> IntentCandidate:
    return IntentCandidate(
        response=response,
        model_used="fake",
        similarity=similarity,
        age_seconds=age_seconds,
        parameters=parameters or [],
    )


# ---------------------------------------------------------------------------
# IntentGate: cheap signals
# ---------------------------------------------------------------------------


async def test_empty_candidates_refuses() -> None:
    verdict = await _gate().evaluate("question?", [])
    assert verdict.serve is False


async def test_stale_entry_refuses() -> None:
    old = _candidate(age_seconds=9999.0)  # well over 3600s staleness_max
    verdict = await _gate().evaluate("question?", [old])
    assert verdict.serve is False


async def test_low_margin_refuses() -> None:
    # top1 = 0.97, top2 = 0.93 → margin = 0.04 < margin_min 0.05
    top1 = _candidate(similarity=0.97)
    top2 = _candidate(similarity=0.93)
    verdict = await _gate().evaluate("question?", [top1, top2])
    assert verdict.serve is False


async def test_bound_answer_refuses() -> None:
    # Response contains the stored parameter → bound → refuse
    candidate = _candidate(
        response="Order 1111 ships Thursday.",
        parameters=["1111"],
        similarity=0.97,
    )
    top2 = _candidate(similarity=0.80)
    verdict = await _gate().evaluate("Where is order 2222?", [candidate, top2])
    assert verdict.serve is False


async def test_clear_pass_serves_generic_answer() -> None:
    # Paramless answer, high similarity, fresh, clear margin → confident serve (above band_hi)
    top1 = _candidate(response="Return within 30 days.", parameters=[], similarity=0.99)
    top2 = _candidate(similarity=0.80)
    # base_confidence = 0.5*0.99 + 0.3*staleness_score + 0.2*margin
    # staleness_score ≈ 1.0 (100s << 3600s), margin = 0.19
    # ≈ 0.495 + 0.3 + 0.038 ≈ 0.833 — rounds into the verify band, so we need verifier_score
    gate = _gate(verifier_score=0.95)
    verdict = await gate.evaluate("How do I return an item?", [top1, top2])
    assert verdict.serve is True
    assert verdict.confidence is not None


# ---------------------------------------------------------------------------
# IntentGate: borderline verify band
# ---------------------------------------------------------------------------


async def test_verify_pass_in_band_serves() -> None:
    # sim=0.90, age=300s, margin=0.15 → base = 0.5*0.90 + 0.3*(1-300/3600) + 0.2*0.15 ≈ 0.76
    # → in verify band [0.70, 0.85); verifier_score=0.95 clears verify_pass_threshold=0.80
    top1 = _candidate(similarity=0.90, age_seconds=300.0)
    top2 = _candidate(similarity=0.75)
    gate = _gate(verifier_score=0.95)
    verdict = await gate.evaluate("question?", [top1, top2])
    assert verdict.serve is True


async def test_verify_fail_in_band_refuses() -> None:
    top1 = _candidate(similarity=0.75, age_seconds=1800.0)
    top2 = _candidate(similarity=0.60)
    gate = _gate(verifier_score=0.30)  # below verify_pass_threshold 0.80
    verdict = await gate.evaluate("question?", [top1, top2])
    assert verdict.serve is False


# ---------------------------------------------------------------------------
# _answer_is_bound helper
# ---------------------------------------------------------------------------


def test_answer_is_bound_true_when_param_in_response() -> None:
    c = _candidate(response="Order 1111 ships Thursday.", parameters=["1111"])
    assert _answer_is_bound(c) is True


def test_answer_is_bound_false_when_param_not_in_response() -> None:
    c = _candidate(response="Return within 30 days.", parameters=["1111"])
    assert _answer_is_bound(c) is False


def test_answer_is_bound_false_with_no_parameters() -> None:
    c = _candidate(response="Some generic answer.", parameters=[])
    assert _answer_is_bound(c) is False


# ---------------------------------------------------------------------------
# RegexIntentExtractor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "expected_canonical_substr", "expected_params_non_empty"),
    [
        ("Where is order 1234?", "{ID}", True),
        ("Where is order #999?", "{n}", True),  # # not a word char → \b#\d+ doesn't match; 999→{N}
        ("Contact us at bob@example.com", "{EMAIL}", True),
        ("Check out https://example.com/docs", "{URL}", True),
        ("Meeting on 2024-01-15", "{DATE}", True),
        ("What is the return policy?", "return policy", False),  # no parameters
    ],
)
def test_extractor_strips_parameters(
    prompt: str, expected_canonical_substr: str, expected_params_non_empty: bool
) -> None:
    extractor = RegexIntentExtractor()
    result = extractor.extract(prompt)
    assert expected_canonical_substr.lower() in result.canonical.lower()
    if expected_params_non_empty:
        assert result.parameters  # non-empty
    else:
        assert not result.parameters


def test_extractor_normalizes_whitespace() -> None:
    extractor = RegexIntentExtractor()
    result = extractor.extract("  what   is   Python  ")
    assert result.canonical == "what is python"


def test_extractor_returns_extracted_intent_type() -> None:
    from gateway.domain.models import ExtractedIntent

    extractor = RegexIntentExtractor()
    result = extractor.extract("order 123 status?")
    assert isinstance(result, ExtractedIntent)
