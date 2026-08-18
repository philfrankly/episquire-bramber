# 08 — GitLogAdapter: a second deterministic adapter, and the corroboration model

**Status:** specced, **deferred 2026-07-21** — not scheduled. Judge it later on feature merit, not as
scaffolding for a claim: the 2026-07-21 ruling *generality claim restated* restated the generality
claim in two parts and closed the structural half with `tests/test_seam.py`, so this adapter is no
longer needed to defend it.
**Depends on:** `00-normalize-adapter-contract.md` (the Protocol), `07-text-units-and-code-excision.md`
(the unit-layer changes this shares).
**Still worth building if:** a change-history view is wanted as a feature — it is self-hosting, so
bramber documenting its own history needs no external corpus.

> **§4 is not deferred.** The two unit-schema additions specified there — `reliability_tier` and
> `provenance.source_artifacts` as a **list** — belong to the unit layer and land with `specs/07`.
> The list shape especially: it costs nothing now and is expensive to retrofit once the schema sets.

---

## 1. Why this exists

Two jobs, and it is worth being explicit that they are separable — a future reader should not assume
solving one solved the other.

1. **Keep the generality claim falsifiable.** The claim is differential: *adding a domain required no
   engine edit*. With one adapter it cannot fail, and `specs/06`'s T1.4 becomes a test that cannot be
   written. A second adapter restores it. **This is the job GitLogAdapter does.**
2. **Give `compile.py` a deterministic producer.** Text units (`specs/07`) are `interpretive` /
   `per_view`. Without a second adapter, `deterministic` / `view_agnostic` and the `git_anchored`
   identity kind lose their only implementor, and the evaluation spec Layer 2's control condition — identical
   unit sets through a mechanical path and a model path — has no home.

**It does not satisfy the code-documentation use-case.** That requirement is recorded separately in
the 2026-07-21 ruling *excise code adapter preserve code use case* and is a different thing: change
history is not code comprehension. Do not conflate them.

**Cost:** ~100–150 lines, stdlib `subprocess` only, no third-party dependency. `TextAdapter` is 119
lines for calibration. It is **self-hosting** — it runs against this repo, so the gate needs no sibling
checkout and cannot rot the way a test pointing at a neighbouring directory does.

## 2. The adapter

### Sources and units

A **source** is a commit. A commit yields:

| Unit `kind` | Cardinality | `content` |
|---|---|---|
| `commit_message` | one per commit | the subject and body, **verbatim** |
| `file_touched` | one per changed file | the path and change kind (added/modified/deleted/renamed) |

Discovery is `git log` via `subprocess` with an explicit `--format`, bounded by a `--since` / `--max-count`
argument so a large repo does not ingest unboundedly.

### Identity

`identity_kind = "git_anchored"`, already declared in `schema.sql` and currently unimplemented after the
excision. The key is a tuple, joined deterministically:

```
<commit_sha> : <repo_slug> : <path-or-sentinel> : <extractor_version>
```

Two properties matter more than the exact encoding:

- **The tuple *is* the key.** A new commit, a new path, or a new extractor version mints a **new record**
  rather than versioning an existing one. Re-anchoring an identical tuple is idempotent, which is what
  makes re-ingest safe.
- **`extractor_version` is part of the key.** Bumping the parser mints new identities instead of silently
  rewriting the meaning of existing history. Two lines of code; prevents a genuinely nasty class of bug
  where improving extraction quietly changes what old records claim.

### Locator

Identity answers *which artifact*; the locator answers *where inside it*, so a citation resolves to the
exact slice a reader can check in one hop. The convention:

```
locator ::= <stable-key> [ "#" <within-artifact-path> ]
```

- whole commit → locator **omitted** (the unit is the whole artifact; do not pad with a sentinel)
- file in a commit → `<repo>@<sha>#<path>`
- line range, if ever added → `<repo>@<sha>#<path>:L120-L138`

