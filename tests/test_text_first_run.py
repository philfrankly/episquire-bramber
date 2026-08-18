"""First TEXT run: the falsifiable generality gate (specs/03-first-text-run.md).

The text analog of tests/test_first_run.py. It proves bramber serves a NON-code (text /
competitive-intelligence) domain end-to-end — fake inbox sources -> extract -> view -> versioned
resource with content_sha lineage — **with no edits to bramber/engine/ or bramber/compile.py**.
If this needs an engine edit, the seam was drawn wrong (spec 00 §1, the falsifiable test).

Differences from the code gate, on purpose:
  - identity is `content_sha` (text is static), not `git_anchored`.
  - `extract_units` is empty at ingest: text extraction is interpretive, done by the agent's
    scan in a second pass. This test exercises the agent-authored resource path (Mode 2 of
    /bramber:process) — the agent writes prose and calls `write_resource_version` directly —
    standing in for the agent with deterministic markdown. (The deterministic selector path
    is covered by tests/test_scan.py and tests/test_compile_selector.py.)
  - stdlib-only: no network. Runs on any checkout (like tests/test_compile_selector.py).

Run:  cd bramber && python -m pytest tests/test_text_first_run.py
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "bramber" / "engine"


def _load_db():
    spec = importlib.util.spec_from_file_location("bramber_db_text_run", ENGINE / "db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lineage(db_path: Path, view_slug: str, resource_slug: str):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT s.identity_kind, s.source_type, s.extract_path, vs.contribution
               FROM version_sources vs
               JOIN sources s ON s.id = vs.source_id
               JOIN resource_versions rv ON rv.id = vs.version_id
               JOIN resources r ON r.id = rv.resource_id
               JOIN views v ON v.id = r.view_id
               WHERE v.slug = ? AND r.slug = ?""",
            (view_slug, resource_slug),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- fixtures authored on disk (no network) ---------------------------------

INBOX = {
    "acme-earnings-call.md": (
        "---\n"
        "source_url: https://www.youtube.com/watch?v=fake-acme-q3\n"
        "source_type: transcript\n"
        'title: "Acme Q3 Earnings Call"\n'
        "author: Acme IR\n"
        "date_published: 2026-05-01\n"
        "---\n"
        "# Acme Q3 Earnings Call\n\n"
        "Revenue grew 22% year over year, driven by the agents product line. "
        "Management guided to accelerating enterprise adoption into Q4.\n"
    ),
    "widget-market-report.md": (
        "---\n"
        "source_url: https://example.com/widget-market-2026\n"
        "source_type: article\n"
        'title: "The 2026 Widget Market, Mapped"\n'
        "author: J. Analyst\n"
        "date_published: 2026-04-18\n"
        "---\n"
        "# The 2026 Widget Market, Mapped\n\n"
        "Three vendors now hold 70% share. Pricing pressure is shifting value "
        "toward integration and away from the core widget.\n"
    ),
    "analyst-note.md": (
        "---\n"
        "source_url: file:///notes/analyst-note.md\n"
        "source_type: doc\n"
        'title: "Internal Analyst Note"\n'
        "author: Internal\n"
        "date_published: 2026-06-02\n"
        "---\n"
        "# Internal Analyst Note\n\n"
        "Our read: the agents narrative and the widget-integration shift are the "
        "same story told from two ends of the value chain.\n"
    ),
}

VIEW_MD = (
    "---\n"
    "name: Market Overview\n"
    "slug: market-overview\n"
    "view_version: 1\n"
    "maintainer: human\n"
    "---\n\n"
    "# Market Overview\n\n"
    "> Read when compiling the market-overview view.\n\n"
    "## Thesis\n"
    "The single best current reading of the market: what is happening, what it means, "
    "and where the evidence is strongest. Breadth with provenance.\n\n"
    "## Projects\n"
    "The claims this view pulls from the shared scan store. (This view is authored on the "
    "agent path — no deterministic selector block, which is allowed; compile requires one, "
    "the agent path does not.)\n\n"
    "## Weighting\n"
    "Primary sources and recent, corroborated claims carry more weight.\n\n"
    "## Discard\n"
    "Speculation with no evidence; sources that address none of the thesis.\n"
)


def _seed_inbox(root: Path):
    inbox = root / "_bramber" / "inbox"
    inbox.mkdir(parents=True)
    for name, text in INBOX.items():
        (inbox / name).write_text(text, encoding="utf-8")


def _author_view(root: Path):
    view_dir = root / "views" / "market-overview"
    view_dir.mkdir(parents=True)
    (view_dir / "view.md").write_text(VIEW_MD, encoding="utf-8")


def _synthesize(db, manifest):
    """Stand-in for the agent (Mode 2 of /bramber:process): write the resource + lineage
    directly via the domain-blind engine writer. Deterministic so the gate is automated."""
    content = (
        "---\n"
        "name: overview\n"
        "title: Market Overview\n"
        'description: "Market overview synthesized from the seeded sources."\n'
        "view: market-overview\n"
        f"source_count: {len(manifest)}\n"
        "maintainer: agent\n"
        "---\n\n"
        "# Market Overview\n\n"
        "**Load this resource when:** you need the current best reading of the market.\n\n"
        "## Current Understanding\n"
        "The agents narrative (Acme Q3) and the widget-integration shift are two ends of "
        "one value-chain story: value is migrating from the core artifact to integration.\n"
    )
    sources = [
        {"extract": m["extract_path"], "scan": None, "contribution": f"seed:{m['slug']}"}
        for m in manifest
    ]
    return db.write_resource_version(
        "market-overview", "overview",
        title="Market Overview", content=content,
        change_summary="initial synthesis", sources=sources,
        description="Market overview synthesized from the seeded sources.",
    )


