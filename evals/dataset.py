"""Adversarial labeled eval set for the intent gate (D30).

Each case is (cached_entry, new_question, expected_verdict).

The set is deliberately adversarial — it is designed to stress the failure modes that a naive
cosine-threshold baseline produces (see SLICE3_PRD.md):

  SURFACE-CLOSE, ANSWER-DIFFERENT: The two prompts score ~0.97 cosine because they differ by
  only one token (the parameter). The cached answer is bound to that token → a cosine-only
  baseline would false-serve; the gate must refuse.

  SURFACE-DISTANT, ANSWER-SAME: The cached and new prompts are worded very differently, landing
  far below the 0.97 cosine threshold. But the cached answer is generic and fully answers the
  new question → the gate should serve even though similarity is low.

The same set calibrates the gate thresholds (D26) and runs the baseline comparison (D30).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One adversarial eval case.

    ``cosine`` is the similarity a real 384-dim embedder (bge-small) assigns the
    ``cached_question`` / ``new_question`` pair on the *stripped* canonical form. It is part of the
    hand-labeled adversarial design, not computed offline: the surface-close cases score ~0.97+
    (single-token difference), the surface-distant cases score low. It drives both the gate's
    candidate similarity and the cosine-only baseline, so the offline harness reproduces the real
    contrast without needing the model loaded. (Re-run against a live embedder to confirm.)

    ``new_parameters`` are the parameters the extractor pulls from ``new_question`` — what the gate
    compares against ``cached_parameters`` to decide value-independent / same-value / value-changed
    (D32). ``verify_score`` is the score the mock model returns *if* the gate reaches the Verifier
    for this case (the value-changed, non-echoing path); cheap-path cases ignore it. ``None`` means
    the case is never expected to reach the model.
    """

    id: str
    cached_question: str
    cached_answer: str
    cached_parameters: list[str]
    new_question: str
    new_parameters: list[str]
    expected: str  # "serve" | "refuse"
    cosine: float
    note: str
    verify_score: float | None = None


