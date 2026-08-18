# Acceptance criteria — key namespacing + merge fixes

<!-- record-kind: criteria -->

**Authored** 2026-08-11 · taxonomy **v5** · tier: default (Opus 5) · mode: **RETROACTIVE**
**Subject:** the corpus-wide key namespace — `srcref_for`, `_stamp`, `statement_token`,
`_namespace_of`, `_round_trips`, `resolve_keys` (mint-vs-reuse by set membership),
`check_srcref_uniqueness`, and the `known_keys` feed that publishes `reuse_as`. Commits
`713a036 · 44af015 · c308e38 · d555f1d`, plus the `_stamp` totality rollback `8ccc745`, read as
the tree stands at `fd3b946`.
**Verify:** `python -m pytest tests/` → **359 passed** (2026-08-11, clean invocation).
**Prior screens:** the 2026-08-07 screen (FIX-FIRST,
3 HIGH / 4 MED / 7 LOW), the 2026-08-10 screen, pass 2
(FIX-FIRST, N1–N6).
**Critical path:** `scan.resolve_keys`. Merges here are **irreversible in the direction that
matters** — two claims silently sharing a stored key is one claim gone.
**Status:** 16 criteria — **14 met, 2 UNMET (AC-9, AC-14)**. 8 classes no-surface.
AC-15 met 2026-08-18; the reproduction below is kept as the record of what was wrong.

---

## Acceptance criteria

### AC-1 — classification is set membership, never key shape   [H12, H2] [retro-satisfied]
- **Holds when:** whether a key mints or reuses is decided by whether its namespace segment is in
  the set of namespaces this corpus actually has — not by whether the segment *looks* like one.
  Every decimal digit is a hex digit, so a shape predicate reads `CLAIM-20260107-1` as a reuse and
  merges two unrelated sources.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_classification_is_set_membership_not_shape tests/test_scan_sections.py::test_a_date_shaped_bare_key_is_a_mint_not_a_reuse`
- **Reddens when:** `resolve_keys` classifies via `_looks_like_namespace` instead of `known_ns`
  membership. *(Not mutation-run; `_looks_like_namespace`'s docstring records the original defect
  and its demotion to advisory.)*
- **Was:** round-1 finding **A**, HIGH.

### AC-2 — a namespace a caller supplies never buys support the source never gave   [H9, H13] [retro-satisfied]
- **Holds when:** an agent writing `CLAIM-<real-namespace>-042` for a number that source never
  minted does **not** land an endorsement on it. The namespace segment is a *claim*, not a fact,
  and only membership plus a matching witness makes it a reuse.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_never_minted_number_in_a_real_namespace_does_not_fabricate_support tests/test_scan_sections.py::test_an_unwitnessed_resolving_reuse_is_refused_and_reported`
- **Reddens when:** the witness requirement is dropped from the reuse path. *(Not mutation-run.)*
- **Was:** round-1 finding **B**, HIGH.

### AC-3 — a witness quotes the claim it endorses, so a wrong key cannot merge   [H5] [retro-satisfied]
- **Holds when:** a reuse naming a real minted key whose witness token does not match that key's
  minted statement is refused rather than merged — a mistyped or model-blended key that happens to
  name another real key passes every existence check, and only content-binding catches it.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_reuse_naming_the_wrong_minted_key_does_not_merge`
- **Reddens when:** `statement_token` is replaced by a constant (`return "000000"`), making every
  witness match every statement. **Mutation run 2026-08-11 — reddens.**

### AC-4 — every published reuse token survives publish → copy → resolve   [H20] [retro-satisfied]
- **Holds when:** the `reuse_as` token the feed publishes, copied back verbatim by an endorser and
  re-read by `resolve_keys`, names the same stored key. A key is a delimited substrate and the
  agent's own prefix is interpolated into it, so a hyphen — or its absence — must not change how
  the key parses on the way back.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_every_published_reuse_token_survives_the_round_trip tests/test_scan_sections.py::test_a_hyphenated_prefix_survives_the_publish_copy_round_trip`
- **Reddens when:** *(hyphenated arm)* the prefix is split on the first hyphen rather than the
  last. *(Not mutation-run for this arm; the hyphen-free arm is AC-5 and was.)*
- **Was:** round-1 finding **C**, HIGH.

