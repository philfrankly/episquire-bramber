"""The scan's four machine-readable sections (`bramber/scan.py`).

`## Claims` has always been parsed. `## Entities`, `## Novel Concepts` and `## Contradictions`
became parsed on 2026-08-07 — the raw material had been written into every scan and discarded one
step before it could be counted, so the glossary and the contradiction register had no input that
survived the seam.

Two properties carry most of the weight here:

  - **an unparsed section is never silent.** A scan is agent prose, so a section in an
    unrecognised shape yields nothing by the same mechanism that has always protected Claims. But
    bare silence reads as "this corpus has no entities", a conclusion nobody drew — so every kind
    that produced nothing carries a reason, and three of those reasons are different information;
  - **a compared-with source never inflates support.** The side of a contradiction supplies the
    contrast; it does not assert the tension. Folding it into provenance would manufacture a
    corroborating source.

Run:  cd bramber && python -m pytest tests/test_scan_sections.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bramber import ingest, scan


# --- fixtures ---------------------------------------------------------------

HEAD = """---
source: _bramber/extracts/src.md
scan_date: 2026-08-07
discarded: false
---
"""


def _scan(body: str, path: str = "_bramber/scans/src.md"):
    return scan.parse_text(HEAD + body, path=path)


FULL = """
## Claims

- **CLAIM-001** - The date is fixed.
  - evidence: strong
  - recency: 2026-05-02
  - topics: schedule

## Entities

- **Acme Corp** - supplies the middleware.
  - role: vendor
  - stance: on schedule
  - status: new
  - aliases: Acme, ACME Corporation
  - topics: vendor-risk

## Novel Concepts

- **cutover** - the weekend the old system stops.
  - status: new
  - relates_to: Acme Corp
  - topics: migration

## Contradictions

- **CONTRA-001** - The minutes and the transcript disagree on the date.
  - side: CLAIM-001 | _bramber/extracts/minutes.md | recorded as fixed
  - resolution: the minutes omit the caveat
  - status: proposed
  - topics: schedule

## Notes

Editorial argument that is deliberately not parsed.
"""


# --- entities and terms: identity is the name -------------------------------

def test_entities_parse_with_a_name_derived_key():
    s = _scan(FULL)
    assert len(s.entities) == 1
    e = s.entities[0]
    assert e.entity_name == "Acme Corp"
    assert e.entity_key == "acme corp"          # casefold + whitespace-collapse
    assert e.role == "vendor"
    assert e.aliases == ["Acme", "ACME Corporation"]
    assert e.topics == ["vendor-risk"]


def test_entity_keys_collapse_within_a_source_case_insensitively():
    """Two spellings in one scan are one unit. The key is normalized, the display name is not."""
    s = _scan("""
## Entities

- **Acme Corp** - supplies the middleware.
  - role: vendor
- **ACME   CORP** - also mentioned later in the document.
  - role: vendor
""")
    assert [e.entity_key for e in s.entities] == ["acme corp", "acme corp"]
    units = scan.units_for_source([s])
    entities = [u for u in units if u.kind == "entity"]
    assert len(entities) == 1, "within-source collapse: first statement wins"
    assert entities[0].payload["entity_name"] == "Acme Corp"


def test_novel_concepts_become_terms():
    s = _scan(FULL)
    assert len(s.terms) == 1
    t = s.terms[0]
    assert (t.term_name, t.term_key) == ("cutover", "cutover")
    assert t.relates_to == ["Acme Corp"]


def test_the_none_identified_sentinel_is_not_an_entity():
    """NAMED_RE would happily read `- **None identified.** - ...` as an entity of that name."""
    s = _scan("""
## Entities

- **None identified.** - nothing named in this source.
""")
    assert s.entities == []
    assert "None identified" in s.kinds_absent["entity"]


def test_a_bulleted_sentinel_is_a_finding_not_a_legacy_section():
    """The opposite conclusion from the truth: this scan DOES use the machine-readable shape."""
    s = _scan("## Entities\n\n- **None identified.** - nothing named.\n")
    assert "predates" not in s.kinds_absent["entity"]


def test_a_blank_name_never_mints_a_key():
    """`NAMED_RE` admits any 1-120 non-asterisk characters, so `- ** ** - a gloss` reaches
    `_make_named` with a name that is whitespace only. `strip()` makes it empty, and an empty name
    is an empty KEY — so every source carrying one mints the SAME key and the selector merges on
    it: two unrelated entities from two unrelated sources collapsing into one unit. That is the
    merge-nobody-judged direction, which this repo treats as unrecoverable.

    A blank name is a malformed ITEM, not the sentinel. The two must not share an outcome: the
    sentinel says "this scan uses the machine-readable shape and reports nothing", which is the
    opposite conclusion from "this bullet was written wrong".

    Reddens when `_make_named`'s blank guard is removed.  -> work/criteria AC-19
    """
    s = _scan("## Entities\n\n- ** ** - a gloss\n")
    assert s.entities == [], "a blank name must not become an entity"
    assert s.kinds_unparsed["entity"]["lost"] == 1, \
        "and it is counted lost, like every other malformed item bullet"
    assert "None identified" not in s.kinds_absent.get("entity", ""), \
        "and never reported as the sentinel, which asserts the opposite"


# --- contradictions ---------------------------------------------------------

def test_contradiction_sides_carry_a_key_and_a_checkable_anchor():
    s = _scan(FULL)
    (c,) = s.contradictions
    assert c.key == "CONTRA-001"
    (side,) = c.sides
    assert side["unit_key"] == "CLAIM-001"
    assert side["extract_path"] == "_bramber/extracts/minutes.md"
    assert side["position"] == "recorded as fixed"


def test_a_bare_key_side_is_accepted_now_that_the_namespace_is_the_corpus():
    """The inverse of the pre-2026-08-07 rule, and deliberately so.

    A bare `CLAIM-007` used to be rejected because keys were minted per view, so without the view
    it could name any of them. Keys are corpus-global now, so the bare form is unambiguous and
    rejecting it would drop a real side.
    """
    s = _scan("""
## Contradictions

- **CONTRA-002** - a disagreement.
  - side: CLAIM-009
""")
    (c,) = s.contradictions
    assert c.sides[0]["unit_key"] == "CLAIM-009"


def test_a_legacy_view_qualified_side_is_read_not_dropped():
    """`<view>/<KEY>` was the old shape. The part after the slash still names a real claim."""
    s = _scan("""
