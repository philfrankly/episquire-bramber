"""Run status & resume (bramber/run.py) — spec 05, as amended by spec 09.

Status is derived from disk (authoritative); the run-log is an advisory overlay that only
distinguishes attempted-and-failed from never-reached. Scanning is corpus-wide (one scan per
source), so the pending set is corpus-wide too; views appear only through their resources.
These tests pin both layers and the seam (the engine never imports run). Hand-authored roots,
like tests/test_compile_selector.py.

Run:  cd bramber && python -m pytest tests/test_run.py
"""

from __future__ import annotations

import json
from pathlib import Path

from bramber import run

REPO = Path(__file__).resolve().parent.parent


# --- the seam ---------------------------------------------------------------

def test_engine_never_imports_run():
    """run.py is a CLI/agent-layer sibling; the domain-blind engine must not depend on it."""
    for py in (REPO / "bramber" / "engine").glob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "bramber.run" not in src and "import run" not in src, \
            f"{py.name} reaches for run; status/resume belongs outside bramber/engine/"


# --- fixtures on disk -------------------------------------------------------

def _extract(root: Path, slug: str, key: str, body: str = "body"):
    p = root / "_bramber" / "extracts" / f"{slug}__{key[:8]}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nidentity_kind: content_sha\nidentity_key: {key}\n"
                 f"source_type: transcript\ntitle: \"{slug}\"\ndate_ingested: 2026-07-17\n---\n{body}\n",
                 encoding="utf-8")
    return f"_bramber/extracts/{slug}__{key[:8]}.md"


def _view(root: Path, slug: str):
    p = root / "views" / slug / "view.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {slug}\nslug: {slug}\nview_version: 1\nmaintainer: human\n---\n# {slug}\n",
                 encoding="utf-8")


def _scan(root: Path, name: str, source_rel: str, discarded: bool = False):
    p = root / "_bramber" / "scans" / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nsource: {source_rel}\nscan_date: 2026-07-17\n"
                 f"discarded: {'true' if discarded else 'false'}\n---\n## Claims\n- c\n",
                 encoding="utf-8")


def _resource(root: Path, view: str, slug: str, versioned: bool = True):
    d = root / "views" / view / "resources" / slug
    (d / "versions").mkdir(parents=True, exist_ok=True)
    (d / "RESOURCE.md").write_text(f"---\nname: {slug}\nview: {view}\nmaintainer: agent\n---\n# {slug}\n",
                                   encoding="utf-8")
    if versioned:
        (d / "versions" / "1.md").write_text("---\nversion: 1\n---\nbody\n", encoding="utf-8")


# --- derived status ---------------------------------------------------------

def test_pending_is_exact(tmp_path: Path):
    """3 extracts, 2 scanned → exactly the 1 unscanned source is pending, corpus-wide."""
    e1 = _extract(tmp_path, "alpha", "k_alpha")
    e2 = _extract(tmp_path, "beta", "k_beta")
    e3 = _extract(tmp_path, "gamma", "k_gamma")
    _scan(tmp_path, "alpha", e1)
    _scan(tmp_path, "beta", e2)

    s = run.derive_status(tmp_path)
    sc = s["scans"]
    assert s["sources_indexed"] == 3
    assert sc["present"] == 2
    assert sc["expected"] == 3
    assert sc["pending"] == [e3]                  # exactly gamma, by extract rel path
    assert sc["discarded"] == 0


def test_discarded_counted_not_pending(tmp_path: Path):
    e1 = _extract(tmp_path, "alpha", "k_alpha")
    _scan(tmp_path, "alpha", e1, discarded=True)
    sc = run.derive_status(tmp_path)["scans"]
    assert sc["present"] == 1 and sc["discarded"] == 1 and sc["pending"] == []


def test_resources_present_and_versioned(tmp_path: Path):
    _view(tmp_path, "v")
    _resource(tmp_path, "v", "overview", versioned=True)
    _resource(tmp_path, "v", "draft", versioned=False)
    v = run.derive_status(tmp_path, view="v")["views"]["v"]
    assert v["resources_present"] == 2 and v["resources_current"] == 1


def test_pending_ingest_from_inbox(tmp_path: Path):
    """An inbox deposit whose body-sha has no extract is pending ingest; one already ingested is not."""
    from bramber.engine import db
    inbox = tmp_path / "_bramber" / "inbox"
    inbox.mkdir(parents=True)
    # deposit A: ingested (its body-sha matches an extract's identity_key)
    bodyA = "the alpha body"
    keyA = db.sha256(bodyA)
    _extract(tmp_path, "alpha", keyA, body=bodyA)
    (inbox / "a.md").write_text(f"---\nsource_type: transcript\ntitle: \"a\"\n---\n{bodyA}\n", encoding="utf-8")
    # deposit B: not ingested
    (inbox / "b.md").write_text("---\nsource_type: transcript\ntitle: \"b\"\n---\nthe beta body\n", encoding="utf-8")

    ib = run.derive_status(tmp_path)["inbox"]
    assert ib["deposits"] == 2 and ib["ingested"] == 1 and ib["pending_ingest"] == ["b.md"]


# --- advisory run-log overlay ----------------------------------------------

def test_run_log_roundtrip_and_latest_wins(tmp_path: Path):
    run.record(tmp_path, "scan", [{"item": "x", "phase": "scan", "outcome": "failed", "reason": "spend"}])
    run.record(tmp_path, "scan", [{"item": "x", "phase": "scan", "outcome": "ok"}])
    latest = run.latest_outcomes(tmp_path)
    assert latest["x|scan"]["outcome"] == "ok"   # last writer wins


def test_failed_overlay_separates_from_pending(tmp_path: Path):
    """A pending source whose latest scan outcome is 'failed' surfaces in failed, not silently
    in bare pending — the attempted-vs-never-reached distinction."""
    e1 = _extract(tmp_path, "alpha", "k_alpha")
    e2 = _extract(tmp_path, "beta", "k_beta")   # never attempted
    run.record(tmp_path, "scan", [{"item": e1, "phase": "scan",
                                   "outcome": "failed", "reason": "spend limit"}])
    sc = run.status(tmp_path)["scans"]
    assert sc["failed"] == [e1]
    assert sc["pending"] == [e2]                 # beta is truly never-reached, stays pending


def test_log_is_advisory_status_correct_without_it(tmp_path: Path):
    """Delete the run-log: derived present/pending is unchanged; only the failed annotation empties."""
    e1 = _extract(tmp_path, "alpha", "k_alpha")
    run.record(tmp_path, "scan", [{"item": e1, "phase": "scan", "outcome": "failed"}])
    assert run.status(tmp_path)["scans"]["failed"] == [e1]
    import shutil
    shutil.rmtree(tmp_path / "_bramber" / "runs")
    sc = run.status(tmp_path)["scans"]
    assert sc["failed"] == [] and sc["pending"] == [e1]  # still correctly pending


def test_status_is_json_serializable_and_formats(tmp_path: Path):
    _view(tmp_path, "v")
    _extract(tmp_path, "alpha", "k_alpha")
    s = run.status(tmp_path, view="v")
    json.dumps(s)                                  # JSON path (`bramber status --json`)
    assert "bramber status" in run.format_status(s)  # human path
