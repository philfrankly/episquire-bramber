# 06 — Eval harness

**Status:** initial spec, not yet built.
**Depends on:** `00-normalize-adapter-contract.md` (the seam), `03` (text generality).
**Motivating corpus:** a synthetic, ground-truth-carrying corpus held outside this repo.

---

## 1. The gap this closes

`tests/` holds 53 tests across 7 files (51 collected; 2 are gated on an optional dependency). Every one of them tests **structure**: lineage survives a DB
rebuild, selectors apply predicates, plugin refs resolve, trace is inert when disabled. None asks
whether the output is any good. The project has said so plainly — *"structure is testable; quality
is not"* — and treated that as a boundary rather than a gap.

Three specific consequences:

1. **The headline claim is not continuously verified.** bramber's design claim is falsifiable: adding
   a domain must not require an engine edit, checked by `git diff --stat bramber/engine bramber/compile.py`
   being empty after the `03` text run. That check ran **once, by hand**. Nothing re-runs it when a
   third adapter lands. A falsifiable claim that cannot currently fail is not doing its job.
2. **There is no CI.** No `.github/`. Even the structural suite runs only when someone remembers.
3. **The engine sells cited provenance and has already leaked it.** `ingest.py` omitted
   `source_url`/`author`/`date_published` while `db._sync_sources` had always read them — writer and
   reader silently disagreed, and *every text source indexed with a NULL url*. It survived because
   fixtures carried the fields but only `source_type` was asserted. It was caught by running `--trace`
   over a real source, not by a test. That class of defect must be caught by the suite, not by luck.

The only existing quality evidence is the 2026-07-17 sibling-instance judge panel: one source, one lens,
run by hand, graded against a human reference. Well-constructed, blind, and **n=1** — an anecdote,
not an eval.

## 2. Design principle — three tiers, only one needs a corpus

Eval effort is often assumed to scale with source data. It does not, uniformly. The tiers map onto
the existing four-layer model, and **data dependence rises with each tier**:

| Tier | Question | Data needed | Cost |
|---|---|---|---|
| **T1 Engine** | Does the adapter↔engine contract hold? | none — schema only | hours |
| **T2 Adapter** | Is ingestion deterministic and identity-stable? | small fixtures | hours |
| **T3 Synthesis** | Is the compiled resource *true to its sources*? | rich corpus + ground truth | days |

T1 and T2 are cheap, universal, and currently absent. Build them first; they are the publication
blockers. T3 is the differentiator.

---

## 3. T1 — Engine contract conformance (no corpus)

**Goal:** make the NULL-url class structurally impossible.

The extract header is the **only** channel between an adapter (which knows provenance) and the engine
(which never imports one). A field ingest omits is NULL forever. So test the channel, not a sample
passing through it.

- ~~**T1.1 Header schema is a single declared artifact.**~~ **DONE 2026-07-21.**
  `bramber/engine/header.py` declares the key set once; `ingest.py` renders through `header.render()`
  and `db._sync_sources` reads through `header.read()`. Enforcement is **runtime, not advisory**:
  `render()` raises unless the writer supplies exactly the declared fields, so adding a field breaks
  ingest until ingest is taught to fill it — a one-sided change can no longer write NULLs.
  Guards in `tests/test_seam.py`; `test_format_spec_extract_header_matches_what_ingest_writes` now
  derives from the declaration (it was the hardcoded tuple `specs/07 §5` called false comfort) and
  compares **set-equality**, so a documented-but-unwritten field fails too.
  One thing deliberately *not* guarded: header **keys** and `upsert_source` **parameters** are
  separate namespaces that happen to share a word for 7 of 9 fields (`source_url` → `url` is the
  exception). Only key-space reads can drift, so only key-space is checked.
- ~~**T1.2 Round-trip completeness.**~~ **DONE 2026-07-21.**
  `test_every_declared_header_field_reaches_the_index` is parameterised over `SOURCE_FIELDS` itself,
  so a field added later is covered without anyone remembering to add an assertion.
- **T1.3 Rebuild identity.** `bramber rebuild` from disk reproduces the index byte-equivalently. Extends
  the existing `test_roundtrip` to cover every header field, not just lineage edges.
