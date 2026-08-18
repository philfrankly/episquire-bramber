"""Text units: scans -> Claims -> Units (specs/09; the dedup model from specs/07 §3.3).

A scan reads one source once, view-agnostically, for anything claim-shaped; every view selects
over the shared store it feeds. These tests cover the parse, the within-source collapse, the
corpus-global mint-or-reuse feed, and the full inbox -> ingest -> scan -> materialize -> compile
round trip.

Run:  cd bramber && python -m pytest tests/test_scan.py
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from bramber import scan as scan_mod
from bramber.compile import compile_view
from bramber.ingest import ingest, make_adapter, materialize

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "bramber" / "engine"


def _load_db(tmp_path: Path, tag: str):
    spec = importlib.util.spec_from_file_location(f"bramber_db_scan_{tag}", ENGINE / "db.py")
    db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db)
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    return db


SCAN = """\
---
source: _bramber/extracts/acme.md
scan_date: 2026-05-02
discarded: false
---

## Claims

- **CLAIM-001** — Revenue grew 22% year over year, driven by the agents product line.
  - evidence: strong
  - recency: 2026-05-01
  - topics: revenue-trajectory, product-mix
- **CLAIM-002** — Management guided to accelerating enterprise adoption into Q4.
  - evidence: moderate
  - recency: 2026-05-01
  - topics: revenue-trajectory

## Contradictions
None identified.

## Notes
- A pricing page changed.
"""


def test_parse_reads_frontmatter_and_graded_claims():
    s = scan_mod.parse_text(SCAN, path="_bramber/scans/acme.md")
    assert s.source == "_bramber/extracts/acme.md"
    assert s.discarded is False
    assert [c.key for c in s.claims] == ["CLAIM-001", "CLAIM-002"]

    first = s.claims[0]
    assert first.statement.startswith("Revenue grew 22%")
    assert first.evidence_strength == "strong"
    assert first.recency == "2026-05-01"
    assert first.topics == ["revenue-trajectory", "product-mix"]


def test_parse_stops_at_the_next_section():
    """Only `## Claims` produces units. The other sections stay prose deliberately — they are
    framing for a human and for the authoring step, not countable atoms, and materializing them
    would be a second design decision wearing this one's clothes."""
    s = scan_mod.parse_text(SCAN)
    assert len(s.claims) == 2, "the Notes bullet must not be read as a claim"


def test_within_source_collapse_is_the_length_bias_fix():
    """A source restating one position five times contributes ONE unit. This is the whole reason
    the product exists: an insistent stakeholder must not buy influence with volume."""
    text = SCAN.replace(
        "## Contradictions",
        "- **CLAIM-001** — Revenue grew, as I said.\n"
        "  - evidence: strong\n"
        "- **CLAIM-001** — Revenue grew, again.\n"
        "  - evidence: strong\n\n## Contradictions")
    s = scan_mod.parse_text(text, path="_bramber/scans/acme.md")
    assert len(s.claims) == 4, "the parser reads every bullet…"

    units = scan_mod.units_for_source([s])
    ref = scan_mod.srcref_for("_bramber/scans/acme.md")
    keys = [u.payload["claim_key"] for u in units]
    assert keys == [f"CLAIM-{ref}-001", f"CLAIM-{ref}-002"], \
        "…and materialization collapses the repeats, in this source's key namespace"
    assert len(units[0].provenance["source_artifacts"]) == 1


def test_units_carry_a_provenance_list_and_a_tier():
    s = scan_mod.parse_text(SCAN, path="_bramber/scans/acme.md")
    unit = scan_mod.units_for_source([s])[0]
    arts = unit.provenance["source_artifacts"]
    assert isinstance(arts, list) and len(arts) == 1, \
        "a list even at length one — the shape is what makes corroboration expressible later"
    assert arts[0]["extract_path"] == "_bramber/extracts/acme.md"
    assert arts[0]["scan_path"] == "_bramber/scans/acme.md"
    assert arts[0]["reliability_tier"] == "reported", \
        "assigned by source class from a fixed table, never derived from how the text sounds"
    assert unit.kind == "claim"


def test_discarded_scans_contribute_nothing():
    s = scan_mod.parse_text(SCAN.replace("discarded: false", "discarded: true"))
    assert scan_mod.units_for_source([s]) == []


# --- the mint-or-reuse feed (corpus-global) ---------------------------------

