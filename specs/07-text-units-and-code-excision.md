# 07 — Text units, the corroboration model, and the code-adapter excision

**Status: BUILT 2026-07-21; the per-view digest surface is SUPERSEDED by `specs/09` (2026-08-07).**
The founder ruled that extraction runs once per source, view-agnostically (`bramber scan`), so
§3's per-(source × view) digest, its view-scoped claim keys, and the *digest* record are gone —
the corroboration model (§3.2–§3.4: agent-minted keys, mint-or-reuse, dedup as two operations)
survives intact in `bramber/scan.py` and `compile.select_units`, and is the part of this spec
that remains canonical. File references below are as of 2026-07-21 and are not updated — this is
a record.
§3 (Claims → Units), §4 (the excision) and §5 (the five bugs, of
which four were real) all landed 2026-07-21. Section bodies below are left in the future tense
they were written in, with DONE markers where work landed — the plan reads as the record of what
was decided and why.
**Depends on:** `00-normalize-adapter-contract.md` (the seam), `03-first-text-run.md` (text generality),
`06-eval-harness.md` (T1/T2 — both landed first, as sequenced).
**Partially supersedes:** `02-first-code-domain-run.md` — see §6.
**Prompted by:** three audits run 2026-07-21 (private-material, precedence/dedup, excision scope) plus
the empirical units check against the live sibling corpus.

---

## 1. The gap this closes

Three problems that look separate and are one:

1. **The README's central claim is false on the path everyone runs.** It says each source is dissolved
   into "small, uniform pieces… no big source left to shout," and that selection is "airtight — a
   deterministic filter, no judgment involved." Both describe the **code** path. On the text path there
   are no units and no deterministic filter.
2. **The engine deletes corroboration.** Dedup is first-wins on `dedup_by`; every occurrence after the
   first is discarded and lineage is built only from survivors. A unit is linked to exactly one source
   *by construction*, even when it legitimately appeared in five.
3. **The code adapter must go** (it depends on `mentalmodeller`, which has no PyPI presence and which
   the maintainer has never run) — but it is **the only `Unit` producer in the repo.** Removing it
   orphans `compile.py`, `bramber select`, `bramber compile`, and ~22 tests.

(3) is unblocked by fixing (1): give text real units and `compile.py` gains a producer on the path that
is actually used. (2) is fixed in the same edit, because both are properties of how units are keyed and
deduped. **Doing these together leaves no orphan window; doing them apart leaves the repo worse than it
is now.**

## 2. What the audits established

Facts, with citations, so this spec is not re-litigated from memory.

**Text units have never existed.** `TextAdapter.extract_units` returns `[]` (`bramber/adapters/text.py:69-70`)
in every commit that ever touched the file. The live sibling corpus has a `_prism/units/`
directory with 23 correctly-named files — **all `{"units": []}`**, 151–215 bytes each. The run's own
trace records `units extracted => 0`, `sources yielding no units => 23`. There is no `units` table in
the database. `ingest.py:190-200` writes the envelope unconditionally, so the directory *looks* like the
work happened. This artifact misled the maintainer about his own system and is fixed in §5.

**But the extraction already happens, 330 times.** The same corpus holds **330 enumerated Claims across
22 live digests** (6–22 per source), each already carrying `evidence_strength`
(strong|moderate|weak|speculative), recency, and the tracked question it addresses
(`FORMAT-SPEC.md:173-175`). Every digest also carries a `## Contradictions` section. **None of it is
read by any code** — `evidence_strength` has zero occurrences in any `.py` or `.sql` file and never
reaches the database.

**Precedence is decided by filename.** Dedup survival is first-wins over
`sorted(units_dir.glob("*.json"))` (`compile.py:260`) then adapter emission order. The winner is the
alphabetically-first source, tie-broken by an 8-hex-char hash prefix. Deterministic, undocumented, and
unasserted by any test — `test_compile_selector.py:108-116` checks which keys survive, never which
source the survivor came from, so attribution is free to change silently. (`order_by` is *not* a hidden
lever: dedup runs inside the loop, sorting after it, so ordering cannot promote a different duplicate.)

**No weighting machinery exists in code.** No `weight`/`trust`/`authority`/`priority`/`confidence`/`tier`
column anywhere in `schema.sql`. No parser for `## Thesis` / `## Projects` / `## Weighting` / `## Discard`
— those sections are invisible to every line of Python. No `units`, `digests`, `claims`, or `extracts`
tables; the finest granularity the index knows is a resource version.

**`CodeAdapter` is the only `Unit` producer**, and `bramber/engine/` is genuinely clean — three
comment-only references to anything code-shaped, so the domain-blindness claim survives the excision
literally.