## Contradictions

- **CONTRA-003** - a disagreement.
  - side: programme-risks/CLAIM-007 | _bramber/extracts/a.md | as recorded
""")
    (c,) = s.contradictions
    assert c.sides[0]["unit_key"] == "CLAIM-007"
    assert c.sides[0]["extract_path"] == "_bramber/extracts/a.md"


def test_a_compared_with_source_never_inflates_support():
    """The side names `minutes.md`; only `src.md` asserts the contradiction."""
    s = _scan(FULL)
    (unit,) = [u for u in scan.units_for_source([s]) if u.kind == "contradiction"]
    credited = {a["extract_path"] for a in unit.provenance["source_artifacts"]}
    assert credited == {"_bramber/extracts/src.md"}
    assert "_bramber/extracts/minutes.md" not in credited
    assert unit.payload["sides"][0]["extract_path"] == "_bramber/extracts/minutes.md"


# --- absence is stated, never silent ----------------------------------------

def test_a_prose_scan_still_produces_every_claim_it_always_did():
    s = _scan("""
## Claims

- **CLAIM-001** - The date is fixed.
  - evidence: strong

## Entities
Acme Corp is the vendor and is on schedule. Prose, as every scan used to be.

## Contradictions
None of this is in the parsed shape.
""")
    assert [c.key for c in s.claims] == ["CLAIM-001"]
    assert s.entities == [] and s.contradictions == []


def test_the_three_absence_reasons_are_distinguishable():
    """Absent · 'None identified' · content in an unparsed shape. Only the last names a count,
    because that is what tells a reader it is a migration rather than an answer."""
    s = _scan("""
## Claims

- **CLAIM-001** - something.

## Entities
None identified.

## Novel Concepts
Two lines of prose
that predate the machine-readable block.
""")
    assert "no `## Contradictions` section" in s.kinds_absent["contradiction"]
    assert "None identified" in s.kinds_absent["entity"]
    assert "predates the machine-readable block" in s.kinds_absent["term"]
    assert "2 line(s)" in s.kinds_absent["term"]
    assert "claim" not in s.kinds_absent, "a kind that produced units carries no reason"


def test_notes_stays_prose_and_is_not_parsed():
    s = _scan(FULL)
    text = json.dumps([u.payload for u in scan.units_for_source([s])])
    assert "deliberately not parsed" not in text


def test_a_discarded_scan_contributes_nothing_of_any_kind():
    s = scan.parse_text(HEAD.replace("discarded: false", "discarded: true") + FULL)
    assert s.claims and s.entities, "parsing still happens"
    assert scan.units_for_source([s]) == [], "materialization does not"


def test_a_bullet_never_spans_a_section():
    """A new H2 closes the previous section; a field bullet after it belongs to nothing."""
    s = _scan("""
## Entities

- **Acme Corp** - supplies the middleware.

## Novel Concepts
  - role: vendor
""")
    assert s.entities[0].role is None


# --- the whole shape --------------------------------------------------------

def test_all_four_kinds_from_one_scan_are_keyed_apart():
    units = scan.units_for_source([_scan(FULL)])
    assert sorted(u.kind for u in units) == ["claim", "contradiction", "entity", "term"]


def test_the_format_spec_example_parses_into_every_kind():
    """The agent writes scans FROM that document. If its example stops parsing, every scan
    written from it contributes nothing and nothing else would notice — the same writer-vs-reader
    drift `engine/header.py` exists to prevent, one artifact over."""
    spec = Path(__file__).resolve().parents[1] / "bramber-plugin" / "docs" / "FORMAT-SPEC.md"
    text = spec.read_text(encoding="utf-8")
    block = re.search(r"```markdown\n(.*?)\n```", text[text.index("## Scan Schema"):], re.S)
    assert block, "the Scan Schema section must carry a fenced markdown example"
    s = scan.parse_text(block.group(1), path="_bramber/scans/example.md")
    assert sorted(u.kind for u in scan.units_for_source([s])) == [
        "claim", "contradiction", "entity", "term"]
    assert s.kinds_absent == {}, s.kinds_absent


# --- the envelope on disk ---------------------------------------------------

def _materialize(tmp_path: Path, scan_body: str):
    (tmp_path / "_bramber" / "extracts").mkdir(parents=True)
    (tmp_path / "_bramber" / "extracts" / "src.md").write_text(
        "---\ntitle: src\nsource_type: article\n---\nbody\n", encoding="utf-8")
    (tmp_path / "_bramber" / "scans").mkdir(parents=True)
    (tmp_path / "_bramber" / "scans" / "src.md").write_text(HEAD + scan_body, encoding="utf-8")
    return ingest.materialize(tmp_path)


def test_kinds_absent_reaches_the_envelope_on_disk(tmp_path: Path, capsys):
    res = _materialize(tmp_path, """
## Claims

- **CLAIM-001** - something.

## Entities
Prose that predates the machine-readable block.
""")
    env = json.loads((tmp_path / "_bramber" / "units" / "src.json").read_text(encoding="utf-8"))
    assert "predates the machine-readable block" in env["kinds_absent"]["entity"]
    assert res["legacy_section_sources"] == ["src"]
    assert "prose-only" in capsys.readouterr().err


def test_a_fully_migrated_scan_prints_no_warning(tmp_path: Path, capsys):
    res = _materialize(tmp_path, FULL)
    assert res["legacy_section_sources"] == []
    assert capsys.readouterr().err == ""
    env = json.loads((tmp_path / "_bramber" / "units" / "src.json").read_text(encoding="utf-8"))
    assert "kinds_absent" not in env
    assert sorted({u["kind"] for u in env["units"]}) == [
        "claim", "contradiction", "entity", "term"]


def test_a_kind_that_produced_units_is_never_reported_absent(tmp_path: Path):
    """One scan's silence must not mask another's finding for the same source."""
    _materialize(tmp_path, FULL)
    env = json.loads((tmp_path / "_bramber" / "units" / "src.json").read_text(encoding="utf-8"))
    assert "kinds_absent" not in env or "entity" not in env["kinds_absent"]


# --- a malformed bullet must lose only itself --------------------------------

MALFORMED = """
## Claims

- **CLAIM-001** - The date is fixed.
  - evidence: strong
  - recency: 2026-05-01
  - topics: schedule
- CLAIM-002 - The vendor cannot staff before November.
  - evidence: speculative
  - recency: 2026-01-01
  - topics: vendor-risk