**Rule: `#` separates *which artifact* from *where inside it*; `:` separates nesting levels within.**
The locator carries the human-readable stable key; the identity carries the deterministic one. Keeping
those jobs in separate fields is what lets identity change (new version) while the reference still
threads back to the same logical thing.

### Valid time

`valid_from` = the **commit author date** — when the change was true in the world — **never the ingest
time**. One field, and it is the whole of what makes "as of when was this true" answerable later.

### Determinism obligations

Normalization must be deterministic *before* hashing, or "the same commit" mints two identities:

- sort and deduplicate the changed-file list before it contributes to any key
- pin the `git log` format string; never depend on locale, colour, or default abbreviation length
- two runs over the same commit range must produce byte-identical output — this is a test, not a hope

## 3. What it deliberately does not do

Each of these is a rule with a test, not a note.

- **No fetching.** The adapter shells out to a local repository and never opens a network socket. Same
  posture as `TextAdapter` — the engine stays stdlib-only and the Stop hook cannot fail on a dependency.
- **No diff parsing, no symbol resolution.** A `file_touched` unit's locator is the path. Anchoring at
  commit-and-path granularity is the whole scope; going finer is the code-documentation use-case wearing
  a disguise.
- **No meaning extraction.** A `commit_message` unit's `content` is the message's own text, **verbatim,
  never a summary of what the change supposedly accomplished.** The moment an adapter paraphrases, it has
  become an interpretive step masquerading as a mechanical one, and its `deterministic` declaration is a
  lie. Name the test for this rule so its violation is loud.

## 4. Unit schema: two additions

These are **not** GitLogAdapter-local. They belong to the unit layer and land with `specs/07`; this spec
is where they are specified because the git domain is what makes the reliability axis concrete.

### 4.1 `reliability_tier` — an ordered enum, and no confidence float

Three values, declared weakest → strongest, so the ordering *is* the precedence table:

| Tier | Meaning |
|---|---|
| `derived` | computed or inferred downstream; must be provenance-pinned |
| `reported` | a faithful account of what happened, not authored by the system of record |
| `authoritative` | the source **is** the system of record for this fact |

For git: a commit **is** the change rather than a report of it, so commit units are `authoritative`.
A text source describing a change would be `reported`.

Three rules that give the tier meaning:

1. **Assigned by source class from a fixed table — never adapter-chosen, never content-derived.** The
   tier is a statement about *provenance*, not about how convincing a particular piece of text sounds.
   An adapter emitting the wrong tier for its class is a defect the conformance test should catch.
2. **No confidence float. Ever.** The type is a small enumerable set so that aggregation is `min()` —
   total, deterministic, explainable, with no threshold to tune and no number to fabricate. A float
   invites averaging, and averaging invites laundering a weak claim into a strong one.
3. **Weakest link bounds what the output may claim.** A compiled resource's floor is the `min` over the
   tiers of the units it cites. **A strong unit never lifts a weak co-cited one** — one `reported` unit
   caps the document at `reported` however many `authoritative` units sit beside it. The floor is
   computed from inputs *before* any prose is generated, so a synthesis step can never re-score its own
   floor.

**`reliability_tier` is orthogonal to the digest's `evidence_strength`** and both should exist. The tier
asks *what is this source's relationship to the fact* (provenance; assigned mechanically by class).
`evidence_strength` asks *how strong is this claim within the source* (content; assigned interpretively
by the agent). Conflating them would collapse two different questions into one unusable number.

### 4.2 `provenance.source_artifacts` is a **list**, minimum length one

The single highest-leverage structural decision in this spec, and the cheapest.

Even while every adapter emits exactly one entry today, **the array shape is what makes corroboration
expressible later without a schema break.** A unit supported by three sources is one unit with three
provenance entries — no new table, no migration, no forked type.

Two derived scalars then answer two genuinely different questions, and both are wanted:

