# 09 — The view-agnostic claim scan: bramber becomes a claims compiler

**Status: RULED AND BUILT 2026-08-07.** Proposed 2026-08-07 as an additive experiment; the
founder ruled the same day for the stronger form — *"rewrite the entire package to run a
view-agnostic claims compiler only… remove mandate and any dependencies… redesign and
simplify"* — because a product that re-runs extraction per (source × view) has no value
proposition against a chat project. Ruling recorded in
the 2026-08-07 ruling *view agnostic claims compiler only*; this spec is the design record of
what was built. The additive shape and the §10 experiment from the proposal draft were
overtaken by the ruling and are gone from this record (git history holds the draft).
**Supersedes:** `specs/07` §3's per-view digest surface (its corroboration model survives here
unchanged). The mandate concept (`specs/00`-era) is **withdrawn entirely**, not relocated.
**Depends on:** `00-normalize-adapter-contract.md` (the seam), `specs/08` §4 (the unit schema,
reused unchanged).

---

## 1. The product statement

**bramber is a view-agnostic claims compiler.** Every source is read exactly once — a *scan*
for anything claim-shaped, graded and tagged — into a shared, provenance-pinned claim store.
A **view** is a cheap, deterministic, re-runnable projection over that store. The pipeline:

```
ingest → scan (agent, once per source) → materialize → compile (per view, re-runnable)
```

The cost structure is the product: extraction is O(sources), not O(sources × views). Adding a
view, editing a view, and recompiling after a ruling all cost zero source reads. The previous
design — a digest per (source × view), view-scoped claim keys, a mandate above it all — made a
second view cost as much as the first and made a view edit effectively irreversible; that is
what the ruling removed.

## 2. What the old doctrine got wrong (and what it got right)

Four places asserted *"a claim only exists relative to a view's Thesis."* That conflated:

- **Existence** — a source asserts what it asserts before any view exists. True view-free.
- **Framing** — wording, altitude, and inclusion depend on a frame. True, but framing belongs
  at *selection and authorship*, where re-running is cheap — not at extraction, where it
  poisons the store's reusability.

The scan is therefore bounded by **form, not topic**: a claim is an assertion that could be
true or false and that a reader could check against the source. No frame at extraction — any
frame there (a Thesis, a mandate) would reintroduce the re-run problem one level up, because
editing the frame would invalidate every scan.

## 3. Why the mandate went

The mandate was audited before removal. Findings: no code ever parsed its sections; its one
stated mechanical job (routing scoped by Scope/High-Level Questions) was never built
(`run.derive_status` expected every source in every view); it was optional on every path
(commands drafted around its absence; the eval harness removed its prompt line when unstaged);
and it appears in no eval artifact. It was a versioned blob served over MCP — a human-readable
frame with no mechanism. With extraction view-agnostic, its last candidate job (bounding the
scan) is exactly the job §2 rules out. Removed: `mandate.md`, `mandate_versions`,
`mandate://` resources, the `mandate` MCP tool, the mandate template, every command reference.
`routing_decisions` went with it — routing was the mandate's mechanism, and a shared store has
nothing to route: every source is scanned; views select.

## 4. As built

### 4.1 The scan (`_bramber/scans/<extract-stem>.md`)

One per source, named for its extract, immutable, agent-authored. Frontmatter: `source`,
`scan_date`, `discarded`. Sections: `## Claims` (parsed — the same bullet grammar specs/07
introduced), `## Contradictions`, `## Notes` (prose). Claim fields: `evidence`
(strong|moderate|weak|speculative), `recency`, and `topics` — free-form tags replacing the
view-fed `questions`, minted by the scanning agent with a reuse-before-mint discipline, since
they are the vocabulary views select on. `bramber/scan.py` is the one reader
(replaces `digest.py`); `run.py` imports it rather than carrying a second parser.

### 4.2 Keys are corpus-global

`bramber claims` (no `--view`) is the mint-or-reuse feed: source *N* sees every key sources
*1..N−1* minted, with statements and asserting sources. Reuse records corroboration; a new key
records a new claim; disagreement **never** shares a key. specs/07 §3.2's rejection of
similarity dedup carries over verbatim — a global namespace makes a false merge worse, not
better. For a multi-view project the global namespace is *smaller* than the sum of the per-view
ones it replaces; for a single-view project it is identical.

### 4.3 Dedup is still two operations — unchanged, and now shared

Within a source: collapse (in `scan.units_for_source` — the length-bias fix). Across sources:
count (in `compile.select_units` — support + reliability floor, aggregating in opposite
directions per specs/08 §4.2). The distinction "five sources said it once vs one source said it
five times" is the product, and the redesign did not touch it. What changed: the counting now
happens in one shared store, so **cross-view corroboration is expressible for the first time**
— two views compiling the same claim cite the same key and the same support.

### 4.4 The selector

