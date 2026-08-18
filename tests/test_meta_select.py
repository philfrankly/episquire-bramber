"""Cross-cutting selection (`bramber/meta.py`).

`compile.py` answers what one view projects. This module answers what the corpus says as a whole,
for the documents that are about the record rather than a perspective on it.

**Most of this file's predecessor tested a guard that no longer has a hazard to guard.** Until
2026-08-07 extraction ran per (source × view) and each view minted its own `CLAIM-001`, so a
cross-view join had to refuse anything agent-assigned or it would report corroboration no source
gave. There is one store now and every key in it is unique across the corpus, so those tests were
retired with the mechanism — see the addendum to
the 2026-08-06 ruling "minted and observed keys". What replaces them is asserted below:
`test_verify_join_no_longer_has_a_namespace_property` pins that the retirement was deliberate.

Two properties carry most of the weight now:

  - **selection keeps one representative, and for a glossary that is fatal.** `variants` is the
    additive pass that keeps every contributor, so two incompatible definitions of one word are
    both on the page rather than one silently winning on filename order;
  - **merging never invents a source.** One source cited by two feeds counts once, because
    `select_units` dedups merged provenance on `extract_path`. That is not implemented here — it
    falls out of reusing that function — and asserting it is what makes the reuse safe rather
    than merely convenient.

Run:  cd bramber && python -m pytest tests/test_meta_select.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bramber import compile as compile_mod
from bramber import meta
from bramber.meta import UnsafeJoin


# --- fixtures ---------------------------------------------------------------

def _units_file(tmp_path: Path, slug: str, units: list[dict]) -> Path:
    p = tmp_path / "_bramber" / "units" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "extract_path": f"_bramber/extracts/{slug}.md",
        "qname": slug,
        "units_produced_by": "test fixture",
        "units": units,
    }), encoding="utf-8")
    return p


def _prov(slug: str, tier: str):
    return {"source_artifacts": [{
        "extract_path": f"_bramber/extracts/{slug}.md",
        "scan_path": f"_bramber/scans/{slug}.md",
        "reliability_tier": tier}]}


def _claim(key, statement, *, slug, topics=None, tier="reported"):
    return {"kind": "claim",
            "payload": {"claim_key": key, "statement": statement,
                        "evidence_strength": "strong", "recency": "2026-05-01",
                        "topics": topics if topics is not None else []},
            "provenance": _prov(slug, tier)}


def _entity(entity_key, gloss, *, slug, tier="reported", topics=None):
    return {"kind": "entity",
            "payload": {"entity_key": entity_key, "entity_name": entity_key.title(),
                        "gloss": gloss, "role": "supplier",
                        "topics": topics if topics is not None else []},
            "provenance": _prov(slug, tier)}


def _contradiction(key, statement, *, slug, sides, resolution=None):
    return {"kind": "contradiction",
            "payload": {"contradiction_key": key, "statement": statement, "sides": sides,
                        "resolution": resolution, "resolution_status": None, "topics": []},
            "provenance": _prov(slug, "reported")}


def _view_file(tmp_path: Path, slug: str, *, kind="claim", dedup_by="claim_key",
               project="statement", match: str = "", scope: str | None = None):
    p = tmp_path / "views" / slug / "view.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {slug}\nslug: {slug}\nview_version: 1\n"
    if scope:
        front += f"scope: {scope}\n"
    front += "---\n"
    p.write_text(
        f"{front}# {slug}\n\n## Projects\nprose.\n\n```selector\nkind: {kind}\n{match}"
        f"dedup_by: {dedup_by}\norder_by: {dedup_by}\nproject: {project}\n```\n",
        encoding="utf-8")
    return p


def _meta_view(tmp_path: Path, slug: str, feeds: str):
    p = tmp_path / "views" / slug / "view.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {slug}\nscope: meta\nview_version: 1\n---\n# {slug}\n\n{feeds}",
                 encoding="utf-8")
    return p


ENTITY_ARGS = dict(kind="entity", dedup_by="entity_key", order_by="entity_key",
                   project=["gloss", "role"])


# --- feed declaration -------------------------------------------------------

def test_parse_feeds_reads_every_block():
    feeds = meta.parse_feeds(
        "```feed\nname: spine\njoin: sources\nrender: coverage\n```\n\n"
        "```feed\nname: glossary\njoin: units\nkind: term\ndedup_by: term_key\n"
        "order_by: term_key\nproject: gloss, term_name\n```\n", "brief")
    assert [f["name"] for f in feeds] == ["spine", "glossary"]
    assert feeds[0]["render"] == "coverage"
    assert feeds[1]["project"] == ["gloss", "term_name"]


def test_a_feed_without_a_join_is_refused():
    with pytest.raises(UnsafeJoin, match="join"):
        meta.parse_feeds("```feed\nname: x\n```\n", "brief")


def test_an_unknown_join_mode_is_refused():
    with pytest.raises(UnsafeJoin, match="expected one of"):
        meta.parse_feeds("```feed\njoin: everything\n```\n", "brief")


def test_a_unit_feed_missing_a_shaping_key_is_refused():
    """No defaults, for the same reason the selector has none: a default would join on whatever
    field happened to exist and render the result as though it had been asked for."""
    with pytest.raises(UnsafeJoin, match="order_by"):
        meta.parse_feeds("```feed\njoin: units\nkind: term\ndedup_by: term_key\n"
                         "project: gloss\n```\n", "brief")


def test_an_unclosed_feed_block_is_refused():
    with pytest.raises(UnsafeJoin, match="unclosed"):
        meta.parse_feeds("```feed\njoin: sources\n", "brief")


def test_an_unknown_renderer_is_refused():
    with pytest.raises(UnsafeJoin, match="no general-purpose one"):
        meta.parse_feeds("```feed\njoin: sources\nrender: sankey\n```\n", "brief")


# --- run_feeds --------------------------------------------------------------

def test_run_feeds_refuses_a_source_view(tmp_path: Path):
    _view_file(tmp_path, "risks")
    with pytest.raises(UnsafeJoin, match="not `scope: meta`"):
        meta.run_feeds(tmp_path, "risks")


def test_run_feeds_refuses_a_meta_view_with_no_feed_block(tmp_path: Path):
    """A meta document assembled from CLI flags has its definition in somebody's shell history."""
    _meta_view(tmp_path, "brief", "no feed blocks here")
    with pytest.raises(UnsafeJoin, match="declares no ```feed block"):
        meta.run_feeds(tmp_path, "brief")


