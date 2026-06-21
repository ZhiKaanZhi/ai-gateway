# Slice 3 — Intent Caching

*A re-entry document. Read this in ten minutes a year from now and the whole mental model comes back. For "why did I choose X over Y," see `DECISIONS.md` (D21–D31) — this is the story those decisions add up to. For exact term definitions, see `GLOSSARY.md`.*

## The one-sentence version

Slice 3 adds a third cache tier that can reuse one answer across *differently-worded, differently-parameterized* questions — but only when a confidence gate is sure the cached answer is actually correct for the new question. Because the failure it prevents is the expensive one: serving a confidently wrong cached answer.

## The problem it solves

The gateway already had two ways to recognize a repeat question. An **exact** repeat (same words) is obvious. A **paraphrase** ("how do I return this?" vs "what's the process for sending something back?") is caught by the **semantic tier** — it embeds both prompts and serves the cached answer when they're close enough in meaning-space (cosine ≥ 0.95).

But semantic closeness is the wrong tool for the question that actually matters: *is this cached answer correct for what's being asked now?* Two failure shapes show why:

- **Surface-close, answer-different.** "Where is order #1111?" and "Where is order #2222?" differ by one digit. Cosine says ~0.97 — "basically the same." But serving #1111's shipping date for #2222 is just wrong. The one token that changed is the one the answer depends on, and similarity is blind to that.
- **Surface-distant, answer-same.** "Python snippet to reverse a string" and "ugh how do I flip a string around, code pls" drift far enough apart in wording to fall below the threshold and miss the cache — even though the same answer serves both.

The fix isn't a tighter threshold (that's the trap — and it's literally what an early note in `DECISIONS.md` D10 assumed before this slice overturned it). A tighter threshold makes the second failure worse without fixing the first. The fix is a *different signal*.

## The idea: confidence is not similarity

This is the whole thesis, and it's the line worth remembering:

- **Similarity** answers *how close are these two prompts?* — one cosine number over their embeddings. A distance.
- **Confidence** answers *how sure are we the cached answer is correct for this request?* — a decision, built from several signals, of which similarity is only one.

High similarity does not imply the same correct answer. The slice exists to build the second thing and *prove*, with numbers, that it's different from the first.

## How it works (one request, start to finish)

Three tiers run in order, cheapest and safest first. The first hit wins.

1. **Exact** — hash the normalized prompt, look it up. Instant, never wrong. Catches literal repeats without even computing an embedding.
2. **Semantic** — the existing tier. Embed the prompt, find the nearest cached prompt, serve if cosine ≥ 0.95. Catches paraphrases.
3. **Intent** — the new tier, and the only one with a brain. It does two separate things that must not be confused:
   - **Match** (find a candidate): strip the parameters out of the prompt — "where is order #1111?" becomes "where is order {N}?" — and search on *that*. So "#1111" and "#2222" both reduce to the same thing and find the same cached candidate. The bare parameter is set aside, not thrown away.
   - **Gate** (decide whether to serve it): this is where confidence lives. **Matching is not serving.** The matcher found a candidate; the gate decides if it's safe. It looks at how clearly the best match beats the runner-up, how stale the cached answer is, and — the key one — *whether the cached answer actually used the parameter*. On the uncertain cases it asks a small cheap model point-blank: "does this cached answer answer this new question?" It serves only when it's confident. Otherwise it gives up and lets the request go down the normal pipeline.

Walk the three canonical cases through the gate:

- **"How do I return order #1111?"** → later → **"How do I send back #2222?"** The cached answer is "Orders → Return → print the label." It never mentions the number. So it's correct for #2222 too. **Serve.** *(This is the win — generalizing across a parameter, which neither earlier tier can do.)*
- **"Where is order #1111?"** → later → **"Where is order #2222?"** The cached answer is "Order #1111 ships Thursday." It's built from the number. Serving it for #2222 is wrong. **Refuse → go fetch #2222 live.** *(This is the trap, avoided. Notice cosine screamed "match" at 0.97; the gate refused anyway, because it looked at whether the answer was bound to the thing that changed.)*

The discriminator is never "does the question have a parameter" (both do). It's "did the **answer** use it." That's the thing similarity structurally cannot see, and it's why this tier earns its existence instead of being the semantic tier with a bigger number.

## What we cache, and what we refuse

