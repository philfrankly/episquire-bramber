# 11 — Retrieval over the witnessed ledger: the unification brief

**Status: DESIGN BRIEF, 2026-08-07 — written for a fresh implementation session with clean
context.** Two design lines landed the same day without seeing each other: the **identity
ledger** (source-owned key namespaces, set-membership resolution, witnessed endorsements —
the 2026-08-07 ruling *identity is a ledger of judgments*, built and tested at 283 green) and
the **retrieval roadmap** (`specs/10`, ruled to spec, nothing built). This brief unifies them:
every place they reinforce each other is named and exploited; every place they grind is named
and **ruled here**, so the implementing session inherits decisions, not tensions.

**Amends `specs/10`:** §4.1 (the index derives from `_bramber/units`, never from scans — §3.G1
below) and §4.3 (the key-allocation ruling landed, and it was neither of the remedies that
section anticipated — the ledger is the fix, and its interaction with the index is settled
here). Everything else in `specs/10` stands, including its phases, its verify recipes, and its
§9 constraints, which this brief extends rather than repeats.

**Read first, in order:** the 2026-08-07 ruling *identity is a ledger of judgments* (the
theorem and the eight obligations — nothing below makes sense without it), `specs/10` (the
phases), the 2026-08-07 ruling *keys are minted in a source owned namespace* + addendum (the
allocation mechanics), the eval queue (before touching Phase 4). The ledger's enforcement
lives in `bramber/scan.py` (`resolve_keys`, `statement_token`, `known_keys`),
`bramber/ingest.py` (`materialize` — the checkpoint where every control runs), and is pinned by
`tests/test_scan_sections.py` — **every safety gate there has been mutation-verified red; new
gates join by the same rite.**

---

## 1. The one-paragraph synthesis

`specs/10`'s governing rule — *retrieval nominates, agents and humans decide, recorded
provenance asserts* — and the ledger's theorem — *sameness is an unmechanizable judgment, so
the machine owns only the ledger of judgments* — are the same boundary derived from opposite
ends. What neither session could see alone: **the ledger is what makes the retrieval layer
safe to build cheap, and the retrieval layer is what makes the ledger affordable at scale.**
A shortlist nominator can be lossy and low-precision because the decide step it feeds must
still quote the minted statement it endorses (the witness) and resolve against the minted set
— a bad nomination can cost recall, never truth. Conversely the ledger's mint-or-reuse
discipline is O(N²) in context tokens under the full feed and collapses recall at ~12k keys
(`specs/10 §1`); the shortlist restores O(N·k) and roughly constant recall. Hardening the
assert layer is the purchase price of cheap judgment everywhere upstream of it — that price is
now paid.

## 2. Mesh — where the two designs reinforce (exploit all of these)

- **M1. The allocation dependency is closed.** `specs/10 §4.3` flagged the concurrent-mint
  collision as an orthogonal open defect and hedged on its fix. Ruled since: source-owned
  namespaces + set-membership resolution + witnesses
  (`decisions/2026-08-07-keys-are-minted-…`). The index indexes **resolved, namespaced final
  keys**. No Phase 1 work item inherits the collision problem, and none may claim to fix it —
  it is fixed upstream.
- **M2. `reuse_as` is the only copy surface, everywhere.** Every feed shape — full, `--like`,
  candidate pack — serves each candidate row as `(reuse_as, statement, sources, support,
  evidence, topics)`, and the agent may copy **only** `reuse_as` as a bullet key. Key and
  witness travel as one atom per row, so a blend across rows breaks the pairing and is refused
  at materialize. This is what makes `specs/10 §4.2`'s coarse 100–300-row pack safe to serve.
- **M3. The audit claim of `specs/10 §2` gets teeth.** "The agent saw CLAIM-007 and minted
  anyway" was to be evidenced by trace-recording the shown candidates; the witness adds the
  stronger half — what was *endorsed* is content-checkable, not merely what was shown.
  Candidate-list recording is a Phase 1 deliverable (§3.G9).
- **M4. Merged-claim variants are free retrieval texts.** Each source's envelope carries that
  source's own phrasing of a reused claim, so the index gets multiple retrieval texts per
  final key with zero extra work — corroborated claims become *more* retrievable with every
  endorsement, which is exactly the right bias.