"""


def test_a_malformed_bullet_never_transplants_its_fields_onto_the_previous_item():
    """The nastiest shape available here: not a drop but a *transplant*.

    `- CLAIM-002 ...` (bold markers dropped) fails the bullet pattern. If the parser leaves
    `current` pointing at the previous claim, CLAIM-002's own sub-bullets are applied to
    CLAIM-001 — which then reaches the store graded `speculative` and tagged `vendor-risk` when
    its source said `strong` and `schedule`. Every downstream surface, `--trace` included, would
    then report the corrupted value as though the source had given it.
    """
    s = _scan(MALFORMED)
    (c,) = s.claims
    assert c.key == "CLAIM-001"
    assert (c.evidence_strength, c.recency) == ("strong", "2026-05-01")
    assert c.topics == ["schedule"], "CLAIM-002's topics must not land on CLAIM-001"


def test_a_malformed_bullet_is_counted_even_though_the_kind_produced_units():
    """`kinds_absent` is a whole-section control and fires only at zero units, so it cannot see a
    section that parsed two bullets of three. The per-item loss needs a per-item signal."""
    s = _scan(MALFORMED)
    assert "claim" not in s.kinds_absent, "the section is not absent — it produced a unit"
    assert s.kinds_unparsed["claim"]["lost"] >= 1, "the lost item must be counted somewhere"


def test_lost_counts_reach_the_envelope_and_the_operator(tmp_path: Path, capsys):
    res = _materialize(tmp_path, MALFORMED)
    env = json.loads((tmp_path / "_bramber" / "units" / "src.json").read_text(encoding="utf-8"))
    assert env["kinds_unparsed"]["claim"]["lost"] >= 1
    assert res["lost_sources"] == ["src"]
    assert "produced NO unit" in capsys.readouterr().err


# --- a line INSIDE a well-formed item must not cost that item its later fields ---
#
# The shape no test covered, which is why a 254-green suite did not see the regression that
# dropping the carry-over on *every* unmatched line introduced.

WRAPPED = """
## Contradictions

- **CONTRA-001** - The minutes and the transcript disagree.
  - side: CLAIM-007 | _bramber/extracts/m.md | recorded as fixed
  - resolution: the minutes postdate the meeting and omit the caveat the
    transcript carries
  - status: proposed
  - topics: deadline-integrity
"""

NESTED = """
## Entities

- **Acme Corp** - supplies the middleware.
  - role: vendor
  - aliases:
    - Acme
    - ACME Corporation
  - topics: vendor-risk
"""


def test_a_wrapped_field_value_does_not_cost_the_item_its_later_fields():
    """A `resolution:` long enough to wrap is ordinary output from a language model writing
    markdown — FORMAT-SPEC's own example value is 68 characters. The continuation line cannot
    introduce a new item, so it can misattribute nothing and must not drop the carry-over."""
    (c,) = _scan(WRAPPED).contradictions
    assert c.resolution_status == "proposed", "the field AFTER the wrapped line must survive"
    assert c.topics == ["deadline-integrity"]
    assert len(c.sides) == 1


def test_a_nested_sublist_does_not_cost_the_item_its_later_fields():
    (e,) = _scan(NESTED).entities
    assert e.role == "vendor"
    assert e.topics == ["vendor-risk"], "the field after the nested list must survive"


def test_an_unplaceable_line_inside_an_item_is_counted_as_truncation_not_loss():
    """The two degrades are different facts and the notice text differs, so one counter standing
    for both would make whichever notice printed false for the other case."""
    s = _scan(WRAPPED)
    counts = s.kinds_unparsed["contradiction"]
    assert counts["truncated"] >= 1
    assert counts["lost"] == 0, "nothing was lost — the item materialized"


def test_the_two_degrades_are_reported_to_the_operator_in_their_own_words(tmp_path: Path, capsys):
    res = _materialize(tmp_path, WRAPPED)
    err = capsys.readouterr().err
    assert res["truncated_sources"] == ["src"]
    assert res["lost_sources"] == []
    assert "DID produce a unit" in err
    assert "produced NO unit" not in err, "the notice must not assert the case that did not occur"


def test_a_truncated_item_still_reaches_the_store(tmp_path: Path):
    """The distinction that makes truncation worth its own notice: the unit is REAL and
    under-populated, so a view selecting on the missing field silently excludes it."""
    _materialize(tmp_path, WRAPPED)
    env = json.loads((tmp_path / "_bramber" / "units" / "src.json").read_text(encoding="utf-8"))
    (u,) = [u for u in env["units"] if u["kind"] == "contradiction"]
    assert u["payload"]["resolution_status"] == "proposed"
    assert env["kinds_unparsed"]["contradiction"]["truncated"] >= 1


def test_a_well_formed_scan_reports_no_unparsed_lines():
    assert _scan(FULL).kinds_unparsed == {}
    assert _scan(WRAPPED + NESTED).kinds_unparsed.get("entity", {}).get("lost", 0) == 0


def test_a_sentinel_also_drops_the_carry_over():
    """`None identified` between two bullets must not leave the earlier item live."""
    s = _scan("""
## Entities

- **Acme Corp** - supplies the middleware.
None identified.
  - role: vendor