### AC-5 — `_stamp` is total, so every stored key carries a readable namespace   [H11, H20] [retro-satisfied]
- **Holds when:** a hyphen-free authored key (`FINDING`) stamps to three segments
  (`FINDING-<ns>-0`), not two — a two-segment key is one `_namespace_of` cannot parse, so the copy
  reads as a fresh mint and the endorsement is lost with every reporting bucket empty.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_stamp_is_total_so_every_stored_key_carries_a_readable_namespace tests/test_scan_sections.py::test_a_hyphen_free_key_is_published_as_reusable_and_corroborates`
- **Reddens when:** `_stamp`'s no-prefix arm returns `f"{key}-{srcref}"` instead of
  `f"{key}-{srcref}-{_NO_SEGMENT}"` — the pre-rollback shape. **Mutation run 2026-08-11 — both
  tests redden.**
- **Was:** round-2 finding **N1**, answered by `8ccc745`.

### AC-6 — totality is not injectivity, and the difference is reported not merged   [H2] [retro-satisfied]
- **Holds when:** `FINDING` and `FINDING-0` authored in **one** source do not share a stored key —
  the sentinel escalates until free and the near-collision is reported, because two distinct claims
  on one key is a merge nobody judged.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_two_authored_keys_one_character_apart_never_share_a_stored_key`
- **Reddens when:** the `while allocated.get(...) != (own, key): final += _NO_SEGMENT` escalation
  is removed. *(Not mutation-run.)*

### AC-7 — a published token that cannot round-trip is withheld, and the guard never fires on a key this code can produce   [H10, H21] [retro-satisfied]
- **Holds when:** both limbs hold — a stored key failing `_round_trips` is not published as
  reusable *and* no key `_stamp` can now emit fails it. The second limb is what stops the guard
  from being a permanently-silent branch.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_the_publish_guard_never_fires_on_a_key_this_code_can_produce tests/test_scan_sections.py::test_a_token_a_segment_short_is_named_rather_than_silently_minted`
- **Reddens when:** *(second limb)* `_stamp` is made non-total — the AC-5 mutation, which makes the
  guard start firing on ordinary keys. **Mutation run 2026-08-11 — reddens.**

### AC-8 — the uniqueness control actually runs, and refuses rather than assumes   [H22, H21, H23] [retro-satisfied]
- **Holds when:** two sources resolving to one namespace are **refused**, and deleting the control's
  call site turns the suite red. Round-1 finding **F** was that removing the call site left 271/271
  green — a control nothing observed.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_shared_key_namespace_is_refused_not_assumed tests/test_scan_sections.py::test_materialize_actually_runs_the_uniqueness_check tests/test_scan_sections.py::test_distinct_namespaces_pass_the_check`
- **Reddens when:** the `check_srcref_uniqueness` call is removed from `materialize`.
  *(Not re-run here; `test_materialize_actually_runs_the_uniqueness_check` exists precisely to
  redden on it, and was added in answer to finding F.)*
- **Note:** the check reads a directory listing with no serialiser. Two concurrent `materialize`
  runs remain outside its reach — see AC-16.

### AC-9 — a check that names the minter's statement can fail when the minter's statement is not what is named   [H21] — **UNMET**
- **Holds when:** `test_witness_tokens_anchor_to_the_minters_statement` turns **red** if the
  anchoring mechanism is removed, in both file orderings.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_witness_tokens_anchor_to_the_minters_statement` — which passes, and passes for the wrong reason.
- **Currently — reproduced 2026-08-11, two ways:**
  1. The test derives its expected value from the function under test (`tok =
     scan.statement_token(...)`, `tests/test_scan_sections.py:724`), so replacing `statement_token`
     with a constant leaves it **green**. Every assertion is self-consistent under any
     implementation.
  2. Worse, it does not gate its *stated* property either. Removing the anchoring guard at
     `scan.py:994` (`if tok and statement_token(item.statement) == tok:` → `if tok:`) leaves it
     **green**, because the fixture builds only the ordering in which guarded and unguarded agree.
     Reverse the fixture's sort order (`a_review_md__` → `z_review_md__`) and the same mutation
     yields `statement -> 'Confirmed as fixed.'` — the endorser's phrasing displayed as the
     minter's, which is exactly the defect the guard exists to prevent.
- **The test's own docstring claims both orderings** — *"whichever scan happens to sort first"* —
  and the fixture constructs one, the inert one.
- **Fix:** pin the expected witness to a literal rather than to `statement_token`'s output, and
  parametrize the fixture over both sort orders.
- **Provenance:** found by this conversion. **No screen caught it** — the round-2 screen answered
  **H21 NOT PRESENT** over this code.

### AC-10 — a degraded reuse is labelled, reported, and itself reusable   [H10] [retro-satisfied]
- **Holds when:** a refused endorsement becomes its author's own claim, is reported to the
  operator, and can itself be endorsed — a claim that exists must be corroborable.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_degraded_reuse_is_itself_reusable tests/test_scan_sections.py::test_an_unwitnessed_resolving_reuse_is_refused_and_reported`
- **Reddens when:** the degrade path re-stamps without recording the refusal. *(Not mutation-run.)*

