# Acceptance criteria — port cross-view onto scan

<!-- record-kind: criteria -->

**Authored** 2026-08-11 · taxonomy **v5** · tier: default (Opus 5) · mode: **RETROACTIVE**
**Subject:** the four-section scan port and the meta layer — `scan._SECTIONS` driving four unit
kinds, `Scan.kinds_absent` and the per-item degrade counters, `_parse_side`, the new `meta` module
(five feeds, the ```feed block parser, three renderers, `verify_join`), `compile.VIEW_SCOPES` and
the `scope: meta` refusal, `ingest.write_units_envelope(kinds_absent=…)`, and the `meta-select`
CLI arm. Read as the tree stands at `fd3b946`.
**Verify:** `python -m pytest tests/` → **359 passed** (2026-08-11, clean invocation).
**Prior screens:** the 2026-08-07 screen (FIX-FIRST, 3 HIGH
/ 6 MED / 9 LOW), the 2026-08-07 screen, pass 2 (FIX-FIRST, G1
HIGH — *introduced by the round-1 F2 fix*).
**Critical path:** `scan.units_for_source`, `compile.select_units`, `meta.contradiction_register`.
**Status:** 19 criteria — **17 met, 2 UNMET (AC-9, AC-10)**. 6 classes no-surface.
AC-19 met 2026-08-18; the reproduction below is kept as the record of what was wrong.
*(Counts here and below are derived by `grep -c '^### AC-'`, not written by hand — the first draft
of this line said 18, which is H24 committed inside a document that files H24 as AC-10.)*

---

## The pair this story exists to pin

Round 1 found **F2**: a malformed item bullet let the next item's fields transplant onto the
previous one. The fix reset the carry-over on any unplaceable line — and round 2 found **G1**: a
wrapped field value, ordinary output from a language model, now killed the item's remaining fields.
One fix, one new HIGH, and the sequence never converged.

**AC-2 and AC-3 are the two halves of that oscillation, and both are mutation-proven.** Reverting
either direction turns the suite red. That is what a terminal condition looks like on a problem
that previously had none: the fix point is pinned from both sides rather than approached from one.

---

## Acceptance criteria

### AC-1 — contradiction keys are namespaced, merge, and are published like claim keys   [H5, H12, H8] [retro-satisfied]
- **Holds when:** two sources recording one tension reuse the key and it gains support normally,
  and the mint-or-reuse feed shows contradiction keys — round-1 **F1** was that `CONTRA-NNN` merged
  corpus-wide while the feed the spec points the agent at published only claim keys, so the agent
  was told to reuse a key it could not see.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_known_keys_carries_contradiction_keys_with_their_sources tests/test_scan_sections.py::test_the_feed_publishes_every_key_minting_section tests/test_meta_select.py::test_a_reused_contradiction_key_merges_and_gains_support`
- **Reddens when:** the feed's key-minting section list drops `contradictions`. *(Not mutation-run.)*

### AC-2 — a malformed item bullet never transplants its fields onto the previous item   [H4, H10, H2] [retro-satisfied]
- **Holds when:** a bullet at column 0 that fails the item pattern drops the carry-over, so its
  sub-bullets cannot be applied to the preceding item. A transplant is worse than a drop: the
  previous claim silently acquires the next one's evidence grade and topics, and every downstream
  surface reports the corrupted value as though the source gave it.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_malformed_bullet_never_transplants_its_fields_onto_the_previous_item tests/test_scan_sections.py::test_a_malformed_bullet_is_counted_even_though_the_kind_produced_units`
- **Reddens when:** `current = None` is removed from the malformed-item arm. **Mutation run
  2026-08-11 — reddens.**
- **Was:** round-1 finding **F2**, HIGH.

### AC-3 — a line that could not have been an item never costs the item its later fields   [H10, H8] [retro-satisfied]
- **Holds when:** a wrapped field value, a nested sublist under `aliases:`, or an editorial line
  between bullets leaves the live item intact — none of them can introduce an item, so none can
  misattribute anything, and resetting on them produces a *wrong* unit rather than an absent one.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_wrapped_field_value_does_not_cost_the_item_its_later_fields tests/test_scan_sections.py::test_a_nested_sublist_does_not_cost_the_item_its_later_fields tests/test_scan_sections.py::test_a_truncated_item_still_reaches_the_store`
- **Reddens when:** the reset condition is widened from `_ITEM_BULLET_RE.match(line)` to every
  non-empty unplaceable line — the round-1 fix's exact overreach. **Mutation run 2026-08-11 — both
  tests redden.**
- **Was:** round-2 finding **G1**, HIGH.

### AC-4 — loss and truncation are counted apart and reach the operator in their own words   [H10, H17] [retro-satisfied]
- **Holds when:** `lost` (an item produced no unit) and `truncated` (an item produced a unit
  missing what followed) are separate counters, both reach the envelope and the operator, and
  neither is reported using the other's word. One counter reporting both makes the notice false for
  whichever case it does not name.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_an_unplaceable_line_inside_an_item_is_counted_as_truncation_not_loss tests/test_scan_sections.py::test_the_two_degrades_are_reported_to_the_operator_in_their_own_words tests/test_scan_sections.py::test_lost_counts_reach_the_envelope_and_the_operator tests/test_scan_sections.py::test_a_well_formed_scan_reports_no_unparsed_lines`
- **Reddens when:** the truncation counter increments `lost` instead. **Mutation run 2026-08-11 —
  two tests redden.**

### AC-5 — disagreeing resolutions are flagged, never decided by filename   [H15, H10] [retro-satisfied]
- **Holds when:** two sources giving a tension different `resolution` values produce a flagged
  disagreement with **both** framings retained, and the register is invariant under renaming the
  source files. Round-1 **F3** and round-2 **G3** were that filename order picked a winner and the
  loser vanished.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_disagreeing_resolutions_are_flagged_not_decided_by_filename tests/test_meta_select.py::test_the_register_is_invariant_under_source_renaming tests/test_meta_select.py::test_every_framing_of_a_reused_tension_survives`
- **Reddens when:** the register keeps one framing per key instead of unioning them.
  *(Not mutation-run.)*

### AC-6 — an omitted status is absence, not disagreement   [H11] [retro-satisfied]
- **Holds when:** a source that simply does not state a resolution is not counted as disagreeing
  with one that does.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_an_omitted_status_is_absence_not_disagreement`
- **Reddens when:** `None` is admitted into the set of distinct wordings. *(Not mutation-run.)*

### AC-7 — divergence means different sources, never one source phrasing twice   [H4] [retro-satisfied]
- **Holds when:** `divergent` is true only where the wordings differ **and** the contributors
  differ — one source phrasing a claim two ways is a within-source collapse, not a disagreement,
  and reporting it as one produced the nonsense pairing `divergent: True` with `support: 1`.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_a_merged_claim_worded_identically_is_not_divergent tests/test_meta_select.py::test_identical_phrasing_is_not_divergent tests/test_meta_select.py::test_one_source_cited_twice_yields_support_one tests/test_meta_select.py::test_divergence_is_deterministic tests/test_meta_select.py::test_two_sources_defining_a_term_differently_merge_and_flag_divergent`
- **Reddens when:** the `len(contributors) > 1` conjunct is dropped at `compile.py:354`.
  *(Not mutation-run.)*
- **Was:** round-2 **G2**, and round-1 **M** from the key-namespacing screen, moved here.

### AC-8 — a merge never invents an attribution   [H5, H13] [retro-satisfied]
- **Holds when:** `verify_join` P1 raises where a merged entry credits a source that contributed no
  unit for that key.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_verify_join_catches_an_invented_attribution`
- **Reddens when:** `phantom = credited - contributing` → `phantom = set()`. **Mutation run
  2026-08-11 — reddens.**

### AC-9 — a merge never publishes a field value no source gave   [H4, H21] — **UNMET**
- **Holds when:** `verify_join` P2 raises where **any** field of the merged representative matches
  no contributing source's value for that field.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_verify_join_catches_a_representative_no_source_gave` — which passes, and does not establish this.
- **Currently — reproduced 2026-08-11:** P2 flattens every field of every variant into one set and
  every field of the representative into another, then raises only if the two sets are **wholly**
  disjoint (`meta.py:796-798`). So a merged entry whose `statement` was made by no source passes,
  provided it shares any unrelated field — a `topic`, say — with a contributor:

  ```
  representative  {statement: "A statement no source ever made.", topic: "cutover"}
  variants        {statement: "The cutover date is fixed.",  topic: "cutover"}
                  {statement: "The date was confirmed.",     topic: "cutover"}
  verify_join     -> PASSES
  control: drop the shared `topic` from the representative -> raises
  ```

  The docstring says P2 catches *"the merge produced a statement no source made"*; the
  reproduction is exactly that, and it passes. The existing test uses a **single-field** entry, so
  its fixture reaches only the wholly-disjoint case the weak predicate happens to catch — the H21
  limb, and the reason two rounds of screening left this open.
- **Fix:** compare per field (`for f in rep: rep[f] in {v["fields"].get(f) for v in vs}`), and add a
  multi-field fixture with one shared field.
- **Was:** round-1 finding **F4**, MED. Its *"cannot fail"* limb has since closed — both P1 and P2
  now redden when disabled — but the property the docstring names is still not the property checked.

### AC-10 — every declared join mode and renderer reaches its own handler   [H24, H7] — **UNMET**
- **Holds when:** adding a name to `JOIN_MODES` or `RENDERERS` without adding its dispatch arm
  fails loudly.
- **Checked by:** *no check exists.* `test_an_unknown_join_mode_is_refused` covers a name **not** in
  the tuple; nothing covers a name that is.
- **Currently:** `JOIN_MODES` holds five names; `run_feeds` dispatches four by name and routes
  everything else to `select_across` in an `else` (`meta.py:252-263`), so a sixth mode validates
  clean in `_finish_feed` and is silently mis-dispatched as `units`. `RENDERERS` has the same shape
  with an if/elif and no else, so a fourth renderer silently renders nothing. H24's quiet kind:
  complete today, a guaranteed defect on the next addition.
- **Fix:** dispatch through a dict keyed by the tuple, or assert `set(JOIN_MODES) == set(handlers)`.
- **Was:** round-1 finding **F10**, LOW. Carried as UNMET rather than dropped because the cost
  arrives on the next edit, and a criteria set is the record that edit will be read against.

### AC-11 — every payload field a unit carries is declared domain vocabulary   [H2, H7] [retro-satisfied]
- **Holds when:** no unit reaches the store carrying a field outside the declared vocabulary —
  round-1 **F18** was four new field vocabularies declared in prose and enforced nowhere.
- **Checked by:** `python -m pytest tests/test_seam.py::test_every_payload_field_is_declared_domain_vocabulary`
- **Reddens when:** a field is added to a dataclass without adding it to `DOMAIN_TOKENS`.
  *(Not mutation-run; the gate is a closed-world comparison, which is the shape that cannot go
  vacuous by omission.)*

### AC-12 — the four sections produce four kinds, keyed apart   [H12] [retro-satisfied]
- **Holds when:** one scan carrying all four sections yields four unit kinds whose keys cannot
  collide across kinds, and FORMAT-SPEC's own example parses into every one of them.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_all_four_kinds_from_one_scan_are_keyed_apart tests/test_scan_sections.py::test_the_format_spec_example_parses_into_every_kind`
- **Reddens when:** the `(kind, key)` tuple is collapsed to `key`. *(Not mutation-run.)*

### AC-13 — absence has three distinguishable reasons, and reaches the envelope on disk   [H11, H17] [retro-satisfied]
- **Holds when:** "the section was missing", "the section was present but empty" and "the section
  predates the machine-readable block" are three distinct recorded reasons; they reach the units
  envelope on disk; and a kind that produced units is never reported absent.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_the_three_absence_reasons_are_distinguishable tests/test_scan_sections.py::test_kinds_absent_reaches_the_envelope_on_disk tests/test_scan_sections.py::test_a_kind_that_produced_units_is_never_reported_absent tests/test_scan_sections.py::test_a_fully_migrated_scan_prints_no_warning`
- **Reddens when:** two reasons are merged into one enum value. *(Not mutation-run.)*

### AC-14 — the empty-section sentinel is never mistaken for content   [H18, H2] [retro-satisfied]
- **Holds when:** `None identified` yields no entity, is recognised as a finding rather than a
  legacy section, and drops the carry-over like any other non-item.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_the_none_identified_sentinel_is_not_an_entity tests/test_scan_sections.py::test_a_bulleted_sentinel_is_a_finding_not_a_legacy_section tests/test_scan_sections.py::test_a_sentinel_also_drops_the_carry_over`
- **Reddens when:** the `SENTINELS` guard is removed from `_make_named`. *(Not mutation-run.)*
- **Was:** round-1 **F6**, MED — *"`None identified` is the cheapest arm."* The arm is now
  **distinguishable**, which is what the H18 rule asks; whether an agent *earns* it is not a
  property this code can check, and is recorded here as out of reach rather than asserted.

### AC-15 — a bullet never spans a section, and a discarded scan contributes nothing   [H23, H6] [retro-satisfied]
- **Holds when:** parsing is per-section — an item cannot carry across a `##` boundary — and a
  discarded scan contributes no unit of any kind.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_bullet_never_spans_a_section tests/test_scan_sections.py::test_a_discarded_scan_contributes_nothing_of_any_kind tests/test_scan_sections.py::test_notes_stays_prose_and_is_not_parsed`
- **Reddens when:** the section reset is removed from the `##` branch. *(Not mutation-run.)*

### AC-16 — a meta view is refused by every path that compiles a source view   [H6, H23] [retro-satisfied]
- **Holds when:** `compile` refuses `scope: meta`, `run_feeds` refuses a source view, a meta view
  with no ```feed block is refused, and the default scope is `source` — so the two view kinds
  cannot be processed by each other's pipeline.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_compiling_a_meta_view_is_refused tests/test_meta_select.py::test_run_feeds_refuses_a_source_view tests/test_meta_select.py::test_run_feeds_refuses_a_meta_view_with_no_feed_block tests/test_meta_select.py::test_view_scope_defaults_to_source tests/test_meta_select.py::test_the_spine_skips_meta_views tests/test_meta_select.py::test_per_view_skips_meta_views`
- **Reddens when:** `_resolve`'s `scope: meta` refusal is removed. *(Not mutation-run.)*
- **Note:** round-1 **F17** observed the refusal is per-invocation while sync/rebuild walk every
  view directory. The six gates above cover every path in this module; a walker outside it is
  outside this story's subject and is named in the table below.

### AC-17 — the per-view feed lays selections side by side and never totals them   [H12, H13] [retro-satisfied]
- **Holds when:** `per-view` returns each view's own selection keyed by view and emits no
  cross-view total — summing them would assert an agreement no view made.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_per_view_lays_selections_side_by_side tests/test_meta_select.py::test_per_view_emits_no_cross_view_total`
- **Reddens when:** a `total` key is added to the per-view result. *(Not mutation-run.)*

### AC-18 — every rendering draws only what the data contains   [H13] [retro-satisfied]
- **Holds when:** coverage renders a table rather than an inferred graph, divergence draws only
  divergent entries, an empty register says so rather than drawing nothing, and mermaid ids survive
  punctuation. A diagram asserts structure and its arrows are the assertion; an almost-right
  diagram is indistinguishable from a right one at a glance.
- **Checked by:** `python -m pytest tests/test_meta_select.py::test_coverage_is_a_table_not_a_graph tests/test_meta_select.py::test_divergence_draws_only_divergent_entries tests/test_meta_select.py::test_divergence_says_so_when_nothing_diverges tests/test_meta_select.py::test_contradiction_graph_names_the_likely_cause_when_empty tests/test_meta_select.py::test_contradiction_graph_draws_every_merged_side tests/test_meta_select.py::test_mermaid_ids_survive_punctuation`
- **Reddens when:** a renderer emits an edge not backed by a stored unit or cited side.
  *(Not mutation-run.)*

### AC-19 — a blank-named entity or term never mints a key   [H11, H12] — **MET 2026-08-18**
- **Holds when:** a loose bullet whose name is blank yields **no** unit, or yields one that cannot
  merge.
- **Checked by:** *no check exists.*
- **Currently — reproduced 2026-08-11:**

  ```
  parse_text('## Entities\n- ** ** — a gloss\n')
     ->  entity_name: ''   entity_key: ''
  ```

  `_make_named` guards the `None identified` sentinel and nothing else, so a blank name survives
  `strip()` into an empty `entity_key`. Every source carrying one mints the same empty key, and the
  selector merges on that key — so unrelated entities from unrelated sources collapse into one
  unit, which is the merge-nobody-judged failure this repo treats as the unrecoverable direction.
- **Fix:** return `None` from `_make_named` on a blank name, counted as `lost` like any other
  malformed item, and add the probe above as a test.
- **Fixed 2026-08-18:** `_make_named` returns `None` on a blank name and `parse_text` counts
  it `lost`. The sentinel needed its own signal (`_SENTINEL_BULLET`) first — sharing `None`
  would have reported a malformed bullet as a section correctly reporting nothing, which is
  the opposite conclusion. Checked by
  `python -m pytest tests/test_scan_sections.py::test_a_blank_name_never_mints_a_key`;
  mutation-verified in isolation (guard removed -> red, AC-15's fix left in place -> still red).
- **Was:** round-1 finding **F7**, MED.

---

## Surfaces ruled out

- **H1 — self-confirmation.** No actor here approves what it produced; `verify_join` reads merged
  entries it did not build, and the parse layer writes nothing it also validates.
- **H3 — durability under crash or race.** `materialize` rewrites the units tree wholesale; there
  is no incremental durable write and no progress mark. The corpus-uniqueness concurrency limb is
  **F16**, which is the same defect as the key-namespacing story's finding **E** and is recorded
  once, there, at its AC-16.
- **H9 — counterfeit credential.** Nothing in this diff accepts a caller-supplied trust value; the
  one credential surface in this work is the key namespace, which belongs to the key-namespacing
  story (its AC-2).
- **H14 — test residue.** Every test builds under `tmp_path`.
- **H16 — queue with no live consumer.** No queue, retry bucket or growing table.
- **H19 — stale-baseline revalidation.** The feeds recompute from the store on every invocation;
  no cached derivation is re-certified. *(The cross-caller version of this is the key-namespacing
  story's AC-14.)*
- **H20 — injection into a trusted substrate.** Values reach mermaid through `_mm_id`/`_mm_label`,
  which is what `test_mermaid_ids_survive_punctuation` covers under AC-18. No signed or delimited
  substrate is built by interpolation here.
- **H22 — invariant validated by reading unlocked records.** See H3 — recorded once, in the
  key-namespacing set.

---

## UNCLASSED

**None.** Every finding this walk produced has a class.

Worth stating because it is the interesting negative: three of this story's criteria were UNMET at
the freeze (AC-19 has since been fixed; AC-9 and AC-10 stand) and all three were already known — two filed by screens that then blocked on them indefinitely, one
(AC-19) filed and left. The conversion's contribution here is not discovery. It is that each is now
a named condition with a reproduction, a fix, and a check that does not yet exist — which is a
thing a person can finish, rather than a verdict that recurs.

---

## Findings converted, and findings dropped

| finding | at screen | disposition |
|---|---|---|
| **F1** | HIGH | → **AC-1**, met |
| **F2** | HIGH | → **AC-2**, met, mutation-proven |
| **F3** | HIGH | → **AC-5**, met |
| **G1** | HIGH | → **AC-3** + **AC-4**, met, mutation-proven |
| **F4** | MED | → **AC-9**, **UNMET**, reproduced here |
| **F5** *(`verify_join` guards one of two merging feeds)* | MED | **dropped.** `select_across` is the only feed producing merged entries with variants; `source_spine` groups rather than merges. The screen's own H6 entry records this as unconfirmed. |
| **F6** | MED | → **AC-14**, met as far as code can reach; the un-reachable half stated |
| **F7** | MED | → **AC-19**, **MET 2026-08-18**, reproduced then fixed |
| **F16** | MED | **moved** to the key-namespacing set's AC-16 — same defect as its finding **E**, recorded once |
| **F18** | MED | → **AC-11**, met |
| **G2** | MED | → **AC-7**, met |
| **G3** | MED | → **AC-5**, met |
| **M** *(from the key-namespacing screen)* | MED | → **AC-7**, met |
| **F10** | LOW | → **AC-10**, **UNMET** |
| **F8, F9, F11** | LOW | **dropped.** Three doc/record drifts: a decision record naming a function that does not read `scope`, a cross-module coupling by prose literal, and a CLAUDE.md command missing an argument. All three are loud or inert, none gates anything, and the records concerned have since been rewritten (`fd3b946` split CLAUDE.md). |
| **F12** | LOW | **dropped as a criterion, kept as scope.** `meta-select` having no agent-facing entry point is acknowledged open in CLAUDE.md and the decision record — the meta documents are not written yet. Inert-until-built is not a defect in this story; it is the next story. |
| **F13** *(`--feed` bypasses the versioned feed declaration)* | LOW | **dropped.** A developer-facing arm on a CLI with no untrusted caller. If the meta layer ever gains a non-human entry point, this returns as a criterion on **that** story. |
| **F14** *(a typo'd `project` field raises "the merge produced a value no source gave")* | LOW | **dropped**, and note the irony: it is a *false positive* from the same P2 that AC-9 shows to be too weak in the other direction. The per-field fix in AC-9 removes both. |
| **F15** *(`source_spine` drops a unit whose extract has no envelope)* | LOW | **dropped.** Reachable only from a hand-edited store; no bramber verb produces a unit without an envelope. |
| **F17** | LOW | → noted on **AC-16**; the walkers are outside this story's subject |
| **G4, G5, G6** | LOW | **dropped.** `orchestrate.md` documenting the old `bramber claims` shape was superseded by the FORMAT-SPEC repair under the key-namespacing story; `key_prefix` inert and `_SECTION_ATTR` duplicating `_SECTIONS` are both cosmetic, with no reachable wrong outcome named in either report. |

**Twenty-five findings in, nineteen criteria out, three unmet.** All four HIGHs across both rounds
are met, and three of the four are mutation-proven — including both halves of the F2/G1 oscillation
that made this story the clearest case in the corpus for why the screen could not terminate.