""")
    assert s.entities[0].role is None


# --- the mint-or-reuse feed must publish every key it merges on ---------------

def test_the_feed_publishes_every_key_minting_section(tmp_path: Path):
    """The F1 hazard, as a structural assertion rather than a spot check.

    A kind that merges on an agent-assigned key MUST appear in the feed the agent consults, or
    two sources assign that key to unrelated things and the merge reports corroboration neither
    gave. Deriving both sides from `_SECTIONS.mints_keys` is what stops them drifting apart —
    which they had, with claims fed and contradictions not.
    """
    (tmp_path / "_bramber" / "scans").mkdir(parents=True)
    (tmp_path / "_bramber" / "scans" / "src.md").write_text(HEAD + FULL, encoding="utf-8")

    fed = {e["kind"] for e in scan.known_keys(tmp_path)}
    declared = {s["kind"] for s in scan._SECTIONS.values() if s["mints_keys"]}
    assert fed == declared, f"key-minting kinds absent from the feed: {sorted(declared - fed)}"
    assert "contradiction" in fed, "the exact asymmetry that made two tensions merge into one"


def test_known_keys_carries_contradiction_keys_with_their_sources(tmp_path: Path):
    (tmp_path / "_bramber" / "scans").mkdir(parents=True)
    (tmp_path / "_bramber" / "scans" / "src.md").write_text(HEAD + FULL, encoding="utf-8")
    ref = scan.srcref_for("_bramber/extracts/src.md")
    contra = [e for e in scan.known_keys(tmp_path) if e["kind"] == "contradiction"]
    assert [e["key"] for e in contra] == [f"CONTRA-{ref}-001"], \
        "the feed must publish the QUALIFIED key, since that is what a reuse copies"
    assert contra[0]["sources"] == ["_bramber/extracts/src.md"]


# --- key namespaces: the collision defect, closed structurally ---------------

def _two_sources_both_minting_001(tmp_path: Path):
    """Two agents, no communication, both reading a feed that ended at 000, both minting 001 for
    UNRELATED claims. This is the reproduction of the defect verbatim."""
    (tmp_path / "_bramber" / "extracts").mkdir(parents=True)
    (tmp_path / "_bramber" / "scans").mkdir(parents=True)
    for slug, statement in (("minutes_md__aaaaaaaa", "The date is fixed."),
                            ("review_md__bbbbbbbb", "The vendor cannot staff before November.")):
        (tmp_path / "_bramber" / "extracts" / f"{slug}.md").write_text(
            "---\ntitle: t\nsource_type: article\n---\nbody\n", encoding="utf-8")
        (tmp_path / "_bramber" / "scans" / f"{slug}.md").write_text(
            f"---\nsource: _bramber/extracts/{slug}.md\nscan_date: 2026-08-07\n"
            f"discarded: false\n---\n\n## Claims\n\n- **CLAIM-001** - {statement}\n"
            f"  - evidence: strong\n", encoding="utf-8")


def test_two_sources_minting_the_same_bare_key_do_not_collide(tmp_path: Path):
    """The defect: both minted `CLAIM-001`, selection merged them, and the register reported
    support 2 for a claim neither source made twice. Namespacing makes that unreachable — the two
    agents cannot produce one key even though neither knew about the other."""
    _two_sources_both_minting_001(tmp_path)
    ingest.materialize(tmp_path)

    keys = [e["key"] for e in scan.known_keys(tmp_path)]
    assert len(set(keys)) == 2, f"two independent mints must stay two claims: {keys}"
    assert set(keys) == {"CLAIM-aaaaaaaa-001", "CLAIM-bbbbbbbb-001"}
    for e in scan.known_keys(tmp_path):
        assert len(e["sources"]) == 1, "neither claim may claim corroboration it never had"


def test_the_migration_hazard_is_classified_but_no_longer_reported(tmp_path: Path, capsys):
    """The bucket outlives its notice. Retired 2026-08-12 →
    the 2026-08-12 ruling "the bare key notice is retired".

    It was a MIGRATION guard: before namespacing, a bare key repeated across sources meant
    corroboration and merged, so a repeat was a decision someone had to make. Its founding record
    states no corpus had been scanned under this pipeline on the day it was written, so the
    population was empty then and stayed empty. After namespacing, FORMAT-SPEC has every scan
    number from 1, so sources share ordinals BY CONSTRUCTION and the bucket re-derives the
    claims-per-source histogram — 46,623 characters of it on the first real corpus, printed ahead
    of the seven notices that can carry a real defect.

    The classification itself is unchanged and still correct, so the datum is still returned:
    the merge-precision eval measures against it.

    Reddens by restoring the `print` in `ingest.materialize` (stderr assertion), or by dropping
    the key from its return dict (the first assertion).
    """
    _two_sources_both_minting_001(tmp_path)
    res = ingest.materialize(tmp_path)
    assert res["ambiguous_bare_keys"] == ["claim:CLAIM-001"]

    err = capsys.readouterr().err
    assert "minted BARE" not in err
    assert "more than one source" not in err


def test_a_witnessed_reuse_merges(tmp_path: Path):
    """The other half: the ledger must not cost corroboration. A source copying the `reuse_as`
    token the feed publishes — key and witness as one atom — merges, and the merged claim
    carries both sources."""
    _two_sources_both_minting_001(tmp_path)
    tok = scan.statement_token("The date is fixed.")
    p = tmp_path / "_bramber" / "scans" / "review_md__bbbbbbbb.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "**CLAIM-001**", f"**CLAIM-aaaaaaaa-001={tok}**"), encoding="utf-8")
    res = ingest.materialize(tmp_path)

    (entry,) = scan.known_keys(tmp_path)
    assert entry["key"] == "CLAIM-aaaaaaaa-001"
    assert len(entry["sources"]) == 2, "a witnessed reuse records corroboration"
    assert res["ambiguous_bare_keys"] == [], "an explicit reuse is not ambiguous"
    assert res["witness_mismatch_keys"] == [] and res["unwitnessed_keys"] == []


def test_a_reuse_naming_an_unknown_namespace_is_reported(tmp_path: Path, capsys):
    """A qualified key is a corroboration, so its namespace must belong to a source here. When it
    does not, the key is still well-formed and becomes an ordinary INDEPENDENT claim with support
    1 — the exact opposite of the intent — and nothing else would ever say so."""
    _two_sources_both_minting_001(tmp_path)
    p = tmp_path / "_bramber" / "scans" / "review_md__bbbbbbbb.md"
    p.write_text(p.read_text(encoding="utf-8").replace("**CLAIM-001**", "**CLAIM-deadbeef-001**"),
                 encoding="utf-8")
    res = ingest.materialize(tmp_path)

    assert res["unresolvable_keys"] == ["CLAIM-deadbeef-001"]
    err = capsys.readouterr().err
    assert "resolve to nothing this corpus minted" in err
    assert "review_md__bbbbbbbb" in err
    assert len(scan.known_keys(tmp_path)) == 2, "it did not merge — that is what makes it a defect"


def test_a_correct_reuse_is_not_reported_as_unresolvable(tmp_path: Path):
    _two_sources_both_minting_001(tmp_path)
    p = tmp_path / "_bramber" / "scans" / "review_md__bbbbbbbb.md"
    p.write_text(p.read_text(encoding="utf-8").replace("**CLAIM-001**", "**CLAIM-aaaaaaaa-001**"),
                 encoding="utf-8")
    assert ingest.materialize(tmp_path)["unresolvable_keys"] == []


def _corpus(tmp_path: Path, *sources):
    """(slug, key, statement) triples -> a materializable corpus."""
    (tmp_path / "_bramber" / "extracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "_bramber" / "scans").mkdir(parents=True, exist_ok=True)
    for slug, key, statement in sources:
        (tmp_path / "_bramber" / "extracts" / f"{slug}.md").write_text(
            "---\ntitle: t\nsource_type: article\n---\nbody\n", encoding="utf-8")
        (tmp_path / "_bramber" / "scans" / f"{slug}.md").write_text(
            f"---\nsource: _bramber/extracts/{slug}.md\nscan_date: 2026-08-07\n"
            f"discarded: false\n---\n\n## Claims\n\n- **{key}** - {statement}\n"
            f"  - evidence: strong\n", encoding="utf-8")


def test_a_date_shaped_bare_key_is_a_mint_not_a_reuse(tmp_path: Path):
    """Every decimal digit is a hex digit, so a shape test read `CLAIM-20260107-1` as an
    already-qualified reuse and two sources authoring it merged to support 2 — verbatim the
    collision this design exists to close, arriving through the classifier instead."""
    _corpus(tmp_path,
            ("minutes_md__aaaaaaaa", "CLAIM-20260107-1", "The cutover date is fixed."),
            ("review_md__bbbbbbbb", "CLAIM-20260107-1", "The vendor cannot staff in November."))
    ingest.materialize(tmp_path)

    keys = scan.known_keys(tmp_path)
    assert len(keys) == 2, f"two unrelated claims must stay two: {[k['key'] for k in keys]}"
    assert all(len(k["sources"]) == 1 for k in keys), "neither may claim corroboration"


def test_a_never_minted_number_in_a_real_namespace_does_not_fabricate_support(tmp_path: Path):
    """The namespace segment is caller-supplied. Checking only that the namespace EXISTS let two
    sources write `CLAIM-<real-ns>-042` — a number that source never minted — and merge into
    fabricated support, with both reporters silent because the namespace resolved."""
    _corpus(tmp_path,
            ("minutes_md__aaaaaaaa", "CLAIM-001", "The cutover date is fixed."),
            ("review_md__bbbbbbbb", "CLAIM-aaaaaaaa-042", "Headcount will grow by forty."),
            ("plan_md__cccccccc", "CLAIM-aaaaaaaa-042", "The vendor cannot staff in November."))
    res = ingest.materialize(tmp_path)

    by_key = {k["key"]: k for k in scan.known_keys(tmp_path)}
    fabricated = [k for k, v in by_key.items() if len(v["sources"]) > 1]
    assert not fabricated, f"a never-minted key must not gain support: {fabricated}"
    assert res["unresolvable_keys"] == ["CLAIM-aaaaaaaa-042"], "and it must be reported"


def test_a_hyphenated_prefix_survives_the_publish_copy_round_trip(tmp_path: Path):
    """`CLAIM_RE` admits `-` in a key. A shape test whose prefix did not made the feed publish a
    key its own reader rejected: a verbatim copy failed to re-match, was stamped again, reuse
    silently stopped merging, and the key grew 9 characters every round."""
    _corpus(tmp_path, ("minutes_md__aaaaaaaa", "RISK-OPS-001", "The cutover date is fixed."))
    ingest.materialize(tmp_path)
    entry = scan.known_keys(tmp_path)[0]
    published, reuse_as = entry["key"], entry["reuse_as"]
    assert reuse_as == f"{published}={entry['witness']}", "the feed publishes one copyable atom"

    # A second source corroborates by copying exactly what the feed printed under reuse_as.
    _corpus(tmp_path, ("review_md__bbbbbbbb", reuse_as, "The cutover date is fixed."))
    ingest.materialize(tmp_path)

    keys = scan.known_keys(tmp_path)
    assert len(keys) == 1, f"the copy must merge, not split: {[k['key'] for k in keys]}"
    assert keys[0]["key"] == published, "and the key must not grow on the round trip"
    assert len(keys[0]["sources"]) == 2


def test_a_source_rewriting_its_own_qualified_key_does_not_restamp(tmp_path: Path):
    """The other direction of the same round trip: idempotence within one namespace."""
    _corpus(tmp_path, ("minutes_md__aaaaaaaa", "CLAIM-aaaaaaaa-001", "The date is fixed."))
    ingest.materialize(tmp_path)
    (k,) = scan.known_keys(tmp_path)
    assert k["key"] == "CLAIM-aaaaaaaa-001"


def test_classification_is_set_membership_not_shape(tmp_path: Path):
    """The structural statement of all three findings at once: a key resolves as a reuse ONLY by
    naming something a source actually minted AND quoting its statement. No pattern on the text
    may decide it."""
    tok = scan.statement_token("The date is fixed.")
    _corpus(tmp_path,
            ("minutes_md__aaaaaaaa", "CLAIM-001", "The date is fixed."),
            ("review_md__bbbbbbbb", f"CLAIM-aaaaaaaa-001={tok}", "The date is fixed."))
    scans = [s for s in scan.read_all(tmp_path) if s.source]
    res = scan.resolve_keys(scans, [s.source for s in scans])

    assert ("claim", "CLAIM-aaaaaaaa-001") in res.minted
    assert res.unresolvable == {} and res.witness_mismatch == {}
    finals = set(res.resolution.values())
    assert finals == {"CLAIM-aaaaaaaa-001"}, "the reuse resolves to the minted key, not a new one"


# --- witnessed endorsement: a reuse must quote what it endorses ---------------

def test_a_reuse_naming_the_wrong_minted_key_does_not_merge(tmp_path: Path):
    """THE misdirection case, and the reason the witness exists. Source A mints -001 (the date)
    and -002 (headcount). B means to corroborate -001 — its witness quotes the date statement —
    but the key slipped to -002. Both keys are REAL, so every existence check passes; before the
    witness this merged silently and the headcount claim gained an endorsement from a source
    that was talking about the date."""
    tok_001 = scan.statement_token("The cutover date is fixed.")
    _corpus(tmp_path,
            ("minutes_md__aaaaaaaa", "CLAIM-001", "The cutover date is fixed."))
    # add A's second claim to the same scan
    p = tmp_path / "_bramber" / "scans" / "minutes_md__aaaaaaaa.md"
    p.write_text(p.read_text(encoding="utf-8")
                 + "- **CLAIM-002** - Headcount grows by forty in Q4.\n  - evidence: strong\n",
                 encoding="utf-8")
    _corpus(tmp_path,
            ("review_md__bbbbbbbb", f"CLAIM-aaaaaaaa-002={tok_001}",
             "The date was confirmed as fixed."))
    res = ingest.materialize(tmp_path)

    by_key = {k["key"]: k for k in scan.known_keys(tmp_path)}
    assert len(by_key["CLAIM-aaaaaaaa-002"]["sources"]) == 1, \
        "the headcount claim must not gain support from a source discussing the date"
    assert res["witness_mismatch_keys"] == ["CLAIM-aaaaaaaa-002"]


def test_a_mismatch_report_suggests_the_key_the_witness_matches(tmp_path: Path, capsys):
    """The remedy line: the witness uniquely identifies what the author READ, so the notice can
    name the key they probably meant instead of leaving them to diff the feed by eye."""
    tok_001 = scan.statement_token("The cutover date is fixed.")
    _corpus(tmp_path, ("minutes_md__aaaaaaaa", "CLAIM-001", "The cutover date is fixed."))
    p = tmp_path / "_bramber" / "scans" / "minutes_md__aaaaaaaa.md"
    p.write_text(p.read_text(encoding="utf-8")
                 + "- **CLAIM-002** - Headcount grows by forty in Q4.\n  - evidence: strong\n",
                 encoding="utf-8")
    _corpus(tmp_path, ("review_md__bbbbbbbb", f"CLAIM-aaaaaaaa-002={tok_001}",
                       "The date was confirmed as fixed."))
    ingest.materialize(tmp_path)
    err = capsys.readouterr().err
    assert "does NOT match" in err
    assert "CLAIM-aaaaaaaa-001" in err, "the suggestion names the mint the witness quotes"


def test_an_unwitnessed_resolving_reuse_is_refused_and_reported(tmp_path: Path, capsys):
    """A bare qualified key resolves — and merging on it would reopen the wrong-minted-key hole
    for exactly the keys where it matters. Refused, kept as the author's own claim, reported."""
    _corpus(tmp_path,
            ("minutes_md__aaaaaaaa", "CLAIM-001", "The date is fixed."),
            ("review_md__bbbbbbbb", "CLAIM-aaaaaaaa-001", "The date is fixed, per the minutes."))
    res = ingest.materialize(tmp_path)

    keys = scan.known_keys(tmp_path)
    assert all(len(k["sources"]) == 1 for k in keys), "no merge without a witness"
    assert res["unwitnessed_keys"] == ["CLAIM-aaaaaaaa-001"]
    assert "carry no witness" in capsys.readouterr().err