We cache only answers whose correctness **doesn't depend on the parameter** — return policy, refund window, "is X compatible with Y," integration how-tos. Parameters are used to *refuse* reuse, never to fill in blanks. (We considered caching templates like "Order {id} arrives {date}" and filling them per request — but to fill {date} you still have to hit the database live every time, so the cache would save the sentence and not the work. Pointless. See D22.)

The non-obvious part worth remembering: **the cache is not for easy questions.** A cache is worth exactly what it skips, and cheap FAQ answers are cheap to regenerate. The real prize is the *expensive* answer that happens to recur and doesn't go stale — a Pro-vs-Enterprise comparison, a "connect your API to Salesforce" walkthrough. The first customer pays for the big-model call; the next thousand who ask it, worded any way, get it free. That's also why the precision bias matters so much here: when a hit saves a lot, a *wrong* hit costs a lot, so the gate is tuned to refuse rather than risk it.

## How we prove it works

The deliverable isn't a demo of a few hand-picked wins — it's a **measurement**. A small, deliberately adversarial labeled set: each case is (a cached entry, a new question, the expected verdict: serve or refuse). The gate runs the set and is scored as **two separate error rates**, because the two errors are not equally bad:

- **False serves** — served when it should have refused. The dangerous one (a wrong answer to a customer).
- **False refuses** — refused when it could have served. The merely wasteful one (a cache miss).

The headline exhibit: run the *same* set through a **cosine-only baseline** — serve if similarity ≥ 0.97, no gate, exactly the naive "just raise the threshold" idea — right next to the real gate. The baseline produces several false serves (the #1111-for-#2222 cases, the translate-'hello'-for-'goodbye' cases). The gate produces zero. *Cosine-only → N false serves; gate → 0.* That one number-to-number comparison is the thesis stated as data instead of argument. The same eval set is also what's used to *tune* the gate's thresholds in the first place.

## What was deliberately left out (and where to pick it up)

- **Tool/action caching.** The cached unit stayed plain text. The wrong-tool-call scenario was kept only as the *motivating story* for why the gate biases to precision — a wrong cached *action* is worse than a wrong cached sentence — but building real tool execution is a separate, much larger subsystem.
- **Multi-provider, multi-tenancy, billing, quality scoring, Kafka.** All off the core path (tiered cache + confidence gate + fallback).
- **Multi-customer data hygiene — designed, not built, and committed as the next slice.** The intent store is global (the "hottest intentions" everyone asks). Admission writes every parameterized prompt there, including the *bound* ones like "where is #1111?" → "ships Thursday." The gate never cross-serves those (it refuses on binding), so they're never *wrong* — but they accumulate: stale customer data taking space. On the synthetic single-tenant data this slice runs against, that's harmless. In production you'd add cleanup: delete-old-entries behind the `IntentRepository` seam, fired by a background timer, with a TTL. The seam is already there *specifically so this plugs in without touching the read path* — that's the whole reason it was drawn. There's also a free refinement noted for later: when the gate refuses specifically because an answer was *bound* (not merely stale), that entry will never help anyone, so it could be evicted on the spot — the gate already computed the verdict.

## The shape of the code

Eight ports now: the original five (`EmbeddingProvider`, `CacheRepository`, `ModelBackend`, `ModelRouter`, `ComplexityClassifier`) plus three new seams — `IntentExtractor` (prompt → stripped form + parameters), `IntentRepository` (its own store and HNSW index for the stripped vectors; returns ranked candidates with their age and parameters), and `Verifier` (the "does this answer fit?" check, backed by a cheap model today but given its own seam because the *question* it answers is conceptually distinct from "call a model" — a rules engine could fill it later). The **gate is a service, not a port** — it orchestrates seams, it isn't one, same as the pipeline and the cache service. The intent store is separate from `cache_entries`, because it searches a *different* vector (the stripped one) and wants a different lifecycle (long-TTL and global, vs the semantic cache's short-TTL and per-deployment). The complexity classifier and router are still deliberate stubs.

## If you have to explain it in 60 seconds

A cache that reuses an answer across questions that *mean* the same thing even when they're worded or parameterized differently — guarded by a gate that refuses whenever the cached answer was actually tied to the specific detail that changed. Two questions about two different orders look 97% identical to a similarity score, but the gate notices the answer was built from the order number and refuses to cross-serve them. The proof is an eval set where a similarity-threshold baseline serves several wrong answers and the gate serves none.

**Intent match ≠ serve. Similarity ≠ confidence.** Everything else is detail.