**MentalModeller does not depend on this repo.** No packaging declaration, no Python import, three
commits. The only references are two prose lines in the *factory core decision brief* record naming `prism`
and a hard-coded path under the predecessor's working tree. The dependency is one-directional; excision breaks nothing downstream.

## 3. The design — Claims become Units  — **BUILT 2026-07-21**

The extraction step is not missing. It runs at digest time, in the agent, and its output dies as prose.
This spec materializes that output.

> **As built.** the *digest* record is the one reader of a digest and the text domain's unit
> producer; `bramber materialize` re-derives `_bramber/units/*.json` from digests; `bramber claims
> --view` is the mint-or-reuse feed of §3.2. Dedup is split exactly as §3.3 specifies —
> within-source collapse in `digest.units_for_source`, across-source counting in
> `compile.select_units`. `provenance.source_artifacts` is a list from day one (`specs/08` §4.2)
> and `reliability_tier` is assigned by source class from a fixed table.
>
> One correction to §3.1's plan: extending `run.py`'s parser in place would have put claim
> parsing inside the status module. The *intent* — one reader per artifact, never two that drift —
> is honoured instead by `run.py` importing `digest.py`. A trap found on the way: `source:` never
> arrives in `split_frontmatter`'s `fields`, because that key is special-cased into its own list
> for the version-snapshot pipe-triple convention. One parser, two conventions; a test caught it.

### 3.1 Claims get a machine-readable form and a stable key

Extend the digest schema so each Claim carries a `claim_key` alongside the grading it already has. The
digest stays human-readable markdown; the claim block becomes parseable.

`run.py:122-130` already parses digest frontmatter for `source:` and `discarded:` to drive
`bramber status`. **That parser is the seam** — extend it past the frontmatter into the body rather than
writing a new one.

`claim_key` is the text domain's `engram_id`: a stable identity minted once, upstream, that the engine
deduplicates on **without understanding it**. The engine stays domain-blind; the agent does the
interpreting, exactly as the four-layer model requires.

### 3.2 Minting keys incrementally, and why not embeddings

When digesting source *N*, the agent is shown the claim keys already minted for that view by sources
*1..N−1*, and either **reuses** an existing key or **mints** a new one. Corroboration becomes an
explicit recorded decision — "source 4 asserts `CLAIM-007`, first minted by source 1" — auditable
through `--trace`, rather than a similarity threshold crossing.

**Semantic-similarity dedup is rejected, and not on cost.** Two reasons specific to this product:

- **Negation is invisible to similarity.** "The deadline is confirmed" and "the deadline is *not*
  confirmed" are near-identical to any embedding metric. In a corpus about contested terms, a threshold
  would merge disagreement into agreement.
- **The error types are not symmetric.** A missed merge inflates a count — visible and correctable. A
  false merge **fabricates attribution**, asserting that source B supports a claim B never made. In an
  engine whose product is cited provenance, that is the failure that destroys the artifact.

This also re-applies a ruling the repo already made: the digest schema absorbed *"adjacency is not
confirmation"* after that judge panel. Semantic similarity **is** adjacency.

**Rule:** dedup may collapse restatement; it must never collapse disagreement.

A normalized-string pre-pass (whitespace, case) is acceptable as a cheap exact-duplicate catch. It is
not a substitute for the key.

### 3.3 Dedup becomes two operations

The current single first-wins rule is replaced by:

- **Within a source:** collapse repeated claims to one unit. *This is the length-bias fix.* An
  insistent stakeholder restating a position five times contributes one unit, not five.
- **Across sources:** do **not** collapse. Increment a **support count** and record every contributing
  source. *This is the corroboration signal the engine currently destroys.*

This distinction — "five sources each said it once" vs "one source said it five times" — is invisible to
the system today at every layer. It is the difference between signal and volume, and it is the whole
point of the product.

### 3.4 Precedence falls out of it

Support count plus `evidence_strength` is a defensible ranking. Alphabetical filename order is not.
`evidence_strength` is already written on all 330 claims; it needs a consumer, not an invention.

**Conflicts are surfaced, never silently resolved.** Two claims that contradict must not merge no matter
how similar. The output states the contest and cites both sides; ranking governs presentation order, not
truth. This is the `## Contradictions` discipline already specified in `FORMAT-SPEC.md:184-188`, finally
given a mechanical footing.

### 3.5 Schema consequences

- A claim becomes an indexed entity with links to its supporting sources — the first thing in the system
  that can answer *"how many independent sources support this?"*
- `evidence_strength` reaches the database instead of dying in markdown.
- `version_sources`' `INSERT OR IGNORE` collapse (`db.py:189-198`, PK `(version_id, source_id)`) must be
  revisited: today when N units from one source contribute, only the first `contribution` survives.