def test_witness_tokens_anchor_to_the_minters_statement(tmp_path: Path):
    """The corroborator phrases the claim its own way — that is the point of agent-judged
    sameness — so the feed's witness must quote the MINTER's statement, stably, whichever scan
    happens to sort first."""
    tok = scan.statement_token("The cutover date is fixed.")
    _corpus(tmp_path,
            # 'a_' sorts before 'minutes_': the corroborator's scan is read first.
            ("a_review_md__bbbbbbbb", f"CLAIM-aaaaaaaa-001={tok}", "Confirmed as fixed."),
            ("minutes_md__aaaaaaaa", "CLAIM-001", "The cutover date is fixed."))
    ingest.materialize(tmp_path)
    (entry,) = scan.known_keys(tmp_path)
    assert entry["witness"] == tok, "the witness quotes the minter, not the first file read"
    assert entry["statement"] == "The cutover date is fixed.", \
        "and the displayed statement is the one the witness quotes"
    assert entry["reuse_as"] == f"CLAIM-aaaaaaaa-001={tok}"
    assert len(entry["sources"]) == 2


def test_a_witness_on_a_mint_is_ignored_and_surfaced(tmp_path: Path, capsys):
    """A witness on a mint endorses nothing — no merge hangs on it — so it cannot corrupt the
    store; but it signals the author misread the convention, so it reaches the return value.
    Deliberately not stderr: it is confusion, not loss."""
    _corpus(tmp_path, ("minutes_md__aaaaaaaa", "CLAIM-001=abcdef", "The date is fixed."))
    res = ingest.materialize(tmp_path)
    (entry,) = scan.known_keys(tmp_path)
    assert entry["key"] == "CLAIM-aaaaaaaa-001", "the unit is unharmed"
    assert res["stray_witness_keys"] == ["CLAIM-001"]
    assert "witness" not in capsys.readouterr().err.lower()


