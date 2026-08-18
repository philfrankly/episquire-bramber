# 10 — Retrieval over the claim store: candidate generation and the assistant surface

**Status: RULED TO SPEC 2026-08-07; design record, nothing built.** The founder ruled that four
things enter the roadmap as product features: a retrieval-backed claims feed, contradiction-aware
serving, graph traversal for the project-assistant use case, and a faithfulness eval tier —
composed through an agentic retrieval surface. The ruling's boundary — retrieval nominates,
agents and humans decide, recorded provenance asserts — is captured in
the 2026-08-07 ruling *retrieval enters as candidate generation only*; this spec is the design.
**Depends on:** `specs/09` (the shared store everything here selects over), `specs/07` §3.2 (the
merge asymmetry nothing here may violate), `specs/04` (the scaling context), the eval queue
(the open defects Phase 4 answers — read it before touching Phase 4).
**Explicitly out of scope, by ruling:** automatic community summaries or any machine-synthesized
framing tier (it would compete with human-gated views, and views are the only framing artifact);
similarity-threshold merging of any kind (specs/07 §3.2 stands); any change to
`bramber/engine/` (§9).

---

## 1. The problem: the cost law is O(N) in scans and O(N²) in tokens

The corroboration discipline requires the scanning agent to read every key already minted before
scanning source N (`bramber claims`, fed by `scan.known_claims`). The feed grows with the corpus,
so each scan pays O(K) context where K ≈ O(N), and a full corpus run pays **O(N²) total tokens**
even though it performs O(N) source reads. The cost structure that is the product — extraction is
O(sources) — holds for source reads and silently fails for context tokens.

Illustrative arithmetic at ~35 tokens per feed entry (key + statement + source list): 1,000 keys
is ~35k tokens per scan, already the dominant context item. 5,000 keys is ~175k, at the practical
window. 12,000 keys — roughly 500 sources at 40 claims each with 60% novelty — does not fit at
all. And **recall fails before capacity does**: "is there an equivalent key among 12,000?" is
needle-in-haystack matching, and every miss is a near-duplicate mint — corroboration silently
unrecorded, a support count understated. That is the product's core signal eroding as a slow
drizzle nobody sees: the claims-store analogue of the synonym-tag topic split `specs/09` §7
already names as the failure to watch. Verbose sources multiply the work again — the matching
task is (claims in this source) × (keys in the corpus).

## 2. The governing principle: nominate, decide, assert

Everything in this spec obeys one rule, stated once:

> **Embeddings and inferred adjacency may nominate. Only an agent or a human decides. Only
> recorded provenance asserts.**

`specs/07` §3.2 rejected similarity **dedup** because there the threshold *is* the merge
decision: negation is invisible to embeddings, and a false merge fabricates attribution — the
failure that destroys a product whose artifact is cited provenance. Candidate **generation** sits
on the other side of that asymmetry, and each clause of the rejection inverts:

- The embedding only nominates; the agent reads the candidate's actual statement and decides.
  Mint-or-reuse stays an explicit, recorded decision — the audit property is kept, not traded.
- Negation blindness flips from hazard to feature. "The deadline is confirmed" retrieving "the
  deadline is *not* confirmed" as a candidate is what you want: the agent refuses the reuse and
  now knows to record a `## Contradictions` entry. Near-identical-but-negated pairs are
  contradiction candidates, surfaced at the one moment somebody is looking.
- The residual risk is a *missed* candidate → near-duplicate mint → under-merge: the direction
  the design already accepts as visible-and-correctable, and the direction the full feed
  converges to anyway at scale through attention degradation. Top-k retrieval over thousands of
  short texts out-recalls a language model scanning a list of the same size, so against the
  status quo at scale this removes a failure mode rather than adding one.
- Auditability improves. Today a near-duplicate mint is indistinguishable from a considered
  mint. With retrieval, the shown-candidate list is trace-recorded, so "the agent saw CLAIM-007
  and minted anyway" becomes evidence instead of an unknowable.

