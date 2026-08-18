"""bramber run — derived pipeline status + an advisory run-log.  (spec 05, as amended by spec 09)

Answers "what has this run done, and what is still pending?" so an interrupted run
(spend-limit kill, classifier outage, process restart) is resumed by reading, not by forensics.

Two layers, per spec 05 §1:

  - **Derived status is authoritative.** What is *done* is a fact on disk: a source is ingested
    iff its extract exists; a source is scanned iff a scan file names its extract; a resource
    exists iff its RESOURCE.md exists. `derive_status` reconciles expected vs present and computes
    pending — the same way `sync` derives the index. No stored manifest that could drift.

  - **The run-log is advisory.** Disk cannot tell attempted-and-failed from never-reached — the
    gap that turns recovery into forensics. Actors append per-item outcomes to
    `_bramber/runs/<ts>-<cmd>.jsonl`; `status` overlays the latest outcome per item. Delete
    `_bramber/runs/` and status is still correct about what exists; only the why-missing note is lost.

Scanning is corpus-wide (one scan per source, no view in sight), so the pending set is
corpus-wide too; views appear in status only through their resources, which is all a view is —
a projection over the shared store.

Stdlib-only; the **engine never imports this** (same boundary as `trace.py`). It uses
`bramber.engine.db` helpers (`split_frontmatter` / `sha256` / `now`) and `bramber.scan` (the one
scan reader) so it reads disk exactly as the pipeline does — importing them here is fine; the
reverse never happens.
"""

from __future__ import annotations

import json
from pathlib import Path

from bramber import scan as scan_mod
from bramber.engine import db


def _rel(root: Path, f: Path) -> str:
    """Repo-relative posix path — the same string a scan's `source:` frontmatter carries."""
    return f.resolve().relative_to(root.resolve()).as_posix()


# ---------------------------------------------------------------------------
# advisory run-log
# ---------------------------------------------------------------------------

def record(root, cmd: str, entries: list[dict]) -> Path:
    """Append per-item outcomes to `_bramber/runs/<ts>-<cmd>.jsonl`.

    Each entry: {item, phase, outcome, detail?, reason?}. Append-only; returns the file path.
    """
    runs = Path(root) / "_bramber" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = db.now().replace("-", "").replace(":", "").replace("T", "-")  # 20260718-001233
    path = runs / f"{stamp}-{cmd}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps({
                "item": str(e.get("item", "")),
                "phase": e.get("phase", ""),
                "outcome": e.get("outcome", ""),
                "detail": e.get("detail", ""),
                "reason": e.get("reason", ""),
            }) + "\n")
    return path


