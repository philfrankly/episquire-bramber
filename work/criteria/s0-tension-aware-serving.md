# Acceptance criteria — S0, tension-aware serving

<!-- record-kind: criteria -->

**Authored** 2026-08-11 · taxonomy **v5** · tier: default (Opus 5) · mode: **RETROACTIVE**
**Subject:** `meta.contradictions_for` + the `bramber contradictions --for` CLI arm, and the
`unattributable` channel added in answer to the round-1 screen. Commit `9337e5d` onward, read as
the tree stands at `fd3b946`.
**Verify:** `python -m pytest tests/` → **359 passed** (2026-08-11, clean invocation).
**Prior screens:** the 2026-08-10 screen (FIX-FIRST, S0-1
HIGH), the 2026-08-10 screen, pass 2 (FIX-FIRST, S0-7 HIGH).
**Status:** 12 criteria — **11 met, 1 UNMET (AC-8)**. 12 classes no-surface.

---

## Acceptance criteria

### AC-1 — a tension none of whose sides resolve is returned, never dropped   [H10] [retro-satisfied]
- **Holds when:** a corpus records `CONTRA-001` whose every side cites a key the corpus never
  minted, and `contradictions_for(root, k)` returns it in `unattributable` with a `why`, rather
  than answering `count: 0`.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_a_tension_whose_sides_all_fail_to_resolve_is_returned_not_dropped`
- **Reddens when:** the `unattributable` limb of the filter in `meta.contradictions_for` is
  disabled (`elif not served or any(...)` → `elif False:`). **Mutation run 2026-08-11 — reddens.**

### AC-2 — a tension recorded with no side at all is in a channel, not in neither   [H11, H23] [retro-satisfied]
- **Holds when:** a tension whose `sides` list is empty (no `side:` lines, or a single side with an
  empty ref dropped at parse time) is returned in `unattributable`. `any()` over an empty list is
  False, so a per-side predicate alone silently drops exactly the tensions carrying the least
  information.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_a_tension_with_no_resolvable_side_at_all_is_still_returned`
- **Reddens when:** the `not served` limb is removed, leaving `elif any(s["unresolved"] for s in
  served):` — the exact round-2 regression S0-7 named. **Mutation run 2026-08-11 — reddens.**

### AC-3 — an unresolvable side is served flagged, never dropped and never re-pointed   [H2] [retro-satisfied]
- **Holds when:** a side whose `ref` names nothing minted arrives with `unresolved: True`, its
  original ref intact, in the served entry.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_an_unresolvable_side_is_served_flagged_not_dropped`
- **Reddens when:** `side["unresolved"] = s.get("ref") not in minted` → `= False`.
  **Mutation run 2026-08-11 — reddens.**

### AC-4 — a pasted witness that quotes a different claim is flagged, never repointed   [H5, H9, H13] [retro-satisfied]
- **Holds when:** a side carrying a witness token that does not match the cited key's minted
  statement token arrives with `side_witness_mismatch: True`, still pointing at the key the author
  wrote.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_a_mismatched_witness_is_served_flagged_never_repointed`
- **Reddens when:** `side["side_witness_mismatch"] = bool(...)` → `= False`.
  **Mutation run 2026-08-11 — reddens.**

### AC-5 — the two flags are disjoint, so neither states the adjacent thing   [H18] [retro-satisfied]
- **Holds when:** an unresolved side is never also marked `side_witness_mismatch` — it has no
  minted token to verify against, so the second flag would assert something unestablished.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_a_side_pasted_as_reuse_as_serves_verified_and_unflagged` together with AC-3's test.
- **Reddens when:** the `not side["unresolved"] and` conjunct is dropped from the mismatch
  predicate. *(Not separately mutation-run; the conjunct is visible at `meta.py:673` and AC-3's
  and AC-4's mutations bracket it. Weaker evidence than the four above — recorded as such.)*

### AC-6 — resolution is exact stored-key equality, never similarity   [H12] [retro-satisfied]
- **Holds when:** a two-source tension citing the queried key returns both sides as a hit, and a
  key nobody cites returns `count: 0` without error — absence of tension is an answer.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_a_two_source_tension_returns_both_sides tests/test_contradictions_for.py::test_a_key_nobody_cites_returns_empty_not_error`
