# Glossary

Domain vocabulary for the ai-gateway. Definitions are load-bearing: two terms below are the thesis of Slice 3 expressed as data instead of argument. See `DECISIONS.md` and `SLICE3_PRD.md` for the full treatment.

---

| Term | Means | Tier | Holds the distinction |
|---|---|---|---|
| **Exact hit** | Normalized prompt hash byte-identical to a stored one | exact | Same string only — no meaning involved |
| **Semantic hit** | Raw-prompt embedding within cosine threshold (≥ 0.95) of a stored prompt | semantic | "Means the same," judged on the *whole* prompt including parameters |
| **Intent match** | Stripped-prompt embedding finds a candidate — **match only, not yet served** | intent | "Same underlying ask" after parameters removed; the matcher finds, it does not authorize |
| **Confidence** | The gate's judgment that a cached answer is *correct for this request* (margin + staleness + binding + borderline verify) | intent | A **correctness** decision, not a distance — what an intent match must clear to serve |
| **Similarity** | One cosine number between two embeddings | semantic + intent | A **distance**; an *input* to confidence, never confidence itself |

---

## The two load-bearing lines

**Intent match ≠ serve.** Finding a candidate is not authorization to serve it. The gate (confidence) is a separate, subsequent decision.

**Similarity ≠ confidence.** A cosine score answers "how close are these prompts?" — a distance. Confidence answers "is this cached answer correct for this request?" — a correctness verdict built from several signals, of which similarity is only one. These two things sound related but make opposite errors: high similarity does not imply the same correct answer (order #1111 vs #2222 score ~0.97), and low similarity does not imply a wrong answer (same code answer, differently worded question). Everything else in Slice 3 is detail.