def test_a_degraded_reuse_is_itself_reusable(tmp_path: Path):
    """A refused endorsement becomes the author's own claim, and a claim that exists must be
    endorsable however it came to exist — so the feed publishes a reuse_as for it too."""
    _corpus(tmp_path,
            ("minutes_md__aaaaaaaa", "CLAIM-001", "The date is fixed."),
            ("review_md__bbbbbbbb", "CLAIM-aaaaaaaa-001", "The date is fixed, per the minutes."))
    ingest.materialize(tmp_path)
    # The degraded key keeps the authored text and gains B's namespace before the tail:
    # CLAIM-aaaaaaaa-bbbbbbbb-001. Deliberate on both counts — the mistyped intent stays
    # visible in the key, and it cannot collide with a bare CLAIM-001 B might also mint
    # (which would stamp to CLAIM-bbbbbbbb-001, a different string).
    degraded = [k for k in scan.known_keys(tmp_path)
                if scan._namespace_of(k["key"]) == "bbbbbbbb"]
    assert degraded and degraded[0]["key"] == "CLAIM-aaaaaaaa-bbbbbbbb-001"
    assert degraded[0]["witness"], "the degraded claim carries its own witness"
    assert degraded[0]["reuse_as"].endswith(f"={degraded[0]['witness']}")


def test_a_shared_key_namespace_is_refused_not_assumed(tmp_path: Path):
    """The namespace is 8 hex of a content_sha, so distinct sources collide with probability
    ~N^2/2^33. Small is not impossible, and the entire argument for namespacing over locking is
    that the guarantee is structural rather than probable — so it is checked."""
    with pytest.raises(SystemExit, match="shared by more than one source"):
        scan.check_srcref_uniqueness(["_bramber/extracts/a_md__cafebabe.md",
                                      "_bramber/extracts/b_md__cafebabe.md"])