## 4. The excision  — **DONE 2026-07-21**

**Deleted:** the code adapter module; the `code` extra in `pyproject.toml`; the `"code"` branch of
`make_adapter` and its error text; `--adapter` and `--repo` on `bramber ingest`; `_discover_root`'s
repo-root path (kept as a seam, now reading a `discover_root` attribute so an adapter whose sources
live elsewhere still needs no ingest edit); the code line in `adapters/__init__.py`; the MM-gated
first-run test; and both shipped example views.

Line references in this section were already stale when written — a reminder that a plan citing
line numbers dates faster than one citing names.

**Generalize in `compile.py`** — the real work. `_project` (`:213-229`) hardcodes five code-shaped keys
(`engram_id`, `qualified_name`, `rationale`, `file_path`, `line_start`); a non-code unit **silently
projects to empty strings with no error**. Also `_is_public` (`:32-35`) and the `public` /
`top_level_only` predicates (`:117-120`), the bullet shape (`:311`), the literal `"of the codebase"`
(`:286-287`, `:361`), and the `engrams` parameter name.

`order_by`/`dedup_by` defaults are *just default strings* and the lookups are fully generic — but change
the defaults to `None` so a missing key **errors loudly** instead of producing blank bullets.

**Docs:** 8 plugin files reference `${CLAUDE_PLUGIN_ROOT}/views/api-surface/…` and will dangle;
`commands/new-view.md:28-30` detects code-vs-text by "does the view have a selector block," which becomes
meaningless. `README.md:180-190` (the code section) and `:225-226` go. the project instructions needs ~14 sites.
`specs/02` is **marked superseded, not deleted** — it is cited by `specs/00` and `specs/03`.
`decisions/` is never edited.

**Also fix, in MentalModeller:** `docs/factory-core-decision-brief.md:7,159` name `prism` and
a local path under the predecessor's working tree. MM is cleared for public release; that doc would publish a dead name and a local path.

## 5. Bugs to fix regardless of the above  — **1–4 FIXED 2026-07-21; 5 was already fixed**

These were live and independent of this spec's design. All four real ones landed in one commit,
each with a test that was **mutation-checked**: the fix was reverted and the test confirmed to go
red, so none of them is the false comfort described at the end of this section.

1. ~~**`compile.py:340` — lineage contribution hardcodes `engram_id`**~~ **FIXED.** It now writes
   `e["dedup_key"]`, the key selection actually deduped on. Any view with a custom `dedup_by` was
   writing **NULL contributions on every lineage row** — and because `contribution` rides the
   snapshot's pipe-triple, a NULL survived a rebuild as a permanent hole. Same defect class as the
   NULL-url bug. Guard: `test_lineage_contribution_uses_the_views_dedup_key`.
2. ~~**`compile.py:294` — `source_count` is populated with the unit count**~~ **FIXED.** It now
   counts distinct contributing extracts, per `FORMAT-SPEC.md`'s *"number of contributing sources."*
   It read 83 and 130 on the shipped views — the one field that looks like a corroboration signal
   was reporting volume. Guard: `test_source_count_counts_sources_not_units`.
3. ~~**`write_resource_version` does not enforce `maintainer: human`**~~ **FIXED.** An agent write to
   a `maintainer: human` resource now raises; the escape hatch is declaring yourself
   (`maintainer="human"`, what `/bramber:evaluate` passes). The old behaviour also **downgraded** the
   resource's maintainer to `agent` on the way past, converting a gated artifact into a generated one.
   Guard: `test_human_maintained_resource_is_gated_from_agent_writes`.
4. ~~**Empty `units/` envelopes mislead**~~ **FIXED.** `ingest.py` now writes `units: null` plus a
   `units_absent_reason` naming the adapter method responsible; `compile.select_units` normalizes
   both shapes (`or []`), so the 23 legacy `[]` envelopes in the live corpus still read. Guard: the
   new step 2b in `test_text_first_run.py`.
5. ~~**No test validates `${CLAUDE_PLUGIN_ROOT}/…` paths exist**~~ — **this claim was wrong when
   written.** `test_every_plugin_root_reference_resolves` already existed in
   `tests/test_plugin_integrity.py`. Recorded rather than deleted, because a spec that audited the
   repo from memory instead of from source is the same failure mode as the false comfort below.

**The pattern under all of these:** a rule declared in one place with nothing checking the other place
agrees — writer-vs-reader, selector-vs-lineage, doc-vs-writer, schema-vs-nothing. Four instances, one
of which shipped. This is why **T1.1 from `specs/06` (writer-keys and reader-keys derived from one
declared artifact) is the highest-value test in the repo** — it makes the whole class impossible rather
than catching instances one at a time. The fixes above close four instances; they do not close the class.

