"""Unit tests for IntentGate and RegexIntentExtractor — no DB, no model."""

from __future__ import annotations

import pytest

from gateway.domain.models import IntentCandidate
from gateway.services.intent_extractor import RegexIntentExtractor
from gateway.services.intent_gate import IntentGate, _answer_echoes_param
from tests.conftest import FakeVerifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gate(verifier: FakeVerifier | None = None, *, verifier_score: float = 0.0) -> IntentGate:
    return IntentGate(
        verifier or FakeVerifier(score=verifier_score),
        margin_min=0.05,
        staleness_max_seconds=3600.0,
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
# IntentGate: cheap-signal refusals (no model call, confidence None)
# ---------------------------------------------------------------------------


async def test_empty_candidates_refuses() -> None:
    verdict = await _gate().evaluate("question?", [], [])
    assert verdict.serve is False
    assert verdict.confidence is None


async def test_stale_entry_refuses() -> None:
    old = _candidate(age_seconds=9999.0)  # well over 3600s staleness_max
    verdict = await _gate().evaluate("question?", [], [old])
    assert verdict.serve is False
    assert verdict.confidence is None


async def test_low_margin_refuses() -> None:
    # top1 = 0.97, top2 = 0.93 → margin = 0.04 < margin_min 0.05
    top1 = _candidate(similarity=0.97)
    top2 = _candidate(similarity=0.93)
    verdict = await _gate().evaluate("question?", [], [top1, top2])
    assert verdict.serve is False
    assert verdict.confidence is None


# ---------------------------------------------------------------------------
# IntentGate: cheap-signal serves (no model call, confidence None)
# ---------------------------------------------------------------------------


async def test_value_independent_answer_serves_without_verifier() -> None:
    # Paramless cached answer → reusable across any value; serves on cheap signals alone.
    v = FakeVerifier(score=0.95)
    top1 = _candidate(response="Return within 30 days.", parameters=[], similarity=0.99)
    top2 = _candidate(similarity=0.80)
    verdict = await _gate(v).evaluate("How do I return an item?", ["anything"], [top1, top2])
    assert verdict.serve is True
    assert verdict.confidence is None
    assert v.calls == 0  # the model is never consulted for a value-independent answer


async def test_same_value_serves_without_verifier() -> None:
    # Cached parameters == incoming parameters → the answer was generated for this exact input.
    v = FakeVerifier(score=0.0)
    top1 = _candidate(response="Order status: shipped.", parameters=["1111"], similarity=0.99)
    top2 = _candidate(similarity=0.80)
    verdict = await _gate(v).evaluate("Where is order 1111?", ["1111"], [top1, top2])
    assert verdict.serve is True
    assert verdict.confidence is None
    assert v.calls == 0


async def test_same_value_serves_ignoring_case_and_whitespace() -> None:
    # Parameter comparison is normalised (set, lowercased, stripped) — D32.
    v = FakeVerifier(score=0.0)
    top1 = _candidate(response="Delivered.", parameters=["ORD-500"], similarity=0.99)
    top2 = _candidate(similarity=0.80)
    verdict = await _gate(v).evaluate("status of ord-500?", [" ord-500 "], [top1, top2])
    assert verdict.serve is True
    assert v.calls == 0


# ---------------------------------------------------------------------------
# IntentGate: value changed
# ---------------------------------------------------------------------------


async def test_value_mismatch_echoing_answer_reject_fast() -> None:
    # Answer echoes the old value → provably bound → reject-fast, model NOT consulted even though
    # the (irrelevant) verifier would have passed.
    v = FakeVerifier(score=0.95)
    candidate = _candidate(
        response="Order 1111 ships Thursday.", parameters=["1111"], similarity=0.97
    )
    top2 = _candidate(similarity=0.80)
    verdict = await _gate(v).evaluate("Where is order 2222?", ["2222"], [candidate, top2])
    assert verdict.serve is False
    assert verdict.confidence is None
    assert v.calls == 0


async def test_value_mismatch_nonechoing_answer_serves_on_high_verify() -> None:
    # Possible transform (answer shares no letters with the value) → Verifier; high → serve.
    v = FakeVerifier(score=0.95)
    candidate = _candidate(response="Hola.", parameters=["hello"], similarity=0.97)
    top2 = _candidate(similarity=0.80)
    verdict = await _gate(v).evaluate(
        "Translate 'goodbye' to Spanish.", ["goodbye"], [candidate, top2]
    )
    assert verdict.serve is True
    assert verdict.confidence == 0.95  # the Verifier's score, recorded verbatim (D34)
    assert verdict.candidate is candidate
    assert v.calls == 1


async def test_value_mismatch_nonechoing_answer_refuses_on_low_verify() -> None:
    # The F5 hole, now closed: transform answer + changed value → Verifier; low → refuse.
    v = FakeVerifier(score=0.10)
    candidate = _candidate(response="Hola.", parameters=["hello"], similarity=0.97)
    top2 = _candidate(similarity=0.80)
    verdict = await _gate(v).evaluate(
        "Translate 'goodbye' to Spanish.", ["goodbye"], [candidate, top2]
    )
    assert verdict.serve is False
    assert verdict.confidence == 0.10  # score recorded even on refuse
    assert verdict.candidate is None
    assert v.calls == 1


# ---------------------------------------------------------------------------
# _answer_echoes_param helper (reject-fast signal only)
# ---------------------------------------------------------------------------


def test_answer_echoes_param_true_when_param_in_response() -> None:
    c = _candidate(response="Order 1111 ships Thursday.", parameters=["1111"])
    assert _answer_echoes_param(c) is True


def test_answer_echoes_param_false_when_param_not_in_response() -> None:
    c = _candidate(response="Return within 30 days.", parameters=["1111"])
    assert _answer_echoes_param(c) is False


def test_answer_echoes_param_false_with_no_parameters() -> None:
    c = _candidate(response="Some generic answer.", parameters=[])
    assert _answer_echoes_param(c) is False


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