def test_materialize_actually_runs_the_uniqueness_check(tmp_path: Path):
    """A guard with no test that it is CALLED is a guard that can be deleted silently — the screen
    verified exactly that by removing the call site and watching 271/271 stay green. This asserts
    the wiring, not the predicate."""
    _corpus(tmp_path,
            ("a_md__cafebabe", "CLAIM-001", "one"),
            ("b_md__cafebabe", "CLAIM-002", "two"))       # same 8-hex namespace, two sources
    with pytest.raises(SystemExit, match="shared by more than one source"):
        ingest.materialize(tmp_path)


def test_distinct_namespaces_pass_the_check():
    scan.check_srcref_uniqueness(["_bramber/extracts/a_md__cafebabe.md",
                                  "_bramber/extracts/b_md__deadbeef.md"])


def test_a_slug_without_an_identity_suffix_still_gets_a_stable_namespace():
    """Total and deterministic rather than having a shape it refuses — a hand-built fixture or a
    pre-convention extract must still land in some namespace, and the same one every run."""
    a = scan.srcref_for("_bramber/extracts/plain.md")
    assert a == scan.srcref_for("_bramber/extracts/plain.md")
    assert a != scan.srcref_for("_bramber/extracts/other.md")
    assert len(a) == 8


def test_known_claims_is_a_projection_of_the_one_feed(tmp_path: Path):
    """Two independent walks of the scans is how the asymmetry arose in the first place."""
    (tmp_path / "_bramber" / "scans").mkdir(parents=True)
    (tmp_path / "_bramber" / "scans" / "src.md").write_text(HEAD + FULL, encoding="utf-8")
    assert [c["claim_key"] for c in scan.known_claims(tmp_path)] == [
        e["key"] for e in scan.known_keys(tmp_path) if e["kind"] == "claim"]


# --- the publish -> copy -> resolve round trip -------------------------------
# the 2026-08-11 ruling "stamp is made total the migration premise was false", superseding
# §3/§6 of `…2026-08-10-a-key-that-cannot-round-trip-is-never-published-as-reusable.md`.
# Screen finding N1 was that `_stamp` APPENDED for an authored key with no hyphen, so the stored
# key had two segments and `_namespace_of` returned None. `_stamp` is total now: the class cannot
# be produced, and the publish-boundary guard is kept only as a falsifier for the NEXT shape.


def test_stamp_is_total_so_every_stored_key_carries_a_readable_namespace(tmp_path: Path):
    """The construction guarantee, asserted over shapes rather than over one corpus.

    Enumerated deliberately: hyphen-free is the case N1 found, but `_` is in `CLAIM_RE`'s charset
    and a trailing hyphen parses too, and neither was pictured when the class was first called
    closed. A test that only ran the shape somebody predicted is how N1 survived a fix that said
    the class was closed by construction."""
    for authored in ("FINDING", "CLAIM_007", "CLAIM007", "X", "CLAIM-001", "RISK-OPS-001",
                     "FINDING-", "A_B_C"):
        stored = scan._stamp(authored, "aaaaaaaa")
        assert scan._namespace_of(stored) == "aaaaaaaa", \
            f"{authored!r} -> {stored!r}: the namespace must be readable at a fixed position"
        assert scan._round_trips(stored), \
            f"{authored!r} -> {stored!r}: publish -> copy -> resolve must be the identity"


def test_a_hyphen_free_key_is_published_as_reusable_and_corroborates(tmp_path: Path):
    """The behaviour the boundary guard could only refuse: an endorser copies the token whole and
    the support is RECORDED. The control is in the same test because the defect was invisible
    precisely when the ordinary key did the right thing."""
    _corpus(tmp_path,
            ("a_md__aaaaaaaa", "FINDING", "The cutover date is fixed."),   # no hyphen
            ("b_md__bbbbbbbb", "CLAIM-001", "The budget is unchanged."))   # ordinary
    feed = {e["key"]: e for e in scan.known_keys(tmp_path)}

    was_bad = feed["FINDING-aaaaaaaa-0"]
    assert was_bad["reuse_as"] == f"FINDING-aaaaaaaa-0={was_bad['witness']}", \
        "a key that round-trips must be publishable — withholding it cost a corroboration"
    assert was_bad["no_reuse_reason"] is None

    ok = feed["CLAIM-bbbbbbbb-001"]
    assert ok["reuse_as"] == f"CLAIM-bbbbbbbb-001={ok['witness']}"
    assert ok["no_reuse_reason"] is None

    # End to end: the endorsement the old shape dropped now merges.
    _corpus(tmp_path, ("c_md__cccccccc", was_bad["reuse_as"], "Gamma agrees on the cutover."))
    ingest.materialize(tmp_path)
    merged = {e["key"]: e for e in scan.known_keys(tmp_path)}["FINDING-aaaaaaaa-0"]
    assert len(merged["sources"]) == 2, \
        f"a verbatim copy of a published token must corroborate: {merged['sources']}"