Note `test_format_spec_extract_header_matches_what_ingest_writes` (in `tests/test_plugin_integrity.py`)
still gives *false comfort* here: it checks a **hardcoded tuple** against FORMAT-SPEC and never reads
`ingest.py` or `db.py`, so the two things it claims to hold together can still drift apart. Cited by
test name, not line — the line reference this paragraph used to carry had itself drifted.

## 6. The generality claim  — **RULED 2026-07-21, see below**

> **Resolved.** The claim is restated in two parts and the structural half is built
> (`tests/test_seam.py`); `specs/08` is deferred. Canon:
> the 2026-07-21 ruling *generality claim restated*. The section below is the analysis that led
> there, kept for its reasoning. One correction it did not have: the old gate would have **failed on
> this very spec**, since de-leaking `_project` is a change to `compile.py`.

The falsifiable test — *"adding a domain required no engine edit,"* verified by
`git diff --stat bramber/engine bramber/compile.py` being empty — is **differential**. With one adapter it
is unfalsifiable, and `specs/06`'s T1.4 becomes a test that cannot be written.

Text units do not by themselves restore it: they are `interpretive` / `per_view`, so the Protocol's
`deterministic` / `view_agnostic` literals lose their only implementor along with `git_anchored` identity.

**Recommended: a `GitLogAdapter`.** Sources are commits; units are one per changed file or per
commit-message trailer. `subprocess` only, no third-party dependency, ~100 lines (`TextAdapter` is 119).
It restores the deterministic view-agnostic producer, keeps `git_anchored` alive, is a genuinely
different domain (change history vs prose), and is **self-hosting** — it runs against this repo, so the
gate needs no sibling checkout, fixing the fragility of the old test's `REPO.parent / "MentalModeller"`.

**Alternative:** retire the differential claim and stand on the static one — the engine never imports an
adapter, already enforced by import-direction tests (`test_run.py:23`, `test_trace.py:45`). True by
construction rather than by anecdote, but weaker as a headline.

**Not acceptable:** keeping `code.py` with MM stubbed out. That proves generality against a fiction.

## 7. Sequencing

1. **Bug fixes (§5)** — independent, small, and two are in the provenance path. No reason to wait.
2. **T1.1 + T2 from `specs/06`** — cheap, no corpus, and they close the defect class before new schema
   lands on top of it.
3. **Claims → Units (§3)** with the excision (§4) in the same change, so `compile.py` never sits orphaned.
4. **Generality decision (§6)** — `GitLogAdapter` if taken, after the excision settles.
5. **Eval** — the evaluation spec Layer 1 becomes runnable at this point and not before. Note its A–F corpus
   holds reliability constant while varying length; it should gain a **source G — long, fluent, and
   wrong** — because the failure that damages a user is length landing on the wrong side. The synthetic
   corpus **cannot** test length-independence: there, length correlates with reliability by construction
   (long transcripts authoritative, short minutes deliberately lossy), so an engine that correctly
   weights the long source scores as length-biased.
6. **Publication** — the README correction in §1 is not gated on any of this and should land immediately;
   shipping a claim the code does not support is the exposure, not the missing feature.

## 8. Verification

- `pytest` green throughout; the excision breaks **zero** currently-passing tests (MM is not installed;
  `test_first_run.py` has never run in this environment).
- A test asserting **which source** a deduped unit is attributed to — the gap that lets attribution
  change silently today.
- A test asserting support count: one source stating a claim five times yields one unit with support 1;
  five sources stating it once yields one claim with support 5. This is the spec's central behavioural
  claim and must fail loudly if regressed.
- A test asserting two contradicting claims never merge regardless of textual similarity.
- Round-trip: claims, keys, support counts, and `evidence_strength` survive a DB delete + `bramber rebuild`
  — disk remains the source of truth (invariant 3).
- End-to-end on the existing sibling corpus, whose 330 claims are real prior data: re-digest and
  confirm the claim count is in range and corroboration appears where sources genuinely overlap.

## 9. Notes / non-goals

- **Not** building semantic similarity, embeddings, or a vector index. §3.2 rules it out on correctness,
  not cost; revisit only with a mechanism that survives negation.
- **Not** resolving contradictions automatically. The system surfaces contests and cites both sides; the
  human remains the arbiter at `/bramber:evaluate`.
- **Not** re-running the sibling corpus from scratch. Identity is the body sha, so re-fetching
  re-run ASR mints spurious duplicate sources.
- ~~The sibling corpus is **orphaned by the rename**~~ — **resolved 2026-07-21.** That corpus
  is migrated and verified on `_bramber/` + `bramber.db` (`_prism/` and
  `prism.db` no longer exist on disk). It is runnable; no pre-run fix needed.
