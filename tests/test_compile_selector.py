"""View-driven selection over the shared unit store (specs/09 §4; dedup model from specs/07).

`bramber/compile.py` is a domain-blind predicate engine: it reads a ```selector block from each
view.md and applies it over the units on disk. These tests hand-author units + extracts + a
view.md and drive the full compile pipeline, so they run on any checkout with no optional
dependency.

The behavioural centre of the file is **dedup as two operations** — collapse within a source,
count across sources. That distinction ("five sources each said it once" vs "one source said it
five times") was invisible at every layer of this system until specs/07, and it is the whole
point of the product, so it is asserted here loudly and in both directions.

Run:  cd bramber && python -m pytest tests/test_compile_selector.py
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from bramber.compile import (_select, compile_view, parse_selector, select_units,
                            selection_for_view)

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "bramber" / "engine"


def _load_db():
    spec = importlib.util.spec_from_file_location("bramber_db_selector", ENGINE / "db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- parse_selector ---------------------------------------------------------

MARKET_BODY = """\
## Projects
prose the agent reads...

```selector
kind: claim
match.evidence_strength: strong, moderate
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength, recency
section: Claims
load_when: you need the current market reading
```
"""


def test_parse_selector_normalizes():
    sel = parse_selector(MARKET_BODY, "market-overview")
    assert sel["kind"] == "claim"
    assert sel["match"] == {"evidence_strength": {"strong", "moderate"}}
    assert sel["dedup_by"] == "claim_key"
    assert sel["order_by"] == "claim_key"
    assert sel["project"] == ["statement", "evidence_strength", "recency"]  # ordered
    assert sel["section"] == "Claims"
    assert sel["load_when"] == "you need the current market reading"


def test_parse_selector_multi_value():
    sel = parse_selector(
        "```selector\nmatch.topics: composition, role\ndedup_by: k\norder_by: k\nproject: s\n```",
        "x")
    assert sel["match"] == {"topics": {"composition", "role"}}   # comma-list -> set


def test_parse_selector_requires_block():
    with pytest.raises(SystemExit):
        parse_selector("## Projects\njust prose, no fenced selector\n", "no-rule")


@pytest.mark.parametrize("omit", ["dedup_by", "order_by", "project"])
def test_parse_selector_requires_the_shaping_keys(omit: str):
    """These used to default to code-shaped field names (`engram_id`, `qualified_name`). A view
    over any other unit shape then silently projected blank bullets — a wrong document with a
    green build. Erroring is strictly better than rendering nothing (specs/07 §4)."""
    lines = {"dedup_by": "claim_key", "order_by": "claim_key", "project": "statement"}
    lines.pop(omit)
    body = "```selector\nkind: claim\n" + "\n".join(f"{k}: {v}" for k, v in lines.items()) + "\n```"
    with pytest.raises(SystemExit) as exc:
        parse_selector(body, "incomplete")
    assert omit in str(exc.value)


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


def _claim(key, statement, *, slug, evidence="strong", recency="2026-05-01",
           topics=("market",), tier="reported"):
    """One claim as one source asserts it. `slug` is the source it came from — which is what
    makes support counting testable: the same key from two slugs must merge, not collapse."""
    return {
        "kind": "claim",
        "payload": {
            "claim_key": key, "statement": statement,
            "evidence_strength": evidence, "recency": recency, "topics": list(topics),
        },
        "provenance": {"source_artifacts": [{
            "extract_path": f"_bramber/extracts/{slug}.md",
            "scan_path": f"_bramber/scans/{slug}.md",
            "reliability_tier": tier,
        }]},
    }


SELECTOR = ("kind: claim\ndedup_by: claim_key\n"
            "order_by: claim_key\nproject: statement, evidence_strength\nsection: Claims")


def _extract_file(tmp_path: Path, slug: str, key: str):
    p = tmp_path / "_bramber" / "extracts" / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        "identity_kind: content_sha\n"
        f"identity_key: {key}\n"
        'identity_json: {"ref": "x"}\n'
        "source_type: article\n"
        f'title: "{slug}"\n'
        "date_ingested: 2026-01-01\n"
        "---\n"
        f"# {slug}\n",
        encoding="utf-8",
    )


def _view_file(tmp_path: Path, slug: str, name: str, selector_lines: str):
    p = tmp_path / "views" / slug / "view.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\nname: {name}\nslug: {slug}\nview_version: 1\nmaintainer: human\n---\n"
        f"# {name}\n\n## Projects\nprose.\n\n```selector\n{selector_lines}\n```\n",
        encoding="utf-8",
    )


# --- the predicate engine ---------------------------------------------------

def test_select_applies_predicates_and_orders(tmp_path: Path):
    f1 = _units_file(tmp_path, "acme", [
        _claim("CLAIM-002", "Guidance was raised.", slug="acme"),
        _claim("CLAIM-001", "Revenue grew 22%.", slug="acme"),
        {"kind": "note", "payload": {"claim_key": "CLAIM-009", "statement": "Not a claim."},
         "provenance": {"source_artifacts": []}},
    ])
    sel = parse_selector(f"```selector\n{SELECTOR}\n```", "market-overview")
    picked = _select([f1], sel)

    assert [p["dedup_key"] for p in picked] == ["CLAIM-001", "CLAIM-002"]  # ordered by key
    assert all(p["support"] == 1 for p in picked)
    # `project` decides which payload fields survive — nothing is hardcoded:
    assert picked[0]["fields"] == {"statement": "Revenue grew 22%.", "evidence_strength": "strong"}


def test_generic_match_predicate_is_the_whole_selection_vocabulary(tmp_path: Path):
    """`match.<field>` is one mechanism over arbitrary payload fields. There is no other
    domain-flavoured predicate left — a view narrows the shared store with it or takes
    everything of its `kind`."""
    f = _units_file(tmp_path, "acme", [
        _claim("CLAIM-001", "Strong one.", slug="acme", evidence="strong"),
        _claim("CLAIM-002", "Weak one.", slug="acme", evidence="speculative"),
    ])
    sel = parse_selector(
        "```selector\nkind: claim\nmatch.evidence_strength: strong, moderate\n"
        "dedup_by: claim_key\norder_by: claim_key\nproject: statement\n```", "graded")
    assert [p["dedup_key"] for p in _select([f], sel)] == ["CLAIM-001"]


def test_match_on_a_list_valued_field_is_any_of(tmp_path: Path):
    """The gap that blocked topic selection: the old scalar-only rule stringified a list
    wholesale, so `match.topics: revenue` could never match `topics: ['revenue', 'growth']` —
    it failed even at cardinality one, since `str(['revenue']) != 'revenue'`. Any-of semantics
    are what let a view select over the shared store by tag."""
    f = _units_file(tmp_path, "acme", [
        _claim("CLAIM-001", "On revenue and growth.", slug="acme", topics=["revenue", "growth"]),
        _claim("CLAIM-002", "On revenue alone.", slug="acme", topics=["revenue"]),
        _claim("CLAIM-003", "On hiring.", slug="acme", topics=["hiring"]),
        _claim("CLAIM-004", "No topics at all.", slug="acme", topics=[]),
    ])
    sel = parse_selector(
        "```selector\nkind: claim\nmatch.topics: revenue\n"
        "dedup_by: claim_key\norder_by: claim_key\nproject: statement\n```", "revenue-view")
    assert [p["dedup_key"] for p in _select([f], sel)] == ["CLAIM-001", "CLAIM-002"], \
        "a multi-valued unit matches if ANY of its values is allowed; an empty list matches nothing"


def test_match_scalar_semantics_stay_exact(tmp_path: Path):
    """The list rule must not loosen scalars: no substring, no membership widening."""
    f = _units_file(tmp_path, "acme", [
        _claim("CLAIM-001", "Strong.", slug="acme", evidence="strong"),
        _claim("CLAIM-002", "Strongish.", slug="acme", evidence="strongish"),
    ])
    sel = parse_selector(
        "```selector\nkind: claim\nmatch.evidence_strength: strong\n"
        "dedup_by: claim_key\norder_by: claim_key\nproject: statement\n```", "exact")
    assert [p["dedup_key"] for p in _select([f], sel)] == ["CLAIM-001"]


# --- the central behavioural claim: dedup is TWO operations -----------------

def test_one_source_repeating_a_claim_yields_support_one(tmp_path: Path):
    """The length-bias fix. An insistent source restating a position five times contributes one
    unit with support 1 — not five units, and not support 5. Collapse happens within the source
    (upstream, at materialization); this asserts selection does not undo it or double-count it."""
    f = _units_file(tmp_path, "loud", [
        _claim("CLAIM-001", "The deadline will slip.", slug="loud"),
        _claim("CLAIM-001", "The deadline will slip.", slug="loud"),
        _claim("CLAIM-001", "The deadline will slip.", slug="loud"),
    ])
    sel = parse_selector(f"```selector\n{SELECTOR}\n```", "market-overview")
    picked = _select([f], sel)

    assert len(picked) == 1, "one claim, however many times one source repeats it"
    assert picked[0]["support"] == 1, "repetition inside a source is volume, not corroboration"


def test_five_sources_each_stating_it_once_yields_support_five(tmp_path: Path):
    """The corroboration signal the engine used to delete. First-wins dedup linked a unit to
    exactly ONE source by construction, even when it legitimately appeared in five — so the
    system could not distinguish this case from the one above. That distinction is the product."""
    files = [
        _units_file(tmp_path, f"src{i}", [_claim("CLAIM-001", "The deadline will slip.",
                                                 slug=f"src{i}")])
        for i in range(5)
    ]
    sel = parse_selector(f"```selector\n{SELECTOR}\n```", "market-overview")
    picked = _select(files, sel)

    assert len(picked) == 1, "one claim — five sources agreeing is not five claims"
    assert picked[0]["support"] == 5, "every corroborating source must be counted"
    assert len({a["extract_path"] for a in picked[0]["source_artifacts"]}) == 5, \
        "and every one of them must be individually citable"


def test_support_and_floor_aggregate_in_opposite_directions(tmp_path: Path):
    """A claim backed by several sources of which one is weak is well-attested AND weakly-floored
    at the same time (specs/08 §4.2). Reporting only one of those numbers hides half the picture,
    so both are computed — support counts up, floor takes the weakest link."""
    files = [
        _units_file(tmp_path, "strong1", [
            _claim("CLAIM-001", "X happened.", slug="strong1", tier="authoritative")]),
        _units_file(tmp_path, "strong2", [
            _claim("CLAIM-001", "X happened.", slug="strong2", tier="authoritative")]),
        _units_file(tmp_path, "weak1", [
            _claim("CLAIM-001", "X happened.", slug="weak1", tier="derived")]),
    ]
    sel = parse_selector(f"```selector\n{SELECTOR}\n```", "market-overview")
    picked = _select(files, sel)[0]

    assert picked["support"] == 3
    assert picked["reliability_floor"] == "derived", \
        "one weak source caps the claim however many authoritative ones sit beside it"


def test_contradicting_claims_never_merge(tmp_path: Path):
    """Dedup may collapse restatement; it must never collapse disagreement (specs/07 §3.2).
    Distinct keys stay distinct no matter how similar the text — which is precisely why identity
    is an agent-minted key and not an embedding distance, since negation is invisible to
    similarity and a false merge fabricates attribution."""
    files = [
        _units_file(tmp_path, "a", [_claim("CLAIM-001", "The deadline is confirmed.", slug="a")]),
        _units_file(tmp_path, "b", [_claim("CLAIM-002", "The deadline is not confirmed.", slug="b")]),
    ]
    sel = parse_selector(f"```selector\n{SELECTOR}\n```", "market-overview")
    picked = _select(files, sel)

    assert [p["dedup_key"] for p in picked] == ["CLAIM-001", "CLAIM-002"]
    assert all(p["support"] == 1 for p in picked), "a contest is not corroboration"


# --- full compile pipeline --------------------------------------------------

def test_compile_view_drives_full_pipeline(tmp_path: Path):
    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")

    _extract_file(tmp_path, "acme", "k_acme")
    _extract_file(tmp_path, "widget", "k_widget")
    _units_file(tmp_path, "acme", [
        _claim("CLAIM-001", "Revenue grew 22%.", slug="acme"),
        _claim("CLAIM-002", "Guidance was raised.", slug="acme"),
    ])
    _units_file(tmp_path, "widget", [
        _claim("CLAIM-001", "Revenue grew 22%.", slug="widget"),   # corroborates acme
        _claim("CLAIM-003", "Three vendors hold 70%.", slug="widget"),
    ])
    _view_file(tmp_path, "market-overview", "Market Overview", SELECTOR)
    db.sync_from_disk()

    res = compile_view(tmp_path, "market-overview")
    assert res["created"] and res["version_num"] == 1

    body = (tmp_path / "views/market-overview/resources/overview/RESOURCE.md").read_text(
        encoding="utf-8")
    assert "## Claims" in body
    assert body.count("\n- **") == 3, "3 distinct claims from 4 assertions"
    assert "source_count: 2" in body, "2 contributing sources, not 4 units"
    assert "reliability_floor: reported" in body
    assert "(2 sources" in body, "the corroborated claim must show its support on the page"

    # Lineage: one row per (unit x contributing source) — 4, not 3. A unit asserted by two
    # sources writes two rows, which is the corroboration record.
    conn = sqlite3.connect(str(tmp_path / "bramber.db"))
    try:
        rows = conn.execute(
            """SELECT vs.contribution, s.extract_path FROM version_sources vs
               JOIN sources s ON s.id = vs.source_id
               JOIN resource_versions rv ON rv.id = vs.version_id
               JOIN resources r ON r.id = rv.resource_id
               JOIN views v ON v.id = r.view_id
               WHERE v.slug = 'market-overview'""").fetchall()
    finally:
        conn.close()
    assert None not in [r[0] for r in rows], "contribution follows the view's dedup_by"
    assert {r[0] for r in rows} == {"CLAIM-001", "CLAIM-002", "CLAIM-003"}

    # Idempotent: recompiling unchanged inputs mints no new version.
    assert compile_view(tmp_path, "market-overview")["created"] is False


def test_compile_view_unknown_view_errors(tmp_path: Path):
    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    (tmp_path / "_bramber" / "units").mkdir(parents=True)
    db.sync_from_disk()
    with pytest.raises(SystemExit):
        compile_view(tmp_path, "does-not-exist")


def test_selection_for_view_matches_compile_and_carries_full_units(tmp_path: Path):
    """`selection_for_view` (the agent's Mode-2 feed / `bramber select`) returns the SAME set the
    baseline compiles, with full units — so the agent never re-derives selection by hand."""
    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    _units_file(tmp_path, "acme", [
        _claim("CLAIM-001", "Revenue grew 22%.", slug="acme", topics=["market"]),
        _claim("CLAIM-009", "Off-topic.", slug="acme", topics=["weather"]),
    ])
    _view_file(tmp_path, "market-overview", "Market Overview",
               "kind: claim\nmatch.topics: market\ndedup_by: claim_key\n"
               "order_by: claim_key\nproject: statement, evidence_strength\nsection: Claims")

    feed = selection_for_view(tmp_path, "market-overview")
    assert feed["view_slug"] == "market-overview"
    assert feed["section"] == "Claims"
    assert feed["count"] == 1
    unit = feed["units"][0]["unit"]
    assert unit["payload"]["claim_key"] == "CLAIM-001"
    assert unit["payload"]["evidence_strength"] == "strong", \
        "the agent sees the full graded payload, not the trimmed bullet"
    json.dumps(feed)                      # the feed is what `bramber select` prints