def test_run_feeds_executes_every_declared_feed(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a", topics=["t"]),
                                _entity("acme", "supplies", slug="a")])
    _view_file(tmp_path, "risks")
    _meta_view(tmp_path, "brief",
               "```feed\nname: spine\njoin: sources\nrender: coverage\n```\n\n"
               "```feed\nname: tags\njoin: topics\n```\n\n"
               "```feed\nname: each\njoin: per-view\n```\n")
    out = meta.run_feeds(tmp_path, "brief")
    assert set(out["feeds"]) == {"spine", "tags", "each"}
    assert "rendering" in out["feeds"]["spine"]
    assert out["view_version"] == "1"


# --- select_across ----------------------------------------------------------

def test_two_sources_defining_a_term_differently_merge_and_flag_divergent(tmp_path: Path):
    """The glossary's whole reason for existing. `select_units` keeps one unit per key, so
    without the additive `variants` pass two incompatible definitions of one word would silently
    become one, decided by filename order."""
    _units_file(tmp_path, "a", [_entity("cutover", "a weekend window", slug="a")])
    _units_file(tmp_path, "b", [_entity("cutover", "a three-month phase", slug="b")])
    out = meta.select_across(tmp_path, **ENTITY_ARGS)
    (e,) = out["entries"]
    assert e["support"] == 2
    assert e["divergent"] is True
    assert {v["fields"]["gloss"] for v in e["variants"]} == {
        "a weekend window", "a three-month phase"}
    assert e["sources"] == ["a", "b"]