def latest_outcomes(root) -> dict[str, dict]:
    """Read every `_bramber/runs/*.jsonl` in filename (=chronological) order; return the last
    entry per `<item>|<phase>`. Malformed lines are skipped, never raised."""
    runs = Path(root) / "_bramber" / "runs"
    out: dict[str, dict] = {}
    if not runs.exists():
        return out
    for f in sorted(runs.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (ValueError, TypeError):
                continue
            out[f"{e.get('item','')}|{e.get('phase','')}"] = e
    return out


# ---------------------------------------------------------------------------
# derived status
# ---------------------------------------------------------------------------

def _view_dirs(root: Path, view: str | None):
    views = root / "views"
    if not views.exists():
        return []
    dirs = [d for d in sorted(views.iterdir()) if d.is_dir() and (d / "view.md").exists()]
    if view:
        dirs = [d for d in dirs if d.name == view]
    return dirs


def derive_status(root, view: str | None = None) -> dict:
    """Pure disk derivation — no run-log. See module docstring / spec 05 §3."""
    root = Path(root)
    inbox = root / "_bramber" / "inbox"
    extracts_dir = root / "_bramber" / "extracts"

    links = sorted(inbox.glob("*.txt")) if inbox.exists() else []
    deposits = sorted(inbox.glob("*.md")) if inbox.exists() else []

    # present sources: identity_key -> extract rel path
    extract_keys: dict[str, str] = {}
    ext_files = sorted(extracts_dir.glob("*.md")) if extracts_dir.exists() else []
    for f in ext_files:
        fields, _, body = db.split_frontmatter(f.read_text(encoding="utf-8"))
        key = fields.get("identity_key") or db.sha256(body)
        extract_keys[key] = _rel(root, f)

    # inbox deposits not yet ingested (body-sha absent from the extract set)
    pending_ingest = []
    for d in deposits:
        _, _, body = db.split_frontmatter(d.read_text(encoding="utf-8"))
        if db.sha256(body) not in extract_keys:
            pending_ingest.append(d.name)

    # scans: one per source, corpus-wide. A source is scanned iff a scan's `source:` names its
    # extract — read through the one scan reader, never a second parser.
    all_sources = set(extract_keys.values())
    scanned, discarded = set(), 0
    scans = scan_mod.read_all(root)
    for s in scans:
        if s.source:
            scanned.add(s.source.strip())
        if s.discarded:
            discarded += 1
    pending_scan = sorted(all_sources - scanned)

    per_view = {}
    for vd in _view_dirs(root, view):
        res_root = vd / "resources"
        res_dirs = [r for r in sorted(res_root.iterdir()) if r.is_dir()] if res_root.exists() else []
        present_res = [r for r in res_dirs if (r / "RESOURCE.md").exists()]
        current_res = [r for r in present_res
                       if (r / "versions").exists() and any((r / "versions").glob("*.md"))]
        per_view[vd.name] = {
            "resources_present": len(present_res),
            "resources_current": len(current_res),
            "stale": [],                         # placeholder until spec 04 stage 4
        }

    return {
        "root": str(root),
        "inbox": {
            "links_pending_fetch": len(links),
            "deposits": len(deposits),
            "ingested": len(deposits) - len(pending_ingest),
            "pending_ingest": pending_ingest,
        },
        "sources_indexed": len(ext_files),
        "scans": {
            "present": len(scans),
            "expected": len(all_sources),
            "pending": pending_scan,             # extract rel paths; basename-ed in the human view
            "failed": [],                        # filled by status() overlay
            "discarded": discarded,
        },
        "views": per_view,
    }


def status(root, view: str | None = None) -> dict:
    """`derive_status` overlaid with the advisory run-log: a pending scan whose latest outcome
    is `failed` moves from `pending` (never-reached) into `failed`."""
    s = derive_status(root, view)
    outcomes = latest_outcomes(root)
    still_pending, failed = [], []
    for src in s["scans"]["pending"]:
        # scan item key is "<extract-rel>" (spec 05 §2, amended by spec 09); phase "scan"
        e = outcomes.get(f"{src}|scan")
        (failed if e and e.get("outcome") == "failed" else still_pending).append(src)
    s["scans"]["pending"] = still_pending
    s["scans"]["failed"] = failed
    return s


# ---------------------------------------------------------------------------
# human rendering
# ---------------------------------------------------------------------------

def format_status(s: dict) -> str:
    ib = s["inbox"]
    sc = s["scans"]
    lines = [
        f"bramber status — {s['root']}",
        f"  inbox: {ib['deposits']} deposit(s), {ib['ingested']} ingested, "
        f"{len(ib['pending_ingest'])} pending ingest, {ib['links_pending_fetch']} link(s) to fetch",
        f"  sources indexed: {s['sources_indexed']}",
        f"  scans: {sc['present']}/{sc['expected']} "
        f"({len(sc['failed'])} failed, {sc['discarded']} discarded)",
    ]
    if ib["pending_ingest"]:
        lines.append("    pending ingest: " + ", ".join(ib["pending_ingest"]))
    if sc["pending"]:
        lines.append("    pending scan: " + ", ".join(Path(p).stem for p in sc["pending"]))
    if sc["failed"]:
        lines.append("    failed scan:  " + ", ".join(Path(p).stem for p in sc["failed"]))
    for vname, v in s["views"].items():
        lines.append(
            f"  view {vname}: resources {v['resources_present']} "
            f"({v['resources_current']} versioned)")
    return "\n".join(lines)