- **T1.4 Generality gate as a standing test.** ~~Assert `bramber/engine/` and `compile.py` are unmodified
  across an adapter-addition scenario.~~ **Restated 2026-07-21** — that wording conflated a hard rule
  with a soft one and would fail on `specs/07`, which must change `compile.py`. The gate is now two
  parts, and the first is **done**: `tests/test_seam.py` asserts structurally that `bramber/engine/`
  neither imports an adapter nor names any domain vocabulary. That is stronger than the diff check it
  replaces — it holds continuously rather than at adapter-addition time, and cannot be satisfied by
  luck. The second part (does a *new domain* flow through `compile.py` unchanged) needs a second
  adapter to be meaningful and is deferred with `specs/08`; see
  the 2026-07-21 ruling *generality claim restated*.

## 4. T2 — Adapter properties (small fixtures)  — **DONE 2026-07-21**

One fixture set per adapter; properties are shared. All four live in `tests/test_seam.py`.

- ~~**T2.1 Identity stability.**~~ **DONE.** Same bytes → same `SourceIdentity`, asserted across two
  differently-named inbox files. Trivially true for `content_sha`; the point is it stays true when
  identity becomes pluggable.
- ~~**T2.2 No spurious duplicate minting.**~~ **DONE.** Re-ingesting identical bytes yields one
  `Source` row and one extract file. Guards a hazard the sibling-instance migration already hit:
  identity is the body sha, so re-fetching a re-run ASR transcript mints a second logical source.
- ~~**T2.3 Extraction determinism.**~~ **DONE**, and **currently vacuous** — `TextAdapter.extract_units`
  returns none, so it compares two empty lists. Kept deliberately: it is the assertion that must hold
  when `specs/07` gives text real units, and it now cannot ship untested.
- ~~**T2.4 Adapter writes nothing engine-owned.**~~ **DONE.** An ingest run creates no `bramber.db`, no
  `views/` tree, and touches nothing outside `_bramber/{inbox,extracts,units}`. This is invariant 1's
  other half: `test_engine_never_imports_an_adapter` stops the engine reaching down, this stops the
  adapter reaching up.

## 5. T3 — Synthesis eval against the KYC corpus (corpus + ground truth)

**Why this corpus.** Most eval sets give input → expected output. The KYC corpus gives input → *hidden ground
truth about what the input means*: per-agent ontology snapshots at each of 10 timesteps, per-meeting
divergence matrices, a contested-terms tracker, and a perturbation log. Inputs are `transcripts/` and
`minutes/` only; everything under `ground_truth/` is the answer key and **is never fed to the pipeline**.

Ingest the 10 transcripts + 10 minutes via `TextAdapter`, compile a view, then score:

- **T3.1 Term recovery.** Does the resource surface the corpus's contested terms? Score against
  `scenario.contested_terms`. Recall, not prose quality. *(The term list is deliberately not
  reproduced here — see the Redaction note below.)*
- **T3.2 Divergence detection.** Does it identify terms used incompatibly across speakers? Score against
  `divergence_t*.json`. The final timestep includes one strongly divergent term — the strongest
  positive case.
- **T3.3 Contradiction catch (the sharpest test).** One meeting's minutes record a contested term as
  *settled* while ground truth has it divergent. Does synthesis **inherit the minutes' error or flag
  the conflict against the transcripts?** This is exactly the "work Contradictions hard" discipline the
  digest schema absorbed after that judge panel — here it is mechanically checkable rather than
  judge-dependent.
- **T3.4 Temporal drift.** Does the resource track convergence across the arc recorded in
  `contested_terms_tracker.json`, and catch the terms that resolved then **re-fragmented** under
  perturbation?
- **T3.5 Fabrication — mechanical, not judged.** The corpus is **closed-world**: `synthetic_customer/
  manifest.yaml` declares a canonical entity registry, and the transcripts name a known subset of it.
  Any entity, date, or figure in the output absent from the corpus is a **fabrication**, detectable by
  matching against the registry. This converts the panel's hand-run "14+ quote checks" into a cheap deterministic gate,
  and it is the single highest-value item in this spec.
- **T3.6 Provenance integrity.** Every claim in the compiled resource cites a source that exists, and
  every cited source actually contains the claim. End-to-end version of the check T1 makes structurally.

**Scoring posture.** T3.1–T3.2 and T3.5–T3.6 are pass/fail or scored numerically and belong in CI.
T3.3–T3.4 depend on agent-authored prose (text has no deterministic compile) and are therefore
**tracked as a scored report, not a blocking gate** — regressions are visible without making CI hostage
to model variance. Record the model used with each run; scores are meaningless across model changes.

## 6. CI