- **Reddens when:** the filter `any(s.get("ref") == claim_key ...)` is relaxed to a prefix or
  substring match. *(Not mutation-run.)*

### AC-7 — a clean corpus pays nothing for the channel   [H17] [retro-satisfied]
- **Holds when:** on a corpus whose sides all resolve, `unattributable_count` is 0 — so a
  non-empty channel means the answer is incomplete, and never becomes background noise.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_a_clean_corpus_pays_nothing_for_the_new_channel`
- **Reddens when:** the channel is made unconditional. *(Not mutation-run.)*

### AC-8 — the channel's prose says only what its predicate establishes   [H4] — **UNMET**
- **Holds when:** an entry is placed in `unattributable` only where the record genuinely cannot
  rule it out — i.e. some unresolved side has no `extract_path`, or an `extract_path` whose
  namespace matches the queried key's — and the `why` string claims no more than that.
- **Checked by:** *no check exists.* The condition needs a test in
  `tests/test_contradictions_for.py` seeding a tension between two sources, neither being the
  queried key's minter, and asserting `unattributable_count == 0`.
- **Reddens when:** *(would redden when)* the namespace comparison is removed from the predicate.
- **Currently:** the predicate is `any(s["unresolved"] …)` and nothing else (`meta.py:678`), while
  the constant `why` at `:692-697` says the entry can be *"neither attributed to this claim nor
  ruled out as contesting it."* Each side carries an `extract_path` anchor and a key's namespace
  **is** its minting source, so where both anchors name namespaces other than the queried key's,
  the record does rule it out — and the entry is returned as un-ruled-out anyway. On a legacy
  corpus every query returns every tension with an unresolved side, so the channel's discriminating
  power there is zero, which is the failure AC-7's test exists to prevent and cannot see because it
  covers only the clean corpus. This is screen finding **S0-6**, still live, reproduced there.

### AC-9 — every consumer of the primitive is told about the channel   [H6, H7] [retro-satisfied]
- **Holds when:** the CLI arm emits `unattributable_count` and `unattributable` in its JSON, so a
  consumer reading the CLI cannot see a `count` without seeing what qualifies it.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_the_cli_serves_the_primitive_as_json`
- **Reddens when:** the two keys are dropped from the CLI's payload. *(Not mutation-run.)*