The ladder, for any future argument about where a mechanism may sit: **full feed** (recall
degrades, then collapses, with K) → **retrieval shortlist** (bounded context, roughly constant
recall, the agent still decides) → **similarity threshold** (no decision-maker — forbidden, and
stays forbidden).

## 3. Phase 0 — contradiction-aware serving (deterministic, no new dependencies)

**Product rule: any surface that returns a claim can also return the tensions citing it.**

A query primitive `contradictions_for(claim_key)`: every contradiction unit whose `sides` cite
the key, with sides unioned across contributors and each side carrying its `extract_path` anchor.
This is a join over the store, not retrieval — no embeddings, no new dependency — and it reuses
`meta.contradiction_register` (`bramber/meta.py`), never reimplementing the merge, so support
counts and side-unioning cannot drift from the register.

Why it is Phase 0: it ships standalone value at today's corpus size, and it proves the
tension-aware serving behaviour before any index exists to argue about. A consumer that reads
CLAIM-007 and is not shown that CONTRA-001 contests it has been handed one side of a recorded
disagreement — the silent-averaging failure every conventional retrieval stack has, present here
only until this join is wired to the serving path.

Adjacent record: the contradiction-derived candidate pool (zero API cost) in
the 2026-08-05 ruling *cross source claims and the citation count stratifier* reads the same
structures; Phase 0's primitive should be written so that analysis can consume it.

**Verify:** unit tests over a fixture corpus — a two-source tension returns both sides through
the primitive; a claim with no citing contradiction returns empty, not error. No paid step.

## 4. Phase 1 — the candidate index and the retrieval-backed claims feed (the scaling fix)

**The feed becomes a retrieval endpoint serving top-k candidates instead of the universe.**

### 4.1 The index

Hybrid: API embeddings over claim statements plus a stdlib keyword match over statements,
topics, entity names and aliases (the keyword half catches exact terms the embedding fuzzes
over, and costs no dependency). Built from `_bramber/scans` / `_bramber/units` on disk — **a
rebuildable cache with exactly `bramber.db`'s status**: disk is truth, losing the index is a
non-event, `rebuild` regenerates it. Incremental by construction: a new scan embeds only its own
claims; `content_sha` supplies invalidation. Brute-force cosine over tens of thousands of short
vectors is sub-second in pure Python, so no vector-store dependency is taken at this scale — the
embedding API is the only true dependency, held behind a lazy `[embed]` extra mirroring `[mcp]`
(provider chosen at implementation time; confirm current Anthropic guidance — the partnership
has been with Voyage).

> **[Superseded 2026-08-08 — the 2026-08-08 ruling *embeddings run on a local model*.]** There
> is no embedding *API* and no provider: embedding runs **locally and in-process** (`fastembed`,
> ONNX), so the corpus never leaves the machine. This paragraph's shape survives — one true
> dependency, lazy `[embed]` extra mirroring `[mcp]`, brute-force cosine, rebuildable cache —
> only its hosted-provider assumption is withdrawn. §208 of `specs/00` had already recorded the
> constraint that decides it: in-perimeter clients may forbid egress.

### 4.2 The two feed shapes

- **Shape A — query per claim.** The agent drafts a statement and calls
  `bramber claims --like "<statement>"` → the ~10 nearest keys with statements and asserting
  sources. Highest precision: the query is claim-shaped and so is the index, a form-match other
  retrieval stacks have to manufacture. The escape hatch and the corroboration workhorse.
- **Shape B — pre-scan candidate pack.** Embed the extract's sections, retrieve the ~100–300
  keys similar to any of them, hand the agent one pre-filtered feed with no mid-scan
  round-trips. Coarser; fits the current one-shot scan flow. The bulk path.