def _write_scan(root: Path, name: str, text: str):
    p = root / "_bramber" / "scans" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_known_claims_feeds_the_agent_the_keys_already_minted(tmp_path: Path):
    """Source N is shown what sources 1..N-1 minted, so it can REUSE a key. That is what makes
    corroboration an explicit, auditable decision — "source 2 asserts acme's 001" — rather than a
    similarity threshold being crossed somewhere invisible.

    **Reuse is now written as the qualified key the feed publishes.** A bare key names the
    minting source's own namespace, so source 2 copies acme's key verbatim to corroborate it. The
    key it copies carries acme's namespace, which is what makes the corroboration readable from
    the key alone rather than only from the provenance list."""
    acme_ref = scan_mod.srcref_for("_bramber/extracts/acme.md")
    tok = scan_mod.statement_token(
        "Revenue grew 22% year over year, driven by the agents product line.")
    _write_scan(tmp_path, "acme.md", SCAN)
    _write_scan(tmp_path, "widget.md",
                SCAN.replace("_bramber/extracts/acme.md", "_bramber/extracts/widget.md")
                    .replace("- **CLAIM-001**", f"- **CLAIM-{acme_ref}-001={tok}**")
                    .replace("- **CLAIM-002** — Management guided to accelerating "
                             "enterprise adoption into Q4.", "- **CLAIM-003** — Three "
                             "vendors hold 70% share."))

    widget_ref = scan_mod.srcref_for("_bramber/extracts/widget.md")
    known = scan_mod.known_claims(tmp_path)
    by_key = {k["claim_key"]: k for k in known}
    assert set(by_key) == {f"CLAIM-{acme_ref}-001", f"CLAIM-{acme_ref}-002",
                           f"CLAIM-{widget_ref}-003"}
    assert by_key[f"CLAIM-{acme_ref}-001"]["sources"] == [
        "_bramber/extracts/acme.md", "_bramber/extracts/widget.md"], \
        "a reused key records both sources — that IS the corroboration record"


# --- the full pipeline ------------------------------------------------------

INBOX = (
    "---\n"
    "source_url: https://example.com/{slug}\n"
    "source_type: article\n"
    'title: "{slug}"\n'
    "author: A. Writer\n"
    "date_published: 2026-05-01\n"
    "---\n"
    "# {slug}\n\nBody of {slug}.\n"
)

VIEW_MD = (
    "---\nname: Market Overview\nslug: market-overview\nview_version: 1\nmaintainer: human\n---\n"
    "# Market Overview\n\n## Thesis\nThe best current reading.\n\n## Projects\nClaims.\n\n"
    "```selector\n"
    "kind: claim\ndedup_by: claim_key\norder_by: claim_key\n"
    "project: statement, evidence_strength\nsection: Claims\n"
    "```\n"
)


def _setup_project(tmp_path: Path):
    inbox = tmp_path / "_bramber" / "inbox"
    inbox.mkdir(parents=True)
    for slug in ("acme", "widget"):
        (inbox / f"{slug}.md").write_text(INBOX.format(slug=slug), encoding="utf-8")
    vd = tmp_path / "views" / "market-overview"
    vd.mkdir(parents=True)
    (vd / "view.md").write_text(VIEW_MD, encoding="utf-8")


def _scan_all(tmp_path: Path, manifest):
    """The agent's step, stood in for deterministically. Both sources assert the same two claims.

    The first source mints; every later one **reuses the first's qualified keys**, which is how
    corroboration is expressed now that a bare key names its minter's own namespace. Writing bare
    keys in both would mint four independent claims — the migration hazard `materialize` warns
    about, and the reason this fixture no longer writes the same text twice.
    """
    ms = sorted(manifest, key=lambda m: m["slug"])
    first, rest = ms[0], ms[1:]
    _write_scan(tmp_path, f"{first['slug']}.md",
                SCAN.replace("_bramber/extracts/acme.md", first["extract_path"]))
    ref = scan_mod.srcref_for(first["extract_path"])
    # A reuse is a WITNESSED endorsement: the key plus six hex quoting the minter's statement,
    # copied as one token from the feed's `reuse_as`. A bare qualified key no longer merges —
    # one slip would land it on a neighbouring real key and corroborate the wrong claim.
    toks = {c.key: scan_mod.statement_token(c.statement)
            for c in scan_mod.parse_text(SCAN, path="x").claims}
    for m in rest:
        _write_scan(tmp_path, f"{m['slug']}.md",
                    SCAN.replace("_bramber/extracts/acme.md", m["extract_path"])
                        .replace("- **CLAIM-001**",
                                 f"- **CLAIM-{ref}-001={toks['CLAIM-001']}**")
                        .replace("- **CLAIM-002**",
                                 f"- **CLAIM-{ref}-002={toks['CLAIM-002']}**"))


def test_full_pipeline_ingest_scan_materialize_compile(tmp_path: Path):
    """The end-to-end: text sources become countable units ONCE, and a deterministic compile
    produces a cited document. Both sources assert CLAIM-001, so the corroboration has to
    survive every hop to the RESOURCE.md."""
    db = _load_db(tmp_path, "e2e")
    _setup_project(tmp_path)

    manifest = ingest(make_adapter("text"), tmp_path)
    assert len(manifest) == 2

    # Before scanning, the envelopes declare emptiness rather than faking it.
    for m in manifest:
        env = json.loads((tmp_path / "_bramber" / "units" / f"{m['slug']}.json").read_text("utf-8"))
        assert env["units"] is None

    _scan_all(tmp_path, manifest)

    res = materialize(tmp_path)
    assert res["sources"] == 2 and res["units"] == 4, "2 claims x 2 sources, before merging"

    db.sync_from_disk()
    compiled = compile_view(tmp_path, "market-overview")
    assert compiled["created"]

    body = (tmp_path / "views/market-overview/resources/overview/RESOURCE.md").read_text("utf-8")
    assert body.count("\n- **") == 2, "4 assertions merge to 2 distinct claims"
    assert "(2 sources" in body, "and each carries the count of sources backing it"
    assert "source_count: 2" in body