Predicates: `kind`, and `match.<field>` over any payload field — **scalar fields match
exactly; list-valued fields match any-of** (the fix that makes `match.topics` work at all: the
old scalar-only rule stringified lists, so a list field could never match, silently, even at
cardinality one). The `view` and `lens` predicates are gone — units carry neither; there is
nothing view-flavoured left to select on. `dedup_by` / `order_by` / `project` remain required
with no defaults.

### 4.5 The seam, simplified

`Unit` is now `{kind, payload, provenance}` — `lens` and `view` deleted. The Adapter Protocol
drops `unit_extraction` and `extraction_scope` (the per-view scope has no implementor and no
justification left; the literals did nothing), and `extract_units(extract)` loses its `view`
parameter. `TextAdapter.extract_units` still returns `[]` — extraction is interpretive, so it
happens in the agent's scan pass, not in a deterministic ingest. The engine remains
domain-blind and stdlib-only; `tests/test_seam.py` is unchanged, including its forbidden
identifiers.

### 4.6 Engine schema v3

`version_sources.digest_path` → `scan_path` (the snapshot pipe-triple stays positional:
`extract | scan | contribution`, so pre-v3 snapshots still parse). `mandate_versions` and
`routing_decisions` dropped; `evaluations.scope` narrows to `'view'`. Migration is the
established drop-and-resync — safe because disk is truth (invariant 3), and the mandate's
history goes with the mandate because the product no longer contains the thing it versioned.

### 4.7 Status and resume

`run.derive_status`: scans are corpus-wide (`scans: {present, expected, pending, failed,
discarded}` — pending keyed by extract path); views report only their resources. Run-log item
key for the scan phase: `<extract-rel>` with `phase: scan`.

### 4.8 The plugin

`/bramber:orchestrate` is the **corpus half** (normalize → ingest → scan → materialize — the
paid half); `/bramber:process` is the **view half** (select → author → version — reads no
sources, re-runnable); `/bramber:new-view` compiles the new view immediately against the
existing store, which is the headline demo; `/bramber:evaluate` rules on views only and
recompiles so rulings take effect. FORMAT-SPEC's Digest Schema became the Scan Schema; the
Routing Plan and Mandate sections are gone. `tests/test_plugin_integrity.py` now forbids
`mandate`, `digests/`, and `digest_path` in plugin prose, the same way it forbids the four
superseded names.

## 5. Bugs fixed by construction

- **`materialize --view X` deleted every other view's units** (reproduced 2026-08-07: it read
  one view's digests but rewrote every extract's envelope). The flag is gone — the store is
  corpus-wide, so there is nothing to scope. Pinned by
  `test_materialize_is_never_scoped_and_never_truncates`.
- **`match.<field>` could never match a list-valued field** (`str(['a']) != 'a'`) — silent
  rejection, the blank-bullet failure one type deeper. Fixed with any-of semantics; scalar
  exactness pinned separately so the fix cannot loosen it.

## 6. What was verified

`pytest` green (182 tests). Specifically: one source scanned once and selected by two views
yields one claim key and identical support in both compiled resources
(`test_a_second_view_costs_no_second_scan` — the product claim as a test, including that the
scans' bytes are untouched by adding a view); support/floor semantics unchanged
(`test_compile_selector.py`); scan lineage survives snapshot → DB delete → rebuild
(invariant 3); the truncation and list-match regressions above; and the corpus-global
mint-or-reuse feed (`test_scan.py`).

## 7. Costs accepted, eyes open

- **The store grows.** Form-bounded extraction is less selective than Thesis-bounded; the
  discrimination moved to selectors and authorship, where it is cheap but must actually be
  exercised. A view with no `match.` predicates is a dump of the store — sometimes wanted,
  usually not.
- **`topics` is a shared vocabulary with no owner but discipline.** Synonym tags split what
  should be one selectable subject. Mitigations: the scan schema's reuse-before-mint rule, and
  `/bramber:evaluate`'s vocabulary-repair proposal path. If this proves too weak in practice, a
  curated tag registry is the escape hatch — a file views and scans share, human-gated like a
  view. Not built; build it when drift is observed, not before.
- **Scan statements are view-voiced by nobody.** Resources gain their voice at authorship.
  Whether anything is lost relative to Thesis-framed extraction was the §10 experiment the
  ruling overtook; the eval harness can still answer it later (see the eval queue).
- **The T3 eval harness stages the withdrawn flow.** Its runs are frozen evidence and stay
  readable; a future paid run needs restaging against the scan pipeline first.

## 8. Non-goals

- **Not** semantic-similarity dedup, under any framing (specs/07 §3.2, strengthened by the
  global namespace).
- **Not** automatic contradiction resolution. Contested claims keep distinct keys; both sides
  are cited; the human arbitrates at `/bramber:evaluate`.
- **Not** a richer selector DSL. Any-of on lists and exact on scalars is the whole addition. A
  view needing boolean logic is a view whose authoring step should do the work.
- **Not** a change to what `support` means. The open question in
  the 2026-08-05 ruling *cross source claims and the citation count stratifier* §6 stays
  open; the shared store gives its eventual repair somewhere to put a second citation, which
  the digest's singular `source:` did not.