Add `.github/workflows/`: run `pytest` on push, T1+T2 always, T3.5 (fabrication) on the KYC corpus,
and the T1.4 generality gate. Structural suite blocks merge; T3 prose-dependent scores report only.

## 7. Out of scope

- Judging prose *quality* (elegance, readability). Fidelity is testable; taste is not.
- Benchmarking against other RAG or synthesis tools.
- Evaluating MentalModeller's engram extraction — that belongs in the MM repo; bramber tests the
  `CodeAdapter` seam, not the extractor behind it.

## 8. Open

- Does the KYC-corpus eval live in this repo (vendored corpus) or reference the sibling directory? Vendoring
  makes CI hermetic; referencing avoids duplicating a 172-file corpus. Recommend vendoring the 20
  transcript/minutes files and the ground truth only — not `synthetic_customer/`.
- `MEETING_SIM_SPEC.md` pins `claude-sonnet-4-20250514`, two model generations old. Re-running the
  simulation is not required to use the existing corpus, but a regeneration should revisit the model.

---

## Amendment 2026-07-21 — corpus audit; what T3 can and cannot claim

The KYC corpus was audited directly rather than from its own documentation. §5 stands, with four
corrections. Recorded as an amendment rather than an edit so the original claims stay visible.

**1. "Any entity, date, or figure" overstates the figure dimension.** The 10 transcripts contain
essentially three numeric tokens in total (values recorded in the corpus's answer-key notes, not
here). Everything else is a vague quantifier — "a material minority", "roughly two-thirds", "a
larger group" (~20 instances). So **T3.5 is strong for entities and dates**, and figure-fabrication is
trivially detectable because *any* number is almost certainly invented — but the corpus **cannot test
quantitative synthesis fidelity**, because there are no quantities in the input to reproduce correctly.

**2. The only unambiguously machine-gradable artifact is the one that must be withheld.**
`synthetic_customer/workloads/*/sample001.gold.json` are true input/schema/gold triplets with typed
scalars and strict JSON Schema. They are also the files whose **directory names** enumerate private
workload classes, so they are withhold-entirely (see
the 2026-07-21 ruling *publish from a fresh repo*). What ships is split: divergence structure
(cluster counts, per-agent alignment sets, resolved flags, the convergence arc) is
exact-match checkable; the ontology `definition` fields are paragraph prose and need a model or a human.
**T3.1/T3.2/T3.4 are therefore part-mechanical, part-judged** — plan the scoring accordingly.

**3. There are no planted claim IDs.** Entity IDs (`ent-merchant-001`) exist only in `manifest.yaml` and
the JSONL records; the transcripts name entities in prose. Any claim-level scoring must match on names,
not IDs.

**4. This corpus cannot test length-independence, and must not be used for it.** Length correlates with
*reliability* by construction: transcripts are long and authoritative, minutes are short, deliberately
lossy, and sometimes wrong (one late meeting's minutes record a contested term as settled when ground
truth has it divergent — the T3.3 case), and the ground truth is derived from the transcripts. **An engine that correctly weights the long
source scores as length-biased; one that ignores length scores as accurate for the wrong reason.** The
corpus contains no case of a short authoritative source contradicting a long unreliable one — which is
the control condition the claim needs. That test belongs to the evaluation spec's synthetic A–F corpus, which
should gain a **source G: long, fluent, and wrong**, since the failure that damages a user is length
landing on the wrong side.

**Also noted:** ~~the corpus is **not a git repository**~~ (under git since 2026-07-23, baseline
`6d98f99`) and it has **never been run through the pipeline**, so the worked example does not yet
exist. A number of registry merchants appear zero times in the transcripts, so the "unstructured sixth
source plane" bridge is real but covers only part of the registry.

---

## Redaction 2026-07-23 — answer-key hygiene

Ground-truth specifics (the contested-term list and count, per-term outcomes, the convergence arc, the
identity of the T3.3 meeting and term, the corpus's numeric-token values, the transcript entity names)
were moved out of this file to
the synthetic corpus's own answer-key notes, held outside this repo. Reason: this spec
is the file a digesting agent is most likely to have in scope, and it stated the answer key in prose —
which would have invalidated any T3 run's scores (the T3 eval review report). Git history
retains the pre-redaction text; that is acceptable under the fresh-repo publication ruling, and the
eval-run environment must exclude this repo (and its `.git`) regardless. Ruling and the run-time
isolation requirements: the 2026-07-23 ruling *context leak remediation*. **Do not restate the
specifics here when amending this spec.**