| Scalar | Definition | Question it answers |
|---|---|---|
| **floor** | `min(tier)` across the unit's sources | *How much may I claim?* |
| **support** | `len(source_artifacts)` | *How well attested is this?* |

They aggregate in opposite directions — weakest-link for the floor, count (optionally with `max(tier)`
for "strongest single backer") for support — and that is correct, not an inconsistency. Reconciling them
explicitly is the point: **a claim backed by five sources of which one is weak is well-attested and
weakly-floored simultaneously**, and a system that reports only one of those numbers is hiding half the
picture.

This is the mechanism `specs/07 §3.3` needs for text ("collapse within a source, count across sources"),
specified once here so both adapters share it.

## 5. The integrity guard — the silent floor lift

A failure mode worth stating precisely, because it is invisible and it corrupts exactly the thing this
engine sells.

Two units can share a dedup key while **disagreeing on content or tier**. Under first-wins dedup, the
iteration order — not the dedup key — silently decides which row's content and tier the shared identity
resolves to. A `derived` claim can therefore end up reading as `authoritative`, **lifting the floor**,
with the set of surviving unit IDs unchanged so nothing downstream notices.

bramber has this hole today: dedup survival is decided by `sorted(glob(...))` filename order
(`compile.py:260`), undocumented and unasserted by any test.

**Required:** group by dedup key **before** sorting (so detection can never depend on file order) and
compare members on the fields that determine what a claim renders and what floor it carries — `content`,
`reliability_tier`, `review_state`. Members that are byte-identical on those fields collapse silently, as
intended. Members that disagree are a **defect to surface, never a floor to average or a winner to pick.**

Disagreement on `unit_id` or on provenance is *not* a violation — different sources legitimately
co-reporting the same claim is the corroboration case, and is what §4.2 exists to represent.

**What to do on detection is a deliberate choice, not an implementation detail.** Failing the compile
outright is correct for a small curated corpus. It is not viable for git history, where the same claim
genuinely arrives from a commit message, a later revert, and a follow-up fix. Recommended for bramber:
**surface the conflict as a contested unit, cite both sides, and let the floor fall to the weakest** —
consistent with `specs/07 §3.4`, which requires that conflicts are surfaced rather than silently
resolved. Whatever is chosen, it must not be "pick one by iteration order," which is the status quo.

## 6. Verification

- **Determinism:** two ingests of the same commit range produce byte-identical units, identities, and
  order. Sorting and deduplication happen before hashing.
- **Idempotence:** re-ingesting an already-anchored commit mints no second `Source` row (`specs/06` T2.2).
- **No fetching:** a test asserts the adapter opens no socket — same shape as the existing stdlib-only
  guard on `intake_server`.
- **Verbatim:** a `commit_message` unit's content equals the commit message exactly; name the test for
  the rule so a violation reads as a violation.
- **Extractor version in identity:** bumping it changes the identity key for the same commit.
- **The generality gate (`specs/06` T1.4), finally writable:** adding this adapter must leave
  `bramber/engine/` unmodified. Self-hosting means CI can run the whole gate against this repo with no
  external checkout.
- **Floor:** a resource citing one `reported` unit among `authoritative` ones floors at `reported`.
- **Integrity:** two units sharing a dedup key but differing on content or tier are detected regardless
  of filename order — the test must construct the adversarial case deliberately, since the accidental
  case is what has been hiding.

## 7. Non-goals

- **Not** a code-documentation adapter. See §1.
- **Not** a bitemporal store. Git history is already immutable and append-only; the commit graph *is* the
  version chain. Recording `valid_from` and the sha captures nearly all the value at nearly none of the
  cost.
- **Not** a configurable selection DSL beyond the selector `view.md` already has.
- **Not** PR, issue, or CI ingestion. Those are different source classes with different tiers — a commit
  is `authoritative` while human commentary *about* a change is `reported`, and that distinction deserves
  its own spec rather than being smuggled in here.