### AC-10 — an unattributable entry is never counted as a hit   [H10] [retro-satisfied]
- **Holds when:** `count` reflects only true hits; the unattributable list is returned separately
  and never summed into it.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_an_unattributable_tension_is_never_counted_as_a_hit`
- **Reddens when:** `"count": len(hits)` → `len(hits) + len(unattributable)`. *(Not mutation-run.)*

### AC-11 — witness tokens are read fresh from the store at serve time   [H19] [retro-satisfied]
- **Holds when:** `token_by_key` is built from `known_keys(data_root)` on every call, never from a
  cache written at scan time (`specs/11` G2) — so a re-minted statement invalidates outstanding
  witnesses immediately.
- **Checked by:** structural, at `meta.py:660-663`; no test isolates it.
- **Reddens when:** *(would redden when)* the map is hoisted to module scope. **No executable check
  — this criterion is asserted, not gated.** Recorded rather than dropped, because a criterion
  known to be unchecked is worth more than a silent gap.

### AC-12 — the shipped template writes side refs that resolve   [H8, H24] [retro-satisfied]
- **Holds when:** the side-ref form taught by the plugin's shipped template parses and resolves
  against the store, so the contract the agent is given cannot itself produce the unresolvable
  sides this whole channel exists to survive.
- **Checked by:** `python -m pytest tests/test_contradictions_for.py::test_the_shipped_template_writes_side_refs_that_resolve`
- **Reddens when:** the template's side-ref line is reverted to the bare-key form it taught until
  2026-08-10. *(Not mutation-run.)*
- **Note:** the check reaches *the* template, and "the shipped template" is a set of one named in
  prose — screen finding **S0-9**, filed LOW and carried here unresolved. If a second template
  ships, this criterion silently narrows to the first.

---

## Surfaces ruled out

- **H1 — self-confirmation.** The serving path produces nothing it also attests to; the witness it
  checks is the minter's, read from a store this path only reads.
- **H3 — durability under crash or race.** Read-only. No write, no queue, no mark.
- **H14 — test residue.** Every test in `test_contradictions_for.py` builds under `tmp_path`.
- **H15 — accidental selection order.** The merge arithmetic is `contradiction_register`'s, reused
  unchanged, and no ordering decides a served value here. *(Ordering hazards on the register itself
  belong to the `port-cross-view-onto-scan` set — see its AC-6.)*
- **H16 — queue with no live consumer.** `unattributable` is a return value on a synchronous call,
  not a durable queue; nothing accumulates.
- **H20 — injection into a trusted substrate.** Refs and anchors travel as JSON values through
  `json.dumps`; nothing here builds a delimited or signed string by interpolation.
- **H22 — invariant validated by reading unlocked records.** No invariant is enforced here; the
  path reports, it does not admit or reject a write.
- **H7 (b), H9 (b), H13 (b)** — the inert/credential/provenance surfaces this change creates are
  covered by AC-9, AC-4 and AC-4 respectively; no second, uncovered instance exists.
- **H21 — verification that cannot fail.** Answered *for this story* by the four mutations run
  above rather than by inspection. **But see the UNCLASSED slot: the class is PRESENT in a
  neighbouring story, and was missed by a screen that answered it NOT PRESENT.**

---

## UNCLASSED

**`test_witness_tokens_anchor_to_the_minters_statement` cannot fail for the property it names** —
`tests/test_scan_sections.py:720`. It belongs to the `key-namespacing-and-merge-fixes` story and is
recorded in full in that set's AC-9. Surfaced here because this story's witness criteria (AC-4,
AC-11) rest on the same mechanism, and because it is the one finding in this conversion that no
screen caught: the round-2 key-namespacing screen answered **H21 NOT PRESENT** over exactly that
code.

Not an append proposal — H21 already names the mechanism precisely (*"does the fixture reach the
path the AC names, or a cheaper path that satisfies the same assert?"*). It is evidence about H21's
**precision**, which its own evidence-strength line calls unmeasured, and it is the first
reproduced instance in this repo of a wrong negative on that class.

---

## Findings converted, and findings dropped

| finding | at screen | disposition |
|---|---|---|
| S0-1 | HIGH | → **AC-1**, met, mutation-proven |
| S0-7 | HIGH | → **AC-2**, met, mutation-proven |
| S0-2 *(the unwitnessed arm is free)* | MED | → folded into **AC-5**; the disjointness rule is what makes the arms cost the same |
| S0-3 *(kind dropped from the resolution maps)* | MED | **dropped.** The maps are keyed by `(kind, key)` at `scan.py` and the round-2 report records no reproduction of a collision; without one this names a shape, not a reachable defect. |
| S0-4 *(sides from the store, resolution from the feed)* | MED | **dropped as a criterion, retained as design.** The split is deliberate and documented at `meta.py:637-640`; the screen recorded it as a concern, not a failure. |
| S0-6 | MED | → **AC-8**, **UNMET**, with the fix named |
| S0-8 *(doc gate accepts a non-namespace segment)* | LOW | **dropped.** A test-local assertion on `_namespace_of`'s output shape; no production path reads it. |
| S0-9 | LOW | → noted on **AC-12**; the set-of-one is real but there is one template |
| S0-10 | LOW | → **AC-9**, met |

**Nine findings in, ten criteria plus two notes out, one criterion unmet.** The two HIGHs are met
and mutation-proven; the one thing still owed is AC-8, which is now a named condition with a stated
fix rather than a screen verdict that blocks forever.