def test_a_merged_claim_keeps_every_source_wording(tmp_path: Path):
    """The main compile path, not just the meta layer. Two sources judged to assert one claim are
    merged on the key, and `select_units` keeps ONE representative — so without `variants` the
    entry shows whichever wording sorted first by filename while still counting the other
    source's citation. The count stays right and the words silently do not."""
    _units_file(tmp_path, "a_minutes", [_claim("CLAIM-x-001", "The date is fixed.", slug="a_minutes")])
    _units_file(tmp_path, "z_review",
                [_claim("CLAIM-x-001", "The date has been confirmed as fixed.", slug="z_review")])

    sel = {"kind": "claim", "match": {}, "dedup_by": "claim_key", "order_by": "claim_key",
           "project": ["statement"], "section": "s", "load_when": None, "description": None}
    (e,) = compile_mod.select_units(sorted((tmp_path / "_bramber" / "units").glob("*.json")), sel)

    assert e["support"] == 2
    assert e["divergent"] is True, "the two sources word it differently"
    assert {v["fields"]["statement"] for v in e["variants"]} == {
        "The date is fixed.", "The date has been confirmed as fixed."}, \
        "both wordings survive; only one can be the rendered representative"


def test_a_merged_claim_worded_identically_is_not_divergent(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("CLAIM-x-001", "The date is fixed.", slug="a")])
    _units_file(tmp_path, "b", [_claim("CLAIM-x-001", "The date is fixed.", slug="b")])
    sel = {"kind": "claim", "match": {}, "dedup_by": "claim_key", "order_by": "claim_key",
           "project": ["statement"], "section": "s", "load_when": None, "description": None}
    (e,) = compile_mod.select_units(sorted((tmp_path / "_bramber" / "units").glob("*.json")), sel)
    assert e["support"] == 2 and e["divergent"] is False


def test_identical_phrasing_is_not_divergent(tmp_path: Path):
    _units_file(tmp_path, "a", [_entity("cutover", "a weekend window", slug="a")])
    _units_file(tmp_path, "b", [_entity("cutover", "a weekend window", slug="b")])
    out = meta.select_across(tmp_path, **ENTITY_ARGS)
    assert out["entries"][0]["divergent"] is False
    assert out["divergent"] == 0


def test_one_source_cited_twice_yields_support_one(tmp_path: Path):
    """Falls out of `select_units` deduping merged provenance on `extract_path`. Asserting it is
    what makes reusing that function safe rather than merely convenient."""
    _units_file(tmp_path, "a", [_entity("acme", "supplies", slug="a"),
                                _entity("acme", "supplies", slug="a")])
    out = meta.select_across(tmp_path, **ENTITY_ARGS)
    assert out["entries"][0]["support"] == 1


def test_support_and_floor_aggregate_in_opposite_directions(tmp_path: Path):
    """Well-attested and weakly-floored at the same time. Reporting one number hides half of it."""
    _units_file(tmp_path, "a", [_entity("acme", "supplies", slug="a", tier="authoritative")])
    _units_file(tmp_path, "b", [_entity("acme", "supplies", slug="b", tier="derived")])
    (e,) = meta.select_across(tmp_path, **ENTITY_ARGS)["entries"]
    assert e["support"] == 2
    assert e["reliability_floor"] == "derived"


def test_divergence_is_deterministic(tmp_path: Path):
    _units_file(tmp_path, "a", [_entity("acme", "one", slug="a")])
    _units_file(tmp_path, "b", [_entity("acme", "two", slug="b")])
    runs = [json.dumps(meta.select_across(tmp_path, **ENTITY_ARGS), sort_keys=True)
            for _ in range(3)]
    assert len(set(runs)) == 1


# --- the verifier -----------------------------------------------------------

def test_verify_join_catches_an_invented_attribution():
    """P1: a citation to a source with nothing to show."""
    entries = [{"dedup_key": "acme", "unit": {"payload": {"gloss": "supplies"}},
                "source_artifacts": [{"extract_path": "_bramber/extracts/ghost.md"}],
                "variants": [{"extract_path": "_bramber/extracts/a.md",
                              "fields": {"gloss": "supplies"}}]}]
    with pytest.raises(UnsafeJoin, match="invented an attribution"):
        meta.verify_join(entries)


