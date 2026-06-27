# Glossary

Domain vocabulary for the ai-gateway. Definitions are load-bearing: two terms below are the thesis of Slice 3 expressed as data instead of argument. See `DECISIONS.md` and `SLICE3_PRD.md` for the full treatment.

---

| Term | Means | Tier | Holds the distinction |
|---|---|---|---|
| **Exact hit** | Normalized prompt hash byte-identical to a stored one | exact | Same string only — no meaning involved |
| **Semantic hit** | Raw-prompt embedding within cosine threshold (≥ 0.95) of a stored prompt | semantic | "Means the same," judged on the *whole* prompt including parameters |
| **Intent match** | Stripped-prompt embedding finds a candidate — **match only, not yet served** | intent | "Same underlying ask" after parameters removed; the matcher finds, it does not authorize |
| **Confidence** | The gate's correctness verdict for a cached answer. Cheap signals (staleness, margin, parameter relationship) decide most cases; on a **value mismatch with a non-echoing answer** the Verifier's score *is* the confidence. `None` when no model ran (D34) | intent | A **correctness** decision, not a distance — and `None` ≠ low confidence |
| **Similarity** | One cosine number between two embeddings | semantic + intent | A **distance**; an *input* to confidence, never confidence itself |
| **Value-bound / transform-bound** | A cached answer whose correctness depends on the parameter value. A **transform** replaces the value with its result (`"Translate 'hello'"` → `"Hola."`) rather than echoing it — so a substring test cannot detect the binding; only the Verifier can | intent | "The answer *used* the value" — the property similarity and substring both miss |
| **Reject-fast** | Cheap refuse when the cached answer text echoes a *differing* cached parameter (the old substring check). Sound as a refuse signal; **never** a serve signal — its absence does not imply independence (D32) | intent | An echoed value *is* evidence of binding; a missing echo is *not* evidence of its absence |
| **Value-independent** | A cached answer that never used a parameter (params empty) — reusable across any value or phrasing (a return-policy answer). Serves on cheap signals, no model call | intent | "The answer ignored the value" — the reuse win the lower tiers can't take |
| **Action (tool-call reply)** | A reply where the model **called a tool** rather than answering in text — it reflects live, mutable external state (an order DB), so it is **never cached** (D43–D45) | live | Tool output is a one-time live event, not reusable static knowledge — detected from the reply, never a request flag or verb |
| **Question (text reply)** | A reply that is **plain text** — reusable static knowledge, so it is **cacheable** through the three tiers | exact/semantic/intent | The complement of an action: text answers reuse, tool calls do not |

---

## The two load-bearing lines

**Intent match ≠ serve.** Finding a candidate is not authorization to serve it. The gate (confidence) is a separate, subsequent decision.

**Similarity ≠ confidence.** A cosine score answers "how close are these prompts?" — a distance. Confidence answers "is this cached answer correct for this request?" — a correctness verdict built from several signals, of which similarity is only one. These two things sound related but make opposite errors: high similarity does not imply the same correct answer (order #1111 vs #2222 score ~0.97), and low similarity does not imply a wrong answer (same code answer, differently worded question). Everything else in Slice 3 is detail.