def test_a_second_view_costs_no_second_scan(tmp_path: Path):
    """The redesign's product claim, asserted: adding a view touches no source and no scan —
    it is a selector over the store the first view already paid for. This is what the
    per-(source × view) digest could not do, and why it was withdrawn."""
    db = _load_db(tmp_path, "twoview")
    _setup_project(tmp_path)
    manifest = ingest(make_adapter("text"), tmp_path)
    _scan_all(tmp_path, manifest)
    materialize(tmp_path)
    db.sync_from_disk()
    compile_view(tmp_path, "market-overview")

    scans_before = {p.name: p.read_text("utf-8")
                    for p in (tmp_path / "_bramber" / "scans").glob("*.md")}

    # A NEW view, added after the corpus was scanned: strong evidence only.
    vd = tmp_path / "views" / "strong-only"
    vd.mkdir(parents=True)
    (vd / "view.md").write_text(
        "---\nname: Strong Only\nslug: strong-only\nview_version: 1\nmaintainer: human\n---\n"
        "# Strong Only\n\n## Thesis\nOnly what is well evidenced.\n\n"
        "```selector\nkind: claim\nmatch.evidence_strength: strong\n"
        "dedup_by: claim_key\norder_by: claim_key\nproject: statement\nsection: Claims\n```\n",
        encoding="utf-8")
    db.sync_from_disk()
    compiled = compile_view(tmp_path, "strong-only")
    assert compiled["created"]

    body = (tmp_path / "views/strong-only/resources/overview/RESOURCE.md").read_text("utf-8")
    assert body.count("\n- **") == 1, "the new view selects the one strong claim"
    assert "(2 sources" in body, "cross-source support is visible to the new view too"

    scans_after = {p.name: p.read_text("utf-8")
                   for p in (tmp_path / "_bramber" / "scans").glob("*.md")}
    assert scans_after == scans_before, "adding a view must not touch a scan"


def test_claims_and_support_survive_a_db_delete_and_rebuild(tmp_path: Path):
    """Invariant 3 under the new schema: disk is the source of truth. Every lineage edge — one
    row per (unit x contributing source) — must reconstruct from the version snapshots alone,
    or the corroboration record is only as durable as a file we call disposable."""
    db = _load_db(tmp_path, "rebuild")
    _setup_project(tmp_path)
    manifest = ingest(make_adapter("text"), tmp_path)
    _scan_all(tmp_path, manifest)
    materialize(tmp_path)
    db.sync_from_disk()
    compile_view(tmp_path, "market-overview")

    def _lineage():
        conn = sqlite3.connect(str(tmp_path / "bramber.db"))
        try:
            return sorted(conn.execute(
                "SELECT source_id, contribution FROM version_sources").fetchall())
        finally:
            conn.close()

    ref = scan_mod.srcref_for(sorted(m["extract_path"] for m in manifest)[0])
    before = _lineage()
    assert len(before) == 4, "2 claims x 2 corroborating sources = 4 lineage rows"
    assert {c for _, c in before} == {f"CLAIM-{ref}-001", f"CLAIM-{ref}-002"}, \
        "both sources contribute under the MINTING source's key — that is the corroboration"

    for suffix in ("", "-wal", "-shm"):
        p = Path(str(tmp_path / "bramber.db") + suffix)
        if p.exists():
            p.unlink()
    db.sync_from_disk()
    assert _lineage() == before, "corroboration must survive a full index loss"


def test_materialize_is_never_scoped_and_never_truncates(tmp_path: Path):
    """The regression behind specs/09 §2: the old `materialize --view X` read one view's digests
    but rewrote every extract's envelope, deleting the other views' units. The scoped rewrite is
    gone with the per-view digest itself; this pins that a materialize over a partially-scanned
    corpus still writes every envelope, each truthful about its own source."""
    _load_db(tmp_path, "noscope")
    _setup_project(tmp_path)
    manifest = ingest(make_adapter("text"), tmp_path)

    # Scan only ONE of the two sources.
    first = sorted(manifest, key=lambda m: m["slug"])[0]
    _write_scan(tmp_path, f"{first['slug']}.md",
                SCAN.replace("_bramber/extracts/acme.md", first["extract_path"]))
    materialize(tmp_path)

    envs = {p.stem: json.loads(p.read_text("utf-8"))
            for p in (tmp_path / "_bramber" / "units").glob("*.json")}
    assert len(envs) == 2, "every source keeps an envelope, scanned or not"
    scanned = envs.pop(first["slug"])
    assert scanned["units"], "the scanned source has units"
    (unscanned,) = envs.values()
    assert unscanned["units"] is None and "not yet" in unscanned["units_absent_reason"], \
        "the unscanned source says so, rather than faking an empty result"