- **M5. The hygiene queues get their assert path and their cheap inputs.** `specs/10 §5.2`
  files proposals but never said how an approved merge becomes real. Answer: the ledger's
  repair doctrine — an approved merge proposal is **one token edit** (replace the later mint
  with the earlier claim's `reuse_as`) in one scan, then `materialize`. And before any
  embedding exists, the queues already have inputs: `materialize`'s `unwitnessed_keys` /
  `witness_mismatch_keys` (each a probable intended corroboration), `stray_witness_keys`,
  `singleton_topics` (the topic-drift pre-filter). *(`ambiguous_bare_keys` was listed here and is
  no longer a queue input — retired 2026-08-12; it is still computed and returned, but it groups
  by ordinal, which the protocol makes uniform across sources.)*
- **M6. Stable graph nodes.** Phase 2 traversal needs node identity that survives concurrent
  authoring; namespaced finals provide it. Contradiction sides now resolve by exact stored-key
  equality (this session's side-ref rework), which is what `contradictions_for` joins on.
- **M7. Phase 4 gains the merge-quality tier.** Queued in the eval queue (merge precision /
  corroboration recall). Note the layering: the **witness** proves the endorser quoted the
  minter (paperwork); Phase 4's `support_verified` entailment proves the endorser's *source*
  actually supports the statement (semantics). Different failure classes; report both, conflate
  never.

## 3. Grind — where they rub, ruled here

- **G1. Index source: `_bramber/units`, never scans.** Scans hold *authored* keys; resolution
  is corpus-wide and happens at materialize. An index over scans would nominate unresolved
  keys and could serve a `reuse_as` that disagrees with the store. **Ruling:** the index
  derives exclusively from unit envelopes (post-resolution), keyed by `(kind, final_key)`,
  invalidated per-envelope by content sha. Consequence: a source is nominable only after the
  materialize that follows its scan — so `orchestrate` runs `materialize` **between scans**
  (it is a cheap stdlib parse), keeping the candidate pool at most one source stale.
- **G2. Witness staleness: vectors may be stale, tokens may not.** The index caches
  embeddings; it must **never** cache what agents copy. **Ruling:** every serving path
  re-reads `reuse_as`, statements, and payloads from the store at serve time; only vectors are
  cached. A repair that rewords a minted statement then invalidates outstanding endorsements
  *by design* (they endorsed the old text — `identity-is-a-ledger §6`), the next materialize
  reports the fallout as mismatches with suggestions, and the hygiene queue lists them for
  one-token re-affirmation. Loud, safe, and the index cannot make it worse.
- **G3. The wholesale-wrong-row error is a judgment error, and stays one.** The witness
  catches blends and slips; it cannot catch an agent copying an entire wrong row and genuinely
  endorsing that row's statement unread. That is the unmechanizable class. Mitigations, all
  already designed: rows carry statements (FORMAT-SPEC: *read the statement before copying*),
  the shown-candidate record makes it auditable (G9), the merge-proposal queue challenges
  recorded merges, Phase 4 measures the rate. The brief states this so the implementing
  session does not attempt a mechanical fix that `specs/07 §3.2` forbids.
- **G4. Negation-as-feature composes cleanly.** A candidate that *contradicts* the draft claim
  is the intended output, not a retrieval error (`specs/10 §2`): the agent refuses the reuse,
  mints its own key, and records a `## Contradictions` entry whose `side:` cites the
  candidate — and sides accept the pasted `reuse_as` token (the parser splits the witness
  off). No pack-side "tension flag" is added: marking pairs as contradictory would be
  inference; the agent decides.
- **G5. Topics ride every shape at full strength.** Topic reuse-before-mint has no witness
  mechanism and the vocabulary is small; shortlisting it would manufacture synonym splits.
  **Ruling:** every feed shape serves the complete topic vocabulary; only claim/contradiction
  candidates are shortlisted.
- **G6. Phase 0 serving inherits P5 (loudness).** `contradictions_for(claim_key)`: resolve
  sides by exact stored-key equality; a side carrying a witness is verified against the cited
  claim's token at serve time — a mismatch is served **flagged** (`side_witness_mismatch`),
  an unresolvable side key is served **flagged** (`unresolved`), and nothing is ever dropped
  or re-pointed. A flag invites a reader; a drop hides a record; a re-point infers.
- **G7. `[embed]`-absent degrade is exact.** No extra → full feed, no retrieval tools, no
  error (`specs/10 §9`). The two regimes must be *semantically identical* at the assert
  layer: same row shape, same `reuse_as`, same materialize checks. Only cost and recall
  differ. `bramber/cli.py` stays import-clean of the embed dependency (lazy import inside the
  subcommands) — the Stop hook's stdlib-only guarantee is non-negotiable and test-pinned.
- **G8. CLI surface, fixed now to prevent bikeshed:** `bramber claims` (full feed, unchanged);
  `bramber claims --like "<statement>"` (Shape A, ~10 rows); `bramber claims --pack
  <extract-rel>` (Shape B, ~100–300 rows + full topics); `bramber index` (build /
  incremental-update / status; artifacts under `_bramber/index/`, gitignored). All JSON, one
  row shape everywhere.
- **G9. The shown-candidate record lands in run records.** Scans are immutable agent
  artifacts, so the candidate list goes to `_bramber/runs/` (specs/05 machinery): one record
  per pack/like call naming the extract and the candidate keys served. Stdlib, tiny, and it
  converts "near-duplicate mint" from unknowable into evidence (M3).

## 4. The unified data flow (what the implementing session is building toward)

```
inbox → ingest → [scan source N: claims --pack extract_N   ← index (vectors only, stale-ok)
                                    rows: reuse_as+statement (fresh from store)
                                    + full topic vocabulary
                  agent writes scan: bare mints / copied reuse_as tokens]
      → materialize  (resolve_keys: membership + witness; all controls; telemetry)
      → index update (incremental, envelope-sha invalidation)
      → next source
…
      → compile (views; variants + divergent now first-class)
      → serve:  engine MCP (deterministic drill-down, untouched)
              + retrieval MCP [embed]: search_units / contradictions_for / expand
      → hygiene: index-inward proposals + ledger telemetry → _bramber/evaluations/
                 → /bramber:evaluate → repair edits (one-token asserts) → materialize
      → measure: Phase 4 mechanical tier every run; merge precision/recall per QUEUE.md
```

## 5. Build plan — ordered stories for the fresh session

Tiers are M05 stakes tiers. The **corroboration ledger is a named critical path** (CLAUDE.md
binding): any story marked ● touches it and takes a hazard screen before commit; every new
safety gate is mutation-verified red before it is trusted. A story without its verify recipe
run green is not done.

| # | story | layer | tier | verify (unpaid unless said) |
|---|---|---|---|---|
| S0 | `contradictions_for(claim_key)` per G6, reusing `meta.contradiction_register` (never reimplementing the merge); CLI `bramber contradictions --for <key>` | `meta.py` | default | pytest fixture: two-source tension returns both sides; no-citation returns empty; mismatch/unresolved sides served flagged |
| S1a | the index: a new `bramber/index` module behind `[embed]`, envelope-derived (G1), incremental by envelope sha, hybrid with the stdlib keyword half; `bramber index` CLI; `_bramber/index/` gitignored | compile layer | default | build/invalidate over fixture; **degrade test: no `[embed]` → cli imports clean, full feed intact**; seam tests untouched |
| S1b ● | feed shapes A/B (G8), rows per M2, full topics per G5, tokens read fresh per G2; shown-candidate run records (G9); FORMAT-SPEC + orchestrate updated (materialize-between-scans, read-before-copy) | `scan.py`/`cli.py` | default, screened | pytest row-shape + freshness tests; recall replay per `specs/10 §4.2` verify; paraphrase-injection mutation check |
| S2 ● | hygiene queues per `specs/10 §5.2` + M5: proposals to `_bramber/evaluations/`, inputs = index near-dups + ledger telemetry; assert only via `/bramber:evaluate` → repair edit | compile layer | default, screened | planted near-dup / synonym-tag / alias fixtures each file a proposal; nothing auto-applies |
| S3 | retrieval MCP per `specs/10 §6` (sibling server, `[embed]`, reuses `compile._field_matches`); engine server untouched | new module | default | scripted e2e transcript, every citation resolving on disk; `test_seam.py` green, zero new exemptions |
| S4 | Phase 4 mechanical tier + merge precision on the synthetic corpus (QUEUE.md entry); judged tier stays designed-not-run | `evals/` | cheap (harness) | pytest; QUEUE.md discipline; no paid step |

Sequencing: S0 ships alone; S1a → S1b; S2 needs S1a; S3 composes S0–S2; S4 anytime after S1b.
Each is independently valuable (`specs/10 §8` holds).

## 6. Contract sheet — what the implementing session may rely on, and must not break

**Rely on (all green at 283 tests):** `scan.resolve_keys(scans, extract_rels) → KeyResolution`
(`resolution`, `minted` as `{(kind, final)}`, `witness_of` as `{(kind, final): token}`, the
disjoint report buckets, `suggestions`); `scan.statement_token` (casefold + collapse, 6 hex);
`scan.known_keys(root)` rows (`kind, key, statement` pinned to the minter's phrasing,
`sources, witness, reuse_as`); `materialize`'s return-value telemetry; `compile.select_units`
entries (`variants`, `divergent`, `support`, `reliability_floor`);
`meta.contradiction_register` (side-union, `resolutions`, divergence flags).

**Must stay true (each is test-pinned; several are mutation-verified):** classification is set
membership, never key shape; an unwitnessed or mismatched reuse degrades to the author's own
namespace and is reported — never merged, never dropped silently; every feed and the store
resolve through the **one** `resolve_keys`; `bramber/engine/` unchanged and the cli import
graph stdlib-only; the index asserts nothing (no merge, no support increment, no edge) and is
never read for tokens or payloads; notices state what happened, not the adjacent thing; disk
is truth — index and db are both losable caches.

**Out of scope, by standing rulings:** similarity-threshold merging in any costume;
machine-synthesized framing; engine schema changes; paid eval runs before the T3 restage.

## 7. Open, deliberately

Rendered-document display of divergence (product/authorship decision, data already survives);
non-projected payload scalars rendering first-wins (`evidence_strength` — mitigate by
projecting it); `support` counting documents rather than independent desks (different axis,
QUEUE-listed); the embedding provider choice (implementation-time, per `specs/10 §4.1`); a
serializer around the materialize-time directory listing (filed screen finding E — a one-run-
late raise, loud not silent).