### AC-11 — an unresolvable reuse is named, and a correct one is never named   [H4, H17] [retro-satisfied]
- **Holds when:** both directions hold: a reuse naming an unknown namespace is reported, **and** a
  correct reuse is not reported as unresolvable. Round-1 finding **D** was that the reporter tested
  namespace-exists rather than key-was-minted, so it was true of the wrong set.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_reuse_naming_an_unknown_namespace_is_reported tests/test_scan_sections.py::test_a_correct_reuse_is_not_reported_as_unresolvable tests/test_scan_sections.py::test_a_mismatch_report_suggests_the_key_the_witness_matches`
- **Reddens when:** the reporter's predicate is widened back to namespace membership.
  *(Not mutation-run.)*

### AC-12 — a source-less scan gets a stable namespace rather than a real-looking one   [H11] [retro-satisfied]
- **Holds when:** a slug with no identity suffix is hashed to a deterministic namespace, so
  `srcref_for` is total — never returning a value that *looks* minted but names nothing.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_a_slug_without_an_identity_suffix_still_gets_a_stable_namespace`
- **Reddens when:** the hash fallback is removed and the empty tail returned. *(Not mutation-run.)*
- **Was:** round-1 finding **J**, LOW.

### AC-13 — the feed is one projection, not a second computation   [H19, H8] [retro-satisfied]
- **Holds when:** `known_claims` is a projection of the same `known_keys` feed rather than an
  independent pass — computing the resolution twice is how the publish-copy round trip breaks.
- **Checked by:** `python -m pytest tests/test_scan_sections.py::test_known_claims_is_a_projection_of_the_one_feed tests/test_scan_sections.py::test_the_feed_publishes_every_key_minting_section`
- **Reddens when:** `known_claims` re-derives its own resolution. *(Not mutation-run.)*

### AC-14 — one resolution serves every caller, over one corpus   [H19] — **UNMET**
- **Holds when:** every caller of `resolve_keys` passes the same `extract_rels`, or the divergence
  is asserted rather than assumed. `known_ns` is derived from that argument and it is what
  separates a reuse from a mint, so two callers on different corpora classify differently.
- **Checked by:** *no check exists.* Needs a test asserting the call sites agree, or a
  caller-neutral accessor for `extract_rels`.
- **Currently:** **four** call sites passing **three** different corpora — `ingest.py:136`
  (`all_extracts`), `scan.py:951` and `hygiene.py:307` (`[s.source for s in scans]`),
  `scan.py:1146` (`[s.source for s in scans if s.source]`). `known_keys`' own docstring asserts
  *"The SAME resolution `units_for_source` uses"*, and `c308e38`'s message asserts *"One resolution
  now serves both the store and the feed"* — both true only while the sets coincide. The round-2
  screen reproduced the consequence: delete a scanned source's extract and the feed reports a
  corroborated claim the store never merged.
- **This has widened since the screen**, which named two callers. `hygiene.py` is a third consumer
  added after it. Verified structurally 2026-08-11; the consequence was not re-reproduced.
- **Was:** round-2 finding **N3**, MED.

### AC-15 — whether a published endorsement merges does not depend on a filename   [H15] — **MET 2026-08-18**
- **Holds when:** a reuse targeting a *degraded* reuse resolves the same way regardless of scan
  file order.
- **Checked by:** *no check exists.* Needs the round-2 reproduction as a test: the same corpus
  twice, the endorsing scan renamed to sort before and after its target.
- **Currently:** the second loop in `resolve_keys` mutates `minted`, `allocated` and `token_of`
  **as it iterates** in `authored` order, which is `scan_files`' filename sort. The screen
  reproduced support 2 versus support 1 on identical content with one filename changed. Structure
  unchanged at `scan.py:295-320`; not re-reproduced here.