def test_verify_join_catches_a_representative_no_source_gave():
    """P2: the compiled text matches none of the contributors' own values."""
    entries = [{"dedup_key": "acme", "unit": {"payload": {"gloss": "something else entirely"}},
                "source_artifacts": [{"extract_path": "_bramber/extracts/a.md"}],
                "variants": [{"extract_path": "_bramber/extracts/a.md",
                              "fields": {"gloss": "supplies"}}]}]
    with pytest.raises(UnsafeJoin, match="matches none of its"):
        meta.verify_join(entries)


def test_verify_join_no_longer_has_a_namespace_property():
    """P3 asserted that no entry merged across views unless every key was observed. It defended
    the per-view key namespace, which the view-agnostic scan removed. Pinning its absence keeps
    the retirement a decision rather than a regression somebody re-adds by reflex."""
    entries = [{"dedup_key": "CLAIM-007",
                "unit": {"kind": "claim", "payload": {"statement": "x"}},
                "source_artifacts": [{"extract_path": "_bramber/extracts/a.md"},
                                     {"extract_path": "_bramber/extracts/b.md"}],
                "variants": [{"extract_path": "_bramber/extracts/a.md",
                              "fields": {"statement": "x"}},
                             {"extract_path": "_bramber/extracts/b.md",
                              "fields": {"statement": "x"}}]}]
    meta.verify_join(entries)          # an agent-assigned key merging two sources is now normal


# --- the source spine -------------------------------------------------------

def test_the_spine_is_derived_from_the_selectors_not_a_stamp(tmp_path: Path):
    """Units carry no view. What a view made of a source is what its selector selects today."""
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a", topics=["risk"])])
    _units_file(tmp_path, "b", [_claim("CLAIM-002", "y", slug="b", topics=["other"])])
    _view_file(tmp_path, "risks", match="match.topics: risk\n")
    spine = meta.source_spine(tmp_path)
    by_source = {s["source"]: s for s in spine["sources"]}
    assert by_source["a"]["views"]["risks"]["units"] == 1
    assert "risks" not in by_source["b"]["views"], "the selector rejects b's only claim"


def test_a_source_with_no_units_still_appears(tmp_path: Path):
    """A source nothing selected is a finding. Dropping it reports a cleaner corpus than exists."""
    _units_file(tmp_path, "empty", [])
    _view_file(tmp_path, "risks")
    spine = meta.source_spine(tmp_path)
    assert [s["source"] for s in spine["sources"]] == ["empty"]
    assert spine["sources"][0]["views"] == {}


def test_the_spine_carries_views_that_selected_nothing_anywhere(tmp_path: Path):
    """Deriving the column set from the cells drops exactly the view whose emptiness is the most
    interesting cell on the page."""
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a", topics=["risk"])])
    _view_file(tmp_path, "risks", match="match.topics: risk\n")
    _view_file(tmp_path, "nothing", match="match.topics: absent-topic\n")
    spine = meta.source_spine(tmp_path)
    assert spine["views"] == ["nothing", "risks"]
    table = meta.coverage_table(spine)
    assert "nothing" in table
    assert "—" in table