def test_two_authored_keys_one_character_apart_never_share_a_stored_key(tmp_path: Path):
    """Totality is not injectivity. `FINDING` and `FINDING-0` in ONE source both stamp to
    `FINDING-<ns>-0`; sharing it would merge two distinct claims into one unit — a merge nobody
    judged, in the unrecoverable direction, introduced by the fix for a hole in the same one."""
    (tmp_path / "_bramber" / "extracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "_bramber" / "scans").mkdir(parents=True, exist_ok=True)
    (tmp_path / "_bramber" / "extracts" / "a_md__aaaaaaaa.md").write_text(
        "---\ntitle: t\nsource_type: article\n---\nbody\n", encoding="utf-8")
    (tmp_path / "_bramber" / "scans" / "a_md__aaaaaaaa.md").write_text(
        "---\nsource: _bramber/extracts/a_md__aaaaaaaa.md\nscan_date: 2026-08-11\n"
        "discarded: false\n---\n\n## Claims\n\n"
        "- **FINDING** - The cutover date is fixed.\n  - evidence: strong\n"
        "- **FINDING-0** - The vendor cannot staff in November.\n  - evidence: weak\n",
        encoding="utf-8")

    scans = [s for s in scan.read_all(tmp_path) if s.source]
    res = scan.resolve_keys(scans, [s.source for s in scans])
    finals = {res.final(s.path, "claim", k) for s in scans for k in ("FINDING", "FINDING-0")}
    assert len(finals) == 2, f"two distinct claims collapsed into one stored key: {finals}"

    statements = {e["key"]: e["statement"] for e in scan.known_keys(tmp_path)}
    assert len(statements) == 2 and "The vendor cannot staff in November." in statements.values(), \
        "neither claim may be silently dropped by the collapse rule"
    assert "FINDING" in res.key_collisions, \
        "an escalated sentinel is a scan defect a human should repair — it must be named"


def test_every_published_reuse_token_survives_the_round_trip(tmp_path: Path):
    """Derived on both sides rather than transcribed: whether a token is published is read from
    the feed, whether it round-trips is recomputed from the stored key. A future key shape that
    breaks the identity fails here without anyone having predicted that shape — which is the
    property the previous fix's 'closed by construction' argument lacked."""
    _corpus(tmp_path,
            ("a_md__aaaaaaaa", "FINDING", "one"),
            ("b_md__bbbbbbbb", "CLAIM-001", "two"),
            ("c_md__cccccccc", "CLAIM_007", "three"),      # `_` is in the key charset
            ("d_md__dddddddd", "RISK-A-2", "four"))
    for e in scan.known_keys(tmp_path):
        published = e["reuse_as"] is not None
        assert published == scan._round_trips(e["key"]), \
            f"{e['key']}: published={published} but round_trips={scan._round_trips(e['key'])}"


def test_a_token_a_segment_short_is_named_rather_than_silently_minted(tmp_path: Path):
    """The residue after totality, and the reason the buckets are kept.

    The two-segment stored key can no longer be MINTED, so `lost_endorsement` — whose subject is
    a key the corpus really minted — is unreachable by construction. What survives is a token
    assembled by hand, or copied a segment short: it names nothing this corpus minted, so it is
    stamped as the author's own claim. That is the safe direction, but it must not be SILENT —
    the whole of N1 was that every reporting bucket stayed empty."""
    _corpus(tmp_path, ("a_md__aaaaaaaa", "FINDING", "The cutover date is fixed."))
    tok = scan.statement_token("The cutover date is fixed.")
    # `FINDING-aaaaaaaa-0` is what the feed publishes; this drops the last segment.
    _corpus(tmp_path, ("b_md__bbbbbbbb", f"FINDING-aaaaaaaa={tok}", "Beta says so too."))
    scans = [s for s in scan.read_all(tmp_path) if s.source]
    res = scan.resolve_keys(scans, [s.source for s in scans])

    assert "FINDING-aaaaaaaa" in res.stray_witness, \
        "a witness riding a key nobody minted must be named, not dropped"
    assert res.lost_endorsement == {}, \
        "unreachable now: every minted key carries a namespace, so a verbatim copy is a reuse"
    assert res.final("_bramber/scans/b_md__bbbbbbbb.md", "claim", "FINDING-aaaaaaaa") \
        == "FINDING-bbbbbbbb-aaaaaaaa", "and the author keeps their assertion as their own claim"


def test_the_publish_guard_never_fires_on_a_key_this_code_can_produce(tmp_path: Path, capsys):
    """The superseded record's §6 instruction: keep the assertion, because it is what makes the
    NEXT unpictured key shape loud. Kept means kept honest — this pins that it is unreachable
    across every shape the parser admits, so a future `_stamp` that stops being total fails here
    rather than quietly withholding tokens again."""
    _corpus(tmp_path,
            ("a_md__aaaaaaaa", "FINDING", "one"),
            ("b_md__bbbbbbbb", "CLAIM-001", "two"),
            ("c_md__cccccccc", "CLAIM_007", "three"),      # `_` is in the key charset
            ("d_md__dddddddd", "RISK-A-2", "four"),
            ("e_md__eeeeeeee", "CLAIM-", "five"))          # a trailing hyphen parses too
    feed = scan.known_keys(tmp_path)
    assert len(feed) == 5, "the corpus must actually exercise five shapes, or this is vacuous"
    for e in feed:
        assert e["no_reuse_reason"] is None and e["reuse_as"] is not None, \
            f"{e['key']}: the guard fired on a key this code produced — `_stamp` is not total"

    ingest.materialize(tmp_path)
    assert "no readable namespace" not in capsys.readouterr().err


def test_a_reuse_of_a_degraded_reuse_does_not_depend_on_the_filename(tmp_path: Path):
    """Resolution must not depend on where a scan's filename happens to sort.

    A degraded reuse — a real namespace, a number that source never minted — is re-stamped into
    the author's own namespace and survives as their own claim. `resolve_keys` then registered
    that new key into `minted` and `token_of` **as it iterated**, and `authored` is built in
    `scan_files`' filename order. So a third source endorsing that claim resolved only if its
    scan happened to sort AFTER the one it endorsed: support 2 one way, support 1 the other, on
    byte-identical content with one file renamed.

    The registration is deferred to after the loop now, so every reuse in a pass is resolved
    against the same set. Within a pass that errs toward under-merge, which is the recoverable
    direction (`specs/07 §3.2`); the key is still published, so the next pass can endorse it —
    pinned by the second assertion, which is what stops this being fixed by over-refusing.

    Reddens when the deferral is removed (register inside the loop again): 2 against 1.
    -> work/criteria AC-15
    """
    DEGRADED = "CLAIM-aaaaaaaa-999"          # `aaaaaaaa` is a real namespace; it never minted -999
    support, published = {}, {}
    for endorser in ("aaa_review_md__cccccccc", "zzz_review_md__cccccccc"):
        root = tmp_path / endorser[:3]
        _corpus(root,
                ("minutes_md__aaaaaaaa", "CLAIM-001", "The cutover date is fixed."),
                ("mid_md__bbbbbbbb", DEGRADED, "Headcount grows by forty in Q4."))
        scans = [s for s in scan.read_all(root) if s.source]
        res = scan.resolve_keys(scans, [s.source for s in scans])
        restamped = res.final("_bramber/scans/mid_md__bbbbbbbb.md", "claim", DEGRADED)

        tok = scan.statement_token("Headcount grows by forty in Q4.")
        _corpus(root, (endorser, f"{restamped}={tok}", "Forty more people arrive in Q4."))
        scans = [s for s in scan.read_all(root) if s.source]
        res = scan.resolve_keys(scans, [s.source for s in scans])

        support[endorser[:3]] = sum(1 for v in res.resolution.values() if v == restamped)
        published[endorser[:3]] = ("claim", restamped) in res.minted

    assert support["aaa"] == support["zzz"], \
        f"identical corpora, one filename changed, different support: {support}"
    assert published == {"aaa": True, "zzz": True}, \
        "a claim that exists must stay endorsable, however it came to exist"