def test_text_first_run(tmp_path: Path):
    from bramber.ingest import ingest, make_adapter

    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")

    # 1. seed a fake inbox (the agent's fetch output) — no network.
    _seed_inbox(tmp_path)

    # 2. ingest via the TextAdapter (content_sha identity; units NOT materialized).
    adapter = make_adapter("text", repo=str(tmp_path))   # repo unused for text
    manifest = ingest(adapter, tmp_path)
    assert len(manifest) == len(INBOX)
    assert all(m["n_units"] == 0 for m in manifest), "text materializes no units at ingest"
    assert (tmp_path / "_bramber" / "extracts").is_dir()

    # 2b. The units envelope must DECLARE that it holds nothing, rather than writing `[]`.
    # For the whole life of the repo this directory held correctly-named ~200-byte
    # `{"units": []}` files — indistinguishable from extraction that ran and legitimately
    # found nothing, so the artifact read as work that had happened and misrepresented the
    # text path to its own maintainer (specs/07 §5.4).
    envelope = json.loads(
        (tmp_path / "_bramber" / "units" / f"{manifest[0]['slug']}.json").read_text(encoding="utf-8"))
    assert envelope["units"] is None, "no units must be null, not an empty list"
    assert "TextAdapter.extract_units" in envelope["units_absent_reason"], \
        "the envelope must name the code responsible, so the status is readable without the trace"

    # 3. author one text view (no ```selector block — text never calls parse_selector).
    _author_view(tmp_path)

    # 4. sync: index the extracts as sources + register the view.
    counts = db.sync_from_disk()
    assert counts["views"] == 1
    assert counts["sources"] == len(manifest)

    # 5. synthesize the resource (the agent's job; deterministic stand-in here).
    res = _synthesize(db, manifest)
    assert res["created"] is True
    assert res["version_num"] == 1

    # 6. re-sync to index the freshly written resource/version from disk.
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    db.sync_from_disk()

    # --- the acceptance gate -------------------------------------------------
    conn = sqlite3.connect(str(tmp_path / "bramber.db"))
    conn.row_factory = sqlite3.Row
    try:
        srcs = conn.execute(
            "SELECT identity_kind, source_type, url, author, date_published FROM sources"
        ).fetchall()
        assert len(srcs) == len(manifest)
        assert all(r["identity_kind"] == "content_sha" for r in srcs), \
            "text sources carry content_sha identity (contrast: code is git_anchored)"
        assert {r["source_type"] for r in srcs} == {"transcript", "article", "doc"}, \
            "source_type from the inbox frontmatter survived the ingest header round-trip"

        # Provenance must survive the same round-trip. `db._sync_sources` reads source_url/
        # author/date_published off the extract header, so ingest has to write them: for a
        # long time it did not, and every text source indexed with a NULL url — an invisible
        # lineage hole in an engine whose whole product is cited provenance. This asserts the
        # writer and the reader agree, which is the thing that silently drifted.
        assert {r["url"] for r in srcs} == {
            "https://www.youtube.com/watch?v=fake-acme-q3",
            "https://example.com/widget-market-2026",
            "file:///notes/analyst-note.md",
        }, "source_url must reach the index — a colon-bearing URL survives the flat parser"
        assert {r["author"] for r in srcs} == {"Acme IR", "J. Analyst", "Internal"}
        assert all(r["date_published"] for r in srcs), "date_published must reach the index"

        assert conn.execute("SELECT 1 FROM views WHERE slug='market-overview'").fetchone()
        assert conn.execute("SELECT 1 FROM resources WHERE slug='overview'").fetchone()
        vrow = conn.execute(
            """SELECT rv.version_num FROM resource_versions rv
               JOIN resources r ON r.id = rv.resource_id
               JOIN views v ON v.id = r.view_id
               WHERE v.slug='market-overview' AND r.slug='overview'
               ORDER BY rv.version_num""").fetchall()
        assert [r["version_num"] for r in vrow] == [1], "exactly version 1 expected"
    finally:
        conn.close()

    lineage = _lineage(tmp_path / "bramber.db", "market-overview", "overview")
    assert len(lineage) == len(manifest), "every seeded source must appear in lineage"
    assert all(r["identity_kind"] == "content_sha" for r in lineage)

    snapshot = (tmp_path / "views" / "market-overview" / "resources" / "overview"
                / "versions" / "1.md")
    assert snapshot.exists(), "the version snapshot must be written to disk"
    snap_text = snapshot.read_text(encoding="utf-8")
    assert "source:" in snap_text, "the snapshot must carry source lineage lines"
    assert "## Current Understanding" in snap_text


def test_text_resource_idempotent(tmp_path: Path):
    """Re-synthesizing identical content mints no new version — the domain-blind content_sha
    no-op path works for text exactly as for code."""
    from bramber.ingest import ingest, make_adapter

    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    _seed_inbox(tmp_path)
    manifest = ingest(make_adapter("text", repo=str(tmp_path)), tmp_path)
    _author_view(tmp_path)
    db.sync_from_disk()

    first = _synthesize(db, manifest)
    second = _synthesize(db, manifest)
    assert first["created"] is True
    assert second["created"] is False, "recompiling unchanged inputs must not mint a new version"
    assert second["version_num"] == 1


if __name__ == "__main__":
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="bramber_text_run_"))
    try:
        test_text_first_run(tmp)
        print("OK — text first run: market-overview/overview readable, v1, content_sha lineage")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