- **Reproduced and fixed 2026-08-18:** the reproduction held exactly as filed — support 1 with the
  endorsing scan renamed to sort first, support 2 renamed to sort last, on byte-identical content.
  `resolve_keys` now defers every reuse's registration into `minted`/`token_of` until after the
  resolution loop, so no reuse is resolved against a set the same loop is still mutating. Within a
  pass this errs toward under-merge; the key is still published, so the next pass can endorse it,
  and that half is pinned by the test's second assertion. Checked by `python -m pytest
  tests/test_scan_sections.py::test_a_reuse_of_a_degraded_reuse_does_not_depend_on_the_filename`;
  mutation-verified in isolation. Re-resolving the 45-source robotics corpus before and after gives
  byte-identical output — it has no degraded reuses at all (778 resolutions, 0 in every failure
  bucket), so the fix is a no-op on shipped corpora and changes only the pathological order.
- **Was:** round-2 finding **N2**, MED. Direction is under-merge and the outcome is loud, which is
  why it is a named red condition rather than a stop.

### AC-16 — the uniqueness invariant is enforced against writers it can see   [H22] [retro-satisfied, narrowly]
- **Holds when:** the corpus-wide namespace uniqueness check runs on every `materialize` and
  refuses on collision.
- **Checked by:** AC-8's tests.
- **Explicitly NOT held:** two concurrent `materialize` runs. The check lists a directory with no
  lock or serialiser, so it validates records no writer holds. This is round-1 finding **E**,
  accepted rather than fixed: bramber is single-operator and no verb runs `materialize`
  concurrently. **Recorded as a bounded exception, not as a passing criterion** — if a second
  writer ever exists, this criterion is false and nothing will say so.

---

## Surfaces ruled out

- **H1 — self-confirmation.** The endorser and the minter are different sources by construction,
  and the witness is checked against the minter's statement, not the endorser's. Separation is
  structural. *(But AC-9 records that the check proving it does not gate.)*
- **H3 — durability under crash or race.** `materialize` rewrites the units tree; a crash
  mid-write leaves a partial tree that the next run replaces. No incremental durable state and no
  progress mark. *(The concurrency limb is H22 and is AC-16.)*
- **H6 — unguarded sibling path.** Round-1 finding **I** — `bramber claims` publishing before the
  control runs — was answered: the feed is now a projection of the resolution that the control
  gates (AC-13). No second writer of stored keys exists; `resolve_keys` is the only stamper.
- **H14 — test residue.** Every test builds under `tmp_path`.
- **H16 — queue with no live consumer.** No queue, retry bucket or growing table here.
- **H18 — free arm.** Round-1 **K** (the cheap authoring arm got cheaper) is about agent incentive,
  not a forced-choice structure in this code. Dropped — see the table.
- **H23 — granularity.** The controls are per-key and the operations are per-key. The one
  cross-granularity concern, per-run versus per-corpus uniqueness, is AC-16.
- **H24 — set named in prose.** Round-1 **L** named a decision record's prose list; that record has
  since been superseded by `2026-08-11-stamp-is-made-total-…`. No live prose set gates anything
  here. *(The plugin's contract sets are AC-4/AC-13's territory and are enumerated in tests.)*

---

## UNCLASSED

**None.** Everything this walk found has a class. AC-9 is the one finding no screen produced, and
H21 names its mechanism exactly — it is evidence about that class's precision, not a gap in the
taxonomy.

---

## Findings converted, and findings dropped

| finding | at screen | disposition |
|---|---|---|
| **A** | HIGH | → **AC-1**, met |
| **B** | HIGH | → **AC-2**, met |
| **C** | HIGH | → **AC-4**, met |
| **N1** | HIGH¹ | → **AC-5**, met, mutation-proven |
| **D** | MED | → **AC-11**, met |
| **E** | MED | → **AC-16**, met narrowly, exception stated |
| **G1** | MED | → folded into **AC-4**; FORMAT-SPEC's side-ref rule now matches the code |
| **M** *(`divergent: True` with `support: 1`)* | MED | **moved.** `select_units`' divergence flag belongs to `port-cross-view-onto-scan` — see its AC-7. |
| **N2** | MED | → **AC-15**, **MET 2026-08-18** |
| **N3** | MED | → **AC-14**, **UNMET**, and widened |
| **F** | LOW | → **AC-8**, met |
| **G2** | LOW | **dropped.** The stale namespace assertions were in a decision record superseded on 2026-08-11; nothing live states them. |
| **H** | LOW | **dropped.** The two `materialize` return fields now have readers (`ingest` prints them; AC-11's tests assert them). |
| **I** | LOW | **dropped** — see H6 above. |
| **J** | LOW | → **AC-12**, met |
| **K** | LOW | **dropped.** A claim about agent incentive with no executable form. A criterion that cannot be checked is not a criterion, and pretending otherwise is what AC-9 is about. |
| **L** | LOW | **dropped.** Its subject record is superseded. |
| **N4, N5** *(FORMAT-SPEC rule vs template; unwritable own-source side ref)* | LOW | **dropped as separate criteria, folded into AC-4.** Both were doc-contract drift against a side-ref form the code now enforces and a test now exercises. |
| **N6** *(inert report field)* | LOW | **dropped** with **H** above. |

**Twenty findings in, sixteen criteria out, three unmet.** All four HIGHs are met and two of them
mutation-proven. The three unmet at the freeze were the two MEDs the screen filed without a fix
(N2 — since fixed — and N3) and one
the conversion found itself (AC-9).

---

¹ N1 was filed at round 2 without an explicit severity in the index; it is recorded HIGH here
because its own reproduction shows an endorsement silently lost, which is the same failure class
as C. Stated rather than assumed.