Either shape makes the scan's context cost roughly constant in corpus size, restoring O(N)
total tokens. `bramber claims` with no argument keeps its current meaning (the full feed) — small
corpora and audits still want the universe, and the full feed is the fallback when `[embed]` is
absent, so **the discipline degrades gracefully rather than gaining a hard dependency**.

### 4.3 What Phase 1 records and does not solve

The sequential-digestion defect (the eval queue: concurrent scans read the same high-water
mark and mint colliding keys, corrupting support silently) is orthogonal — the index changes what
the agent is *shown*, not how keys are *allocated*. Its fix (allocation under a lock, or
content-derived keys) is a separate ruling; this spec cites the defect so nobody mistakes Phase 1
for that fix. Note the interaction: content-derived keys, if ever ruled, change what the index
indexes but nothing about this design.

**Verify (unpaid):** recall replay — hold out sources whose existing scans recorded reuses under
the full-feed regime; re-run retrieval for each reused claim; measure how often the correct key
appears in the shortlist. Plus a paraphrase-injection mutation check: inject reworded duplicates
of known claims and confirm they surface. Both run without a paid generation step and belong in
`evals/` under the QUEUE.md discipline.

## 5. Phase 2 — graph expansion and store hygiene (the index pointed inward)

### 5.1 Traversal as a retrieval primitive

Expansion over relationships the record already contains: claim↔source (provenance),
unit↔topic, contradiction↔claim (`sides`), term↔entity (`relates_to`), entity↔aliases.
Co-occurrence adjacency (same source + shared topic) is permitted **for nomination only** — a
unit found through an inferred hop is returned on its own recorded provenance, and the hop is
never presented as an edge the record asserts. This is `meta.py`'s no-inferred-renderer stance
applied to retrieval: the renderers refuse to draw inferred edges because a diagram asserts;
traversal may *follow* an inferred adjacency precisely because a retrieved unit asserts nothing
the store does not already pin.

### 5.2 Hygiene: three nomination queues, one human gate

The same index pointed at the store itself, with every output filed as an evaluation proposal
(`_bramber/evaluations/`, FORMAT-SPEC shape) for `/bramber:evaluate` — never auto-applied:

- **Merge proposals** — near-duplicate claim pairs (high similarity, distinct keys). The agent
  or founder rules merge / keep-apart / contradiction; a rejected proposal is itself a record
  that the pair was examined.
- **Topic-drift detection** — `specs/09` §7 defers a topic registry "until drift is observed";
  an embedding pass over the tag vocabulary is the observer. A synonym tag that would split a
  topic silently becomes a filed proposal instead of an invisible loss.
- **Alias suggestions** — two entity keys with high similarity and overlapping topics propose an
  `aliases` entry. `_norm_key` stays deliberately dumb; the suggestion queue is where the
  under-merges it accepts get examined instead of merely tolerated.

**Verify:** fixture corpus with planted near-duplicates, a synonym tag pair, and an alias pair —
each lands in the proposal queue with its evidence; nothing is applied without
`/bramber:evaluate`. No paid step.

## 6. Phase 3 — the agentic retrieval surface (MCP)

The delivery surface composing Phases 0–2 for the project-assistant use case. Read-only tools:

- `search_units` — hybrid query plus `match.<field>` filters, reusing the selector's generic
  predicate vocabulary (`compile._field_matches`) so the retrieval filter and the view selector
  cannot drift in semantics.
- `contradictions_for` — Phase 0's primitive, served.
- `expand` — Phase 2's traversal, from a unit key outward, depth-bounded.
- Drill-down — resource → contributing units → sources, over existing lineage
  (`resource_lineage` already serves the last hop).