EVAL_CASES: list[EvalCase] = [
    # --- SURFACE-CLOSE, ANSWER ECHOES THE VALUE → reject-fast (should refuse, no model call) ---
    EvalCase(
        id="order-tracking-1",
        cached_question="Where is order 1111?",
        cached_answer="Order 1111 is scheduled to ship on Thursday, June 26.",
        cached_parameters=["1111"],
        new_question="Where is order 2222?",
        new_parameters=["2222"],
        expected="refuse",
        cosine=0.98,  # one digit differs → near-identical in embedding space
        note="Value changed (1111→2222); answer echoes 1111 → reject-fast, no Verifier call.",
    ),
    EvalCase(
        id="order-tracking-2",
        cached_question="What is the status of order ORD-500?",
        cached_answer="Order ORD-500 was delivered on June 19.",
        cached_parameters=["ORD-500"],
        new_question="What is the status of order ORD-501?",
        new_parameters=["ORD-501"],
        expected="refuse",
        cosine=0.97,
        note="Answer echoes ORD-500 → reject-fast; ORD-501 may have a different status.",
    ),
    EvalCase(
        id="translation-1",
        cached_question="Translate 'hello' to Spanish.",
        cached_answer="'Hello' in Spanish is 'Hola'.",
        cached_parameters=["hello"],
        new_question="Translate 'goodbye' to Spanish.",
        new_parameters=["goodbye"],
        expected="refuse",
        cosine=0.97,
        note=(
            "The cached answer reuses the stripped literal ('Hello') → echoes the old value → "
            "reject-fast (no Verifier call). Contrast translate-transform, whose answer ('Hola.') "
            "does NOT echo and so must go through the Verifier."
        ),
    ),
    EvalCase(
        id="account-balance-1",
        cached_question="What is the balance on account ACC-9001?",
        cached_answer="Account ACC-9001 has a balance of $3,421.50.",
        cached_parameters=["ACC-9001"],
        new_question="What is the balance on account ACC-9002?",
        new_parameters=["ACC-9002"],
        expected="refuse",
        cosine=0.98,
        note="Answer echoes ACC-9001 → reject-fast; balance is account-specific.",
    ),
    # --- TRANSFORM-BOUND: value changed, answer does NOT echo → Verifier called, low → refuse ---
    # The F5-closing cases: a substring test cannot see the binding, so the model must.
    EvalCase(
        id="translate-transform",
        cached_question="Translate 'hello' to Spanish.",
        cached_answer="Hola.",
        cached_parameters=["hello"],
        new_question="Translate 'goodbye' to Spanish.",
        new_parameters=["goodbye"],
        expected="refuse",
        cosine=0.98,
        verify_score=0.1,
        note="The exact proven hole: 'Hola.' shares no letters with 'hello' → Verifier → refuse.",
    ),
    EvalCase(
        id="define-transform",
        cached_question="Define 'ephemeral'.",
        cached_answer="Lasting a very short time.",
        cached_parameters=["ephemeral"],
        new_question="Define 'gregarious'.",
        new_parameters=["gregarious"],
        expected="refuse",
        cosine=0.98,
        verify_score=0.1,
        note="Definition is bound to the word; answer doesn't echo it → Verifier refuses.",
    ),
    EvalCase(
        id="arithmetic-transform",
        cached_question="What is 7 times 8?",
        cached_answer="56.",
        cached_parameters=["7", "8"],
        new_question="What is 6 times 9?",
        new_parameters=["6", "9"],
        expected="refuse",
        cosine=0.98,
        verify_score=0.1,
        note="'56.' is bound to 7×8 but echoes neither operand → Verifier → refuse (54 ≠ 56).",
    ),
    EvalCase(
        id="convert-transform",
        cached_question="Convert 10 USD to EUR.",
        cached_answer="≈ €9.20.",
        cached_parameters=["10"],
        new_question="Convert 50 USD to EUR.",
        new_parameters=["50"],
        expected="refuse",
        cosine=0.98,
        verify_score=0.1,
        note="Converted amount is bound to 10; answer doesn't echo it → Verifier refuses.",
    ),
    # --- VALUE-INDEPENDENT but PARAMETERISED: value changed, no echo → Verifier → serve ---
    # The win cosine can't take: the answer generalises across the value, and only the model knows.
    EvalCase(
        id="return-policy-order",
        cached_question="Return policy for order #1111?",
        cached_answer="All orders can be returned within 30 days.",
        cached_parameters=["1111"],
        new_question="Return policy for order #2222?",
        new_parameters=["2222"],
        expected="serve",
        cosine=0.98,
        verify_score=0.9,
        note="Answer never used the order number → generalises; Verifier confirms → serve.",
    ),
    EvalCase(
        id="password-reset",
        cached_question="How do I reset the password for account ACC-9001?",
        cached_answer="Go to Settings → Security → Reset.",
        cached_parameters=["ACC-9001"],
        new_question="How do I reset the password for account ACC-9002?",
        new_parameters=["ACC-9002"],
        expected="serve",
        cosine=0.98,
        verify_score=0.9,
        note="Reset steps are the same for any account → Verifier confirms → serve.",
    ),
    # --- SURFACE-DISTANT, PARAMLESS, ANSWER-SAME (should serve on cheap signals, no model call) ---
    EvalCase(
        id="return-policy-1",
        cached_question="How do I return an item I ordered?",
        cached_answer="You can return any item within 30 days for a full refund. "
        "Go to Orders → Return, print the label, and drop it off.",
        cached_parameters=[],
        new_question="ugh how do I send something back that I bought",
        new_parameters=[],
        expected="serve",
        cosine=0.82,  # same intent, very different words → clears a real embedder but misses 0.97
        note="Completely different wording, but the same generic return policy answers both.",
    ),
    EvalCase(
        id="return-policy-2",
        cached_question="What is the refund window?",
        cached_answer="Our refund window is 30 days from the date of purchase.",
        cached_parameters=[],
        new_question="How many days do I have to get my money back?",
        new_parameters=[],
        expected="serve",
        cosine=0.80,
        note="Different framing of the same paramless policy question.",
    ),
    EvalCase(
        id="python-reverse-string-1",
        cached_question="Python snippet to reverse a string",
        cached_answer="```python\ns = 'hello'\nreversed_s = s[::-1]\n```",
        cached_parameters=[],
        new_question="how do I flip a string around in python, code pls",
        new_parameters=[],
        expected="serve",
        cosine=0.78,
        note="Idiomatic code answer is paramless and correct for both phrasings.",
    ),
    EvalCase(
        id="api-integration-1",
        cached_question="How do I connect my account to Salesforce?",
        cached_answer="Go to Settings → Integrations → Salesforce, click Connect, "
        "and authorize with your Salesforce admin credentials.",
        cached_parameters=[],
        new_question="Steps to link Salesforce to my workspace?",
        new_parameters=[],
        expected="serve",
        cosine=0.83,
        note="Integration walkthrough is paramless and reusable across phrasings.",
    ),
]