def test_the_spine_can_scope_to_a_subset_of_views(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a")])
    _view_file(tmp_path, "risks")
    _view_file(tmp_path, "other")
    assert meta.source_spine(tmp_path, views=["risks"])["views"] == ["risks"]


def test_the_spine_skips_meta_views(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a")])
    _view_file(tmp_path, "risks")
    _meta_view(tmp_path, "brief", "```feed\njoin: sources\n```\n")
    assert meta.source_spine(tmp_path)["views"] == ["risks"]


# --- the topic register -----------------------------------------------------

def test_topics_aggregate_a_field_nothing_else_reads(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a", topics=["schedule", "vendor"])])
    out = meta.topic_register(tmp_path)
    assert [t["topic"] for t in out["topics"]] == ["schedule", "vendor"]
    assert out["topic_count"] == 2


def test_topics_merge_across_sources_and_kinds(tmp_path: Path):
    """The opposite of the per-view `questions` register it replaces: those were view-authored
    vocabulary and could not be merged; `topics` are free tags on one shared store."""
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a", topics=["schedule"])])
    _units_file(tmp_path, "b", [_entity("acme", "supplies", slug="b", topics=["schedule"])])
    (t,) = meta.topic_register(tmp_path)["topics"]
    assert t["unit_count"] == 2
    assert t["support"] == 2
    assert t["kinds"] == ["claim", "entity"]


def test_topics_count_distinct_sources_and_floor_on_the_weakest(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("C1", "x", slug="a", topics=["s"], tier="authoritative")])
    _units_file(tmp_path, "b", [_claim("C2", "y", slug="b", topics=["s"], tier="derived")])
    (t,) = meta.topic_register(tmp_path)["topics"]
    assert (t["support"], t["reliability_floor"]) == (2, "derived")


def test_topics_are_empty_not_broken_when_nothing_is_tagged(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a")])
    assert meta.topic_register(tmp_path)["topics"] == []


# --- the contradiction register ---------------------------------------------

def test_a_reused_contradiction_key_merges_and_gains_support(tmp_path: Path):
    """It did not merge before: CONTRA-001 was counted upward per view, so two views' copies
    shared nothing but the shape. One corpus-wide feed makes reuse the same explicit decision it
    already is for a claim."""
    side_a = {"ref": "CLAIM-001", "unit_key": "CLAIM-001",
              "extract_path": "_bramber/extracts/a.md", "position": "fixed"}
    side_b = {"ref": "CLAIM-002", "unit_key": "CLAIM-002",
              "extract_path": "_bramber/extracts/b.md", "position": "under review"}
    _units_file(tmp_path, "a", [_contradiction("CONTRA-001", "they disagree",
                                               slug="a", sides=[side_a])])
    _units_file(tmp_path, "b", [_contradiction("CONTRA-001", "they disagree", slug="b",
                                               sides=[side_b], resolution="the minutes postdate")])
    out = meta.contradiction_register(tmp_path)
    (c,) = out["contradictions"]
    assert c["support"] == 2
    assert {s["unit_key"] for s in c["sides"]} == {"CLAIM-001", "CLAIM-002"}, \
        "both sides survive; the representative alone would show one"
    assert c["resolution"] == "the minutes postdate", \
        "the resolution is on the non-representative unit and must still survive"
    assert c["resolution_divergent"] is False, "one contributor recorded it; nobody disagreed"


def test_disagreeing_resolutions_are_flagged_not_decided_by_filename(tmp_path: Path):
    """The register's entire job is surfacing unreconciled tensions, so reporting one as
    `resolved` because a filename sorted first — and dropping the source that called it
    `disputed` — is the worst available failure. Both are carried; the scalars go None."""
    def _c(slug, resolution, status):
        u = _contradiction("CONTRA-001", "they disagree", slug=slug, sides=[])
        u["payload"]["resolution"] = resolution
        u["payload"]["resolution_status"] = status
        return u

    _units_file(tmp_path, "a_minutes", [_c("a_minutes", "settled at the board", "resolved")])
    _units_file(tmp_path, "z_review", [_c("z_review", "never actually agreed", "disputed")])
    (c,) = meta.contradiction_register(tmp_path)["contradictions"]

    assert c["resolution_divergent"] is True
    assert c["resolution"] is None and c["resolution_status"] is None, \
        "a disagreement must not be presented as the corpus's answer"
    assert {r["resolution_status"] for r in c["resolutions"]} == {"resolved", "disputed"}
    assert {r["source"] for r in c["resolutions"]} == {"a_minutes", "z_review"}


def test_an_omitted_status_is_absence_not_disagreement(tmp_path: Path):
    """Both sources give the identical resolution; one adds a status. Comparing the pair as a
    tuple read the missing `status` as a disagreeing value, so the register reported a conflict
    that did not exist and suppressed a reconciliation both sources had given."""
    def _c(slug, status):
        u = _contradiction("CONTRA-001", "they disagree", slug=slug, sides=[])
        u["payload"]["resolution"] = "the minutes postdate the meeting"
        u["payload"]["resolution_status"] = status
        return u

    _units_file(tmp_path, "a", [_c("a", None)])
    _units_file(tmp_path, "b", [_c("b", "resolved")])
    (c,) = meta.contradiction_register(tmp_path)["contradictions"]
    assert c["resolution_divergent"] is False
    assert c["resolution"] == "the minutes postdate the meeting"
    assert c["resolution_status"] == "resolved", "one source stated it; nobody contradicted it"


def test_every_framing_of_a_reused_tension_survives(tmp_path: Path):
    """`statement` was the last field read off the representative, and therefore the last decided
    by filename order. Two sources reusing a key assert one tension but phrase it differently,
    and the losing phrasing was absent from the output entirely."""
    _units_file(tmp_path, "a_minutes",
                [_contradiction("CONTRA-001", "the minutes and the transcript disagree on the date",
                                slug="a_minutes", sides=[])])
    _units_file(tmp_path, "z_review",
                [_contradiction("CONTRA-001", "the vendor and the board disagree on the date",
                                slug="z_review", sides=[])])
    (c,) = meta.contradiction_register(tmp_path)["contradictions"]
    assert c["statement_divergent"] is True
    assert len(c["statements"]) == 2
    assert {s["source"] for s in c["statements"]} == {"a_minutes", "z_review"}


def test_the_register_is_invariant_under_source_renaming(tmp_path: Path):
    """`unit_records` walks files in name order, so anything decided by 'first wins' is decided by
    filename. Renaming the sources must not change what the register reports."""
    def _c(slug, resolution, status):
        u = _contradiction("CONTRA-001", "they disagree", slug=slug, sides=[])
        u["payload"]["resolution"] = resolution
        u["payload"]["resolution_status"] = status
        return u

    def _report(first, second):
        for f in (tmp_path / "_bramber" / "units").glob("*.json"):
            f.unlink()
        _units_file(tmp_path, first, [_c(first, "settled at the board", "resolved")])
        _units_file(tmp_path, second, [_c(second, "never actually agreed", "disputed")])
        (c,) = meta.contradiction_register(tmp_path)["contradictions"]
        return c["resolution"], c["resolution_status"], c["resolution_divergent"]

    assert _report("a_minutes", "z_review") == _report("z_minutes", "a_review")


def test_two_distinct_contradictions_stay_distinct(tmp_path: Path):
    _units_file(tmp_path, "a", [_contradiction("CONTRA-001", "one", slug="a", sides=[]),
                                _contradiction("CONTRA-002", "two", slug="a", sides=[])])
    assert meta.contradiction_register(tmp_path)["count"] == 2


# --- per-view ---------------------------------------------------------------

def test_per_view_lays_selections_side_by_side(tmp_path: Path):
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a", topics=["risk"])])
    _view_file(tmp_path, "risks", match="match.topics: risk\n")
    _view_file(tmp_path, "nothing", match="match.topics: absent\n")
    out = meta.selections_by_view(tmp_path)
    assert out["support_by_view"] == {"nothing": 0, "risks": 1}


def test_per_view_emits_no_cross_view_total(tmp_path: Path):
    """One document read by six views would be counted six times. There is no total and there
    must not be one — for a corpus-wide count, select over the store instead."""
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a")])
    _view_file(tmp_path, "risks")
    out = meta.selections_by_view(tmp_path)
    assert "total" not in out
    assert "total" not in out["support_by_view"]


def test_per_view_skips_meta_views(tmp_path: Path):
    """Including, importantly, the calling document's own view — which would recurse."""
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a")])
    _view_file(tmp_path, "risks")
    _meta_view(tmp_path, "brief", "```feed\njoin: per-view\n```\n")
    assert meta.selections_by_view(tmp_path)["views"] == ["risks"]


# --- view scope -------------------------------------------------------------

def test_view_scope_defaults_to_source():
    assert compile_mod.view_scope({}) == "source"
    assert compile_mod.view_scope({"scope": "meta"}) == "meta"
    assert compile_mod.view_scope({"scope": "mtea"}) == "source", "a typo must not change behaviour"


def test_compiling_a_meta_view_is_refused(tmp_path: Path):
    """It has no selector, so compiling it writes an empty resource that looks like a real one."""
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a")])
    _meta_view(tmp_path, "brief", "```feed\njoin: sources\n```\n")
    with pytest.raises(SystemExit, match="scope: meta"):
        compile_mod.selection_for_view(tmp_path, "brief")


def test_views_on_disk_reads_the_filesystem_not_the_index(tmp_path: Path):
    _view_file(tmp_path, "risks")
    (tmp_path / "views" / "no-spec").mkdir(parents=True)
    assert meta.views_on_disk(tmp_path) == ["risks"]


# --- renderings -------------------------------------------------------------

def test_coverage_is_a_table_not_a_graph(tmp_path: Path):
    """Twenty sources against six views is up to 120 edges — drawable and unreadable."""
    _units_file(tmp_path, "a", [_claim("CLAIM-001", "x", slug="a")])
    _view_file(tmp_path, "risks")
    table = meta.coverage_table(meta.source_spine(tmp_path))
    assert table.startswith("| source |")
    assert "flowchart" not in table


def test_coverage_says_so_rather_than_drawing_nothing(tmp_path: Path):
    assert "_No sources indexed._" == meta.coverage_table({"sources": [], "views": []})


def test_divergence_draws_only_divergent_entries(tmp_path: Path):
    _units_file(tmp_path, "a", [_entity("acme", "one", slug="a"),
                                _entity("beta", "same", slug="a")])
    _units_file(tmp_path, "b", [_entity("acme", "two", slug="b"),
                                _entity("beta", "same", slug="b")])
    out = meta.select_across(tmp_path, **ENTITY_ARGS)
    mm = meta.mermaid_divergence(out)
    assert "acme" in mm
    assert "beta" not in mm, "sparse by construction"


def test_divergence_says_so_when_nothing_diverges(tmp_path: Path):
    _units_file(tmp_path, "a", [_entity("acme", "same", slug="a")])
    mm = meta.mermaid_divergence(meta.select_across(tmp_path, **ENTITY_ARGS))
    assert mm.startswith("%%")


def test_mermaid_ids_survive_punctuation(tmp_path: Path):
    _units_file(tmp_path, "a", [_entity("acme corp. (uk)", "one", slug="a")])
    _units_file(tmp_path, "b", [_entity("acme corp. (uk)", "two", slug="b")])
    mm = meta.mermaid_divergence(meta.select_across(tmp_path, **ENTITY_ARGS))
    for line in mm.splitlines():
        if "[" in line and "-->" not in line:
            assert " " not in line.split("[")[0].strip(), line


def test_contradiction_graph_names_the_likely_cause_when_empty(tmp_path: Path):
    out = meta.contradiction_graph({"contradictions": []})
    assert out.startswith("%%")
    assert "kinds_absent" in out


def test_contradiction_graph_draws_every_merged_side(tmp_path: Path):
    sides = [{"ref": "CLAIM-001", "unit_key": "CLAIM-001", "extract_path": "a", "position": "p1"},
             {"ref": "CLAIM-002", "unit_key": "CLAIM-002", "extract_path": "b", "position": "p2"}]
    _units_file(tmp_path, "a", [_contradiction("CONTRA-001", "x", slug="a", sides=sides[:1])])
    _units_file(tmp_path, "b", [_contradiction("CONTRA-001", "x", slug="b", sides=sides[1:])])
    mm = meta.contradiction_graph(meta.contradiction_register(tmp_path))
    assert "CLAIM-001" in mm and "CLAIM-002" in mm