**Placement, decided here:** not `bramber/engine/server.py`. The engine is domain-blind and
stdlib-only, and `bramber.db` does not index units — the unit store lives on disk. The tools
live at the `compile.py` layer (domain-blind by correction): a sibling retrieval module plus its
own MCP registration behind the `[embed]` extra. `engine/server.py` stays untouched;
`tests/test_seam.py` must stay green with no new exemptions. An assistant session composes the
two servers: deterministic drill-down from the engine's surface, probabilistic search from this
one — which is the whole design: the compiled views answer the questions a human anticipated,
this surface answers the ones nobody did, and both cite the same store.

**Verify:** an end-to-end assistant transcript over a throwaway root — question → `search_units`
→ `contradictions_for` on a hit → drill to source — with every returned unit's citation
resolving on disk. Scriptable; no paid judging.

## 7. Phase 4 — mechanical faithfulness and the judged tier (through QUEUE.md)

Two tiers, deliberately unequal in what they may claim.

- **Mechanical tier (unpaid, structural).** Every citation resolves: claim key exists in the
  store, cited extract appears in the unit's provenance, every contradiction side's
  `extract_path` exists. Runs on every compile and on every retrieval answer. **This tier is a
  tripwire, not a result**: QUEUE.md already records that citation resolution 1.00 is structural
  for the deterministic compile and separates bramber from nothing. Its value is catching
  regressions on the agent-authored path and on retrieval answers, where resolution is not
  structural.
- **Judged tier (paid).** Per-(claim, cited-source) entailment — which is exactly Layer C's pair
  judging, extended into the store: an **entailment-checked support count** (`support_verified`
  alongside `support`) is the fix shape for QUEUE.md's standing defect "*`support` counts
  sources that do not support*" (five silent citations in the first hundred pairs, two claims
  whose only cited source is silent). Preconditions, all already on the record and honored
  here: fold retry-with-backoff and checkpointing into `judge_faithfulness` before another paid
  hour; the T3 harness restaging blocks any paid run; costs from the measured 11.4 s/call table
  with concurrency as the untouched lever; the cross-source pair-unit blindness and its
  matched-both-ways design note (`decisions/2026-08-05-…-stratifier.md`) constrain the sampling
  design; ground-truth specifics never restated — pointers only, the leak tripwire is the
  tripwire.
- **Left alone on purpose:** the Layer B fabrication check and its deliberately-pinned MISS
  test. The judged tier supersedes that check's blind spot; strengthening the token-membership
  check in place is explicitly not the path, and the pinning test exists to make that a choice
  rather than an accident.

**Verify:** the mechanical tier is its own test surface. The judged tier's design lands in
the evaluation spec and is priced through QUEUE.md before any run — this spec deliberately does not
schedule a paid run.

## 8. Order and what each phase buys alone

0 ships tension-aware serving with no new dependency. 1 removes the scaling ceiling on the
corroboration discipline and builds the only new infrastructure (the index). 2 reuses the index
inward for store hygiene. 3 composes 0–2 into the assistant surface. 4 makes the store's headline
numbers checkable. Each phase is independently shippable and independently valuable; nothing
later is load-bearing for anything earlier.

## 9. Constraints (binding on every phase)

- **The engine does not change.** `bramber/engine/` stays domain-blind and stdlib-only; nothing
  here adds a table, a column, or an import to it. Everything lands at the `compile.py` layer or
  outside the package, behind lazy imports. The Stop hook (`bramber sync`) must never fail on a
  missing dependency — `[embed]` absent means the full feed and no retrieval tools, never an
  error.
- **The cost law is preserved.** Index build is O(units), incremental on new sources, zero
  source re-reads. Adding a view still costs zero source reads and now also zero re-embedding.
- **The index is never the source of truth.** Disk is truth (invariant 3); the index is a
  rebuildable cache, and losing it is a non-event.
- **Vocabulary:** "retrieval", "candidate", "index", "shortlist". Withdrawn words stay
  withdrawn.
- **Nominate / decide / assert (§2)** governs any mechanism added under this spec later — a
  proposed feature that lets a similarity score make a merge, a support increment, or an edge
  assertion is out of scope by ruling, not by taste.
