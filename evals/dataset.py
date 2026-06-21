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
    """One adversarial eval case."""

    id: str
    cached_question: str
    cached_answer: str
    cached_parameters: list[str]
    new_question: str
    expected: str  # "serve" | "refuse"
    note: str


EVAL_CASES: list[EvalCase] = [
    # --- SURFACE-CLOSE, ANSWER-DIFFERENT (should refuse) ---
    EvalCase(
        id="order-tracking-1",
        cached_question="Where is order 1111?",
        cached_answer="Order 1111 is scheduled to ship on Thursday, June 26.",
        cached_parameters=["1111"],
        new_question="Where is order 2222?",
        expected="refuse",
        note="Answer is bound to order number 1111; serving it for 2222 is factually wrong.",
    ),
    EvalCase(
        id="order-tracking-2",
        cached_question="What is the status of order ORD-500?",
        cached_answer="Order ORD-500 was delivered on June 19.",
        cached_parameters=["ORD-500"],
        new_question="What is the status of order ORD-501?",
        expected="refuse",
        note="Answer bound to ORD-500; ORD-501 may have a different status.",
    ),
    EvalCase(
        id="translation-1",
        cached_question="Translate 'hello' to Spanish.",
        cached_answer="'Hello' in Spanish is 'Hola'.",
        cached_parameters=[],
        new_question="Translate 'goodbye' to Spanish.",
        expected="refuse",
        note=(
            "Even though parameters=[] (no extraction), the answer is implicitly bound to 'hello'. "
            "The gate's binding check (answer contains the thing asked about) catches this."
        ),
    ),
    EvalCase(
        id="account-balance-1",
        cached_question="What is the balance on account ACC-9001?",
        cached_answer="Account ACC-9001 has a balance of $3,421.50.",
        cached_parameters=["ACC-9001"],
        new_question="What is the balance on account ACC-9002?",
        expected="refuse",
        note="Balance is account-specific; cross-serving is wrong.",
    ),
    # --- SURFACE-DISTANT, ANSWER-SAME (should serve) ---
    EvalCase(
        id="return-policy-1",
        cached_question="How do I return an item I ordered?",
        cached_answer="You can return any item within 30 days for a full refund. "
        "Go to Orders → Return, print the label, and drop it off.",
        cached_parameters=[],
        new_question="ugh how do I send something back that I bought",
        expected="serve",
        note="Completely different wording, but the same generic return policy answers both.",
    ),
    EvalCase(
        id="return-policy-2",
        cached_question="What is the refund window?",
        cached_answer="Our refund window is 30 days from the date of purchase.",
        cached_parameters=[],
        new_question="How many days do I have to get my money back?",
        expected="serve",
        note="Different framing of the same paramless policy question.",
    ),
    EvalCase(
        id="python-reverse-string-1",
        cached_question="Python snippet to reverse a string",
        cached_answer="```python\ns = 'hello'\nreversed_s = s[::-1]\n```",
        cached_parameters=[],
        new_question="how do I flip a string around in python, code pls",
        expected="serve",
        note="Idiomatic code answer is paramless and correct for both phrasings.",
    ),
    EvalCase(
        id="api-integration-1",
        cached_question="How do I connect my account to Salesforce?",
        cached_answer="Go to Settings → Integrations → Salesforce, click Connect, "
        "and authorize with your Salesforce admin credentials.",
        cached_parameters=[],
        new_question="Steps to link Salesforce to my workspace?",
        expected="serve",
        note="Integration walkthrough is paramless and reusable across phrasings.",
    ),
]
