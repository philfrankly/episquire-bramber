#!/usr/bin/env python3
"""
bramber — SQLite index helper.

The .md tree is authoritative for content; this script derives bramber.db (the index +
lineage graph) from disk and exposes a few transactional writers. It is stdlib-only
so the Stop hook never fails for a missing dependency.

`schema.sql` is found relative to this file; the *data* tree it indexes is a separate
project directory given by `--root` (or $BRAMBER_ROOT, else the cwd). So one installed
engine serves many projects.

Lifted from the predecessor factory's engine/db.py per specs/01-engine-lift.md.
Generalizations vs the original:
  - source identity: content_sha -> identity_kind/identity_key/identity_json
    (text extracts with no identity header default to content_sha = sha256(body)).
  - view spec: reads views/<slug>/view.md (falls back to lens.md).
  - names: prfs -> views, _orchestrator -> _bramber, prf.db -> bramber.db, PRF_* -> BRAMBER_*.

CLI (prefer `python -m bramber.cli ...`; this main() mirrors it for direct use):
  python -m bramber.engine.db --init    --root <project>
  python -m bramber.engine.db --sync    --root <project>
  python -m bramber.engine.db --rebuild --root <project>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# schema.sql ships with the engine — found relative to THIS file, never the data root.
ENGINE_DIR = Path(__file__).resolve().parent

# The extract header's key set, declared once and shared with ingest.py (specs/06 T1.1).
# Loaded by path rather than by `from bramber.engine import header` because this module is
# deliberately runnable standalone — tests load it via spec_from_file_location and
# `python -m bramber.engine.db` runs it directly — so it must not assume it was imported as
# a package member. Still stdlib-only, and still no adapter in sight.
try:  # normal package import
    from bramber.engine import header
except ImportError:  # pragma: no cover — standalone load
    _spec = importlib.util.spec_from_file_location(
        "bramber_engine_header", ENGINE_DIR / "header.py")
    header = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(header)
SCHEMA = ENGINE_DIR / "schema.sql"

# Data-tree paths are resolved against the project root, set by configure() below.
ROOT: Path
DB_PATH: Path
EXTRACTS: Path
VIEWS_DIR: Path


def configure(root=None, db=None) -> None:
    """Point the engine at a project's data tree.

    Precedence: explicit arg > $BRAMBER_ROOT / $BRAMBER_DB > cwd.
    """
    global ROOT, DB_PATH, EXTRACTS, VIEWS_DIR
    ROOT = Path(root or os.environ.get("BRAMBER_ROOT") or Path.cwd()).resolve()
    DB_PATH = Path(db or os.environ.get("BRAMBER_DB") or (ROOT / "bramber.db"))
    EXTRACTS = ROOT / "_bramber" / "extracts"
    VIEWS_DIR = ROOT / "views"


configure()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def rel(p: Path) -> str:
    """Repo-relative posix path, for stable DB + MCP identifiers."""
    return p.resolve().relative_to(ROOT).as_posix()


def split_frontmatter(text: str):
    """Minimal flat-frontmatter parser (no YAML dependency).

    Returns (fields: dict, sources: list[str], body: str). `source:` keys may
    repeat and are collected into `sources` (each a 'extract | scan | contribution'
    pipe-triple). All other keys are flat 'key: value'.
    """
    if not text.startswith("---"):
        return {}, [], text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, [], text
    fields, sources = {}, []
    for ln in lines[1:end]:
        s = ln.strip()
        if not s or s.startswith("#") or ":" not in ln:
            continue
        key, _, val = ln.partition(":")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key == "source":
            sources.append(val)
        else:
            fields[key] = val
    body = "\n".join(lines[end + 1:]).strip("\n") + "\n"
    return fields, sources, body


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Bump when a table's SHAPE changes in a way `CREATE TABLE IF NOT EXISTS` cannot apply to an
# existing file. v2: version_sources gained `contribution` in its primary key.
# v3: digest_path -> scan_path in version_sources; mandate_versions and routing_decisions
#     removed with the mandate (specs/09 — views select over a shared claim store; there is
#     no project frame to version and no per-(source x view) routing to record).
SCHEMA_VERSION = 3


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create anything missing, and migrate shapes that `IF NOT EXISTS` would silently skip.

    The migration is a **drop and let sync rebuild**, which is only safe because of invariant 3:
    the .md tree is authoritative and every lineage edge is reconstructible from the version
    snapshots on disk. Losing the index is a non-event by design, so the cheapest correct
    migration is to stop pretending otherwise. Nothing that exists *only* in the database is
    touched.
    """
    stored = conn.execute("PRAGMA user_version").fetchone()[0]
    if stored and stored < SCHEMA_VERSION:
        # Derived-only tables whose shape changed. Sync repopulates them from the snapshots.
        conn.execute("DROP TABLE IF EXISTS version_sources")
        # Withdrawn features (v3): dropped outright, not migrated. mandate.md left the
        # product; its version history goes with it.
        conn.execute("DROP TABLE IF EXISTS mandate_versions")
        conn.execute("DROP TABLE IF EXISTS routing_decisions")
        # evaluations: scope CHECK narrowed to 'view'. No code path has ever written a row
        # (proposals live as _bramber/evaluations/ files on disk), so recreating is lossless.
        conn.execute("DROP TABLE IF EXISTS evaluations")
        print(f"[bramber] migrating index schema v{stored} -> v{SCHEMA_VERSION}: "
              f"lineage will be rebuilt from the version snapshots on disk", file=sys.stderr)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


# ---------------------------------------------------------------------------
# transactional writers (importable; also used by --sync)
# ---------------------------------------------------------------------------

def upsert_view(conn, slug, name, view_path):
    conn.execute(
        """INSERT INTO views(slug, name, view_path, created_at) VALUES(?,?,?,?)
           ON CONFLICT(slug) DO UPDATE SET name=excluded.name, view_path=excluded.view_path""",
        (slug, name, view_path, now()),
    )
    return conn.execute("SELECT id FROM views WHERE slug=?", (slug,)).fetchone()["id"]


def upsert_source(conn, *, url, title, source_type, author, date_published,
                  date_ingested, identity_kind, identity_key, identity_json, extract_path):
    conn.execute(
        """INSERT INTO sources(url, title, source_type, author, date_published, date_ingested,
                               identity_kind, identity_key, identity_json, extract_path)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(identity_key) DO UPDATE SET
               url=excluded.url, title=excluded.title, source_type=excluded.source_type,
               author=excluded.author, date_published=excluded.date_published,
               identity_kind=excluded.identity_kind, identity_json=excluded.identity_json,
               extract_path=excluded.extract_path""",
        (url, title, source_type, author, date_published, date_ingested,
         identity_kind, identity_key, identity_json, extract_path),
    )
    return conn.execute("SELECT id FROM sources WHERE identity_key=?", (identity_key,)).fetchone()["id"]


def _get_or_create_resource(conn, view_id, slug, title, description, maintainer, resource_path):
    row = conn.execute("SELECT id FROM resources WHERE view_id=? AND slug=?", (view_id, slug)).fetchone()
    if row:
        conn.execute(
            "UPDATE resources SET title=?, description=?, maintainer=?, resource_path=? WHERE id=?",
            (title, description, maintainer, resource_path, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        """INSERT INTO resources(view_id, slug, title, description, maintainer, resource_path, created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (view_id, slug, title, description, maintainer, resource_path, now()),
    )
    return cur.lastrowid


def _insert_version(conn, resource_id, version_num, content, change_summary, run_id, created_at):
    existing = conn.execute(
        "SELECT id FROM resource_versions WHERE resource_id=? AND version_num=?",
        (resource_id, version_num),
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO resource_versions(resource_id, version_num, content, content_sha,
                                         change_summary, run_id, created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (resource_id, version_num, content, sha256(content), change_summary, run_id, created_at),
    )
    return cur.lastrowid


def _link_source(conn, version_id, extract_path, scan_path, contribution):
    row = conn.execute("SELECT id FROM sources WHERE extract_path=?", (extract_path,)).fetchone()
    if not row:
        print(f"[bramber] lineage: no source for extract {extract_path!r}; skipping link", file=sys.stderr)
        return
    conn.execute(
        """INSERT OR IGNORE INTO version_sources(version_id, source_id, scan_path, contribution)
           VALUES(?,?,?,?)""",
        (version_id, row["id"], scan_path, contribution),
    )


def _refresh_current(conn, resource_id):
    row = conn.execute(
        "SELECT id FROM resource_versions WHERE resource_id=? ORDER BY version_num DESC LIMIT 1",
        (resource_id,),
    ).fetchone()
    if row:
        conn.execute("UPDATE resources SET current_version_id=? WHERE id=?", (row["id"], resource_id))


def _snapshot_text(view_slug, resource_slug, version_num, created_at, content_sha,
                   change_summary, sources, body):
    head = [
        "---",
        f"resource: {view_slug}/{resource_slug}",
        f"version: {version_num}",
        f"created_at: {created_at}",
        f"content_sha: {content_sha}",
        f"change_summary: {change_summary}",
    ]
    for s in sources or []:
        head.append(f"source: {s.get('extract','')} | {s.get('scan','')} | {s.get('contribution','')}")
    head.append("---")
    head.append("")
    return "\n".join(head) + body.rstrip("\n") + "\n"


def write_resource_version(view_slug, resource_slug, *, title, content, change_summary,
                           sources=None, description=None, maintainer="agent",
                           run_id=None, write_files=True, conn=None):
    """Mint a new immutable version of a resource: write RESOURCE.md + versions/<n>.md
    and record the DB rows + lineage. No-op (returns current) if content is unchanged.

    `sources` is a list of dicts: {"extract": "...", "scan": "...", "contribution": "..."}.
    """
    own = conn is None
    if own:
        conn = connect()
        ensure_schema(conn)
    def _bail(msg):
        """Raise without leaking the connection we opened. Windows holds a lock on an
        unclosed sqlite handle, so a bare `raise` here turns a clear error into a second,
        unrelated failure when the caller (or a test's tmp_path) tries to clean up."""
        if own:
            conn.close()
        raise SystemExit(msg)

    view = conn.execute("SELECT id FROM views WHERE slug=?", (view_slug,)).fetchone()
    if not view:
        _bail(f"[bramber] unknown view {view_slug!r}; create it with /new-view first")

    # Invariant 4 (human-gated artifacts) was prose only: an agent write would overwrite a
    # human-maintained resource without complaint, and `_get_or_create_resource` would quietly
    # downgrade its `maintainer` to 'agent' on the way past. The escape hatch is to declare
    # yourself — `maintainer="human"`, which is what /bramber:evaluate does — so the guard costs
    # the authorized path nothing and blocks the unauthorized one loudly.
    prior = conn.execute(
        "SELECT maintainer FROM resources WHERE view_id=? AND slug=?",
        (view["id"], resource_slug)).fetchone()
    if prior and prior["maintainer"] == "human" and maintainer != "human":
        _bail(
            f"[bramber] {view_slug}/{resource_slug} is `maintainer: human` and this write is "
            f"{maintainer!r}. Human-maintained resources are gated (invariant 4): edit it via "
            f"/bramber:evaluate, or pass maintainer='human' if you are that path."
        )

    res_dir = VIEWS_DIR / view_slug / "resources" / resource_slug
    resource_path = rel(res_dir / "RESOURCE.md")
    resource_id = _get_or_create_resource(
        conn, view["id"], resource_slug, title, description, maintainer, resource_path)

    latest = conn.execute(
        "SELECT version_num, content_sha FROM resource_versions WHERE resource_id=? "
        "ORDER BY version_num DESC LIMIT 1", (resource_id,)).fetchone()
    new_sha = sha256(content)
    if latest and latest["content_sha"] == new_sha:
        if own:
            conn.commit(); conn.close()
        return {"resource_id": resource_id, "version_num": latest["version_num"], "created": False}

    version_num = (latest["version_num"] + 1) if latest else 1
    created_at = now()

    if write_files:
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "versions").mkdir(exist_ok=True)
        (res_dir / "RESOURCE.md").write_text(content, encoding="utf-8")
        (res_dir / "versions" / f"{version_num}.md").write_text(
            _snapshot_text(view_slug, resource_slug, version_num, created_at, new_sha,
                           change_summary, sources, content),
            encoding="utf-8")

    vid = _insert_version(conn, resource_id, version_num, content, change_summary, run_id, created_at)
    for s in sources or []:
        _link_source(conn, vid, s.get("extract"), s.get("scan"), s.get("contribution"))
    _refresh_current(conn, resource_id)
    if own:
        conn.commit(); conn.close()
    return {"resource_id": resource_id, "version_id": vid, "version_num": version_num, "created": True}


def add_run(conn, kind, view_id=None, summary=None):
    cur = conn.execute(
        "INSERT INTO runs(kind, view_id, started_at, summary) VALUES(?,?,?,?)",
        (kind, view_id, now(), summary))
    return cur.lastrowid


# ---------------------------------------------------------------------------
# sync (disk -> index)
# ---------------------------------------------------------------------------

def _sync_views(conn):
    if not VIEWS_DIR.exists():
        return
    for d in sorted(p for p in VIEWS_DIR.iterdir() if p.is_dir()):
        spec = d / "view.md"
        if not spec.exists():
            spec = d / "lens.md"        # migration fallback
        if not spec.exists():
            continue
        fields, _, body = split_frontmatter(spec.read_text(encoding="utf-8"))
        name = fields.get("name") or fields.get("title")
        if not name:
            for line in body.splitlines():
                if line.startswith("# "):
                    name = line[2:].strip()
                    break
        upsert_view(conn, d.name, name or d.name, rel(spec))


def _sync_sources(conn):
    if not EXTRACTS.exists():
        return
    for f in sorted(EXTRACTS.glob("*.md")):
        fields, _, body = split_frontmatter(f.read_text(encoding="utf-8"))
        # Derived from the one declaration the writer also derives from (header.py), so the
        # reader cannot fall out of step with ingest.py — the drift that produced the NULL-url
        # bug. Fallbacks stay here and stay explicit; they are the engine's policy, not the
        # channel's shape.
        kw = header.read(fields)
        kw["identity_kind"] = kw["identity_kind"] or "content_sha"
        kw["identity_key"] = kw["identity_key"] or sha256(body)
        kw["date_ingested"] = kw["date_ingested"] or now()[:10]
        upsert_source(conn, extract_path=rel(f), **kw)


def _sync_resources(conn):
    if not VIEWS_DIR.exists():
        return
    for view_dir in sorted(p for p in VIEWS_DIR.iterdir() if p.is_dir()):
        view = conn.execute("SELECT id FROM views WHERE slug=?", (view_dir.name,)).fetchone()
        if not view:
            continue
        res_root = view_dir / "resources"
        if not res_root.exists():
            continue
        for res_dir in sorted(p for p in res_root.iterdir() if p.is_dir()):
            md = res_dir / "RESOURCE.md"
            meta, _, md_body = split_frontmatter(md.read_text(encoding="utf-8")) if md.exists() else ({}, [], "")
            title = meta.get("title") or meta.get("name") or res_dir.name
            description = meta.get("description")
            maintainer = meta.get("maintainer", "agent")
            resource_id = _get_or_create_resource(
                conn, view["id"], res_dir.name, title, description, maintainer,
                rel(md) if md.exists() else rel(res_dir))

            snaps = sorted((res_dir / "versions").glob("*.md"),
                           key=lambda p: int(p.stem) if p.stem.isdigit() else 0) \
                if (res_dir / "versions").exists() else []
            if snaps:
                for snap in snaps:
                    fields, srcs, body = split_frontmatter(snap.read_text(encoding="utf-8"))
                    try:
                        vnum = int(fields.get("version") or snap.stem)
                    except ValueError:
                        continue
                    vid = _insert_version(
                        conn, resource_id, vnum, body,
                        fields.get("change_summary", ""), None,
                        fields.get("created_at") or now())
                    for s in srcs:
                        parts = [x.strip() for x in s.split("|")]
                        parts += [""] * (3 - len(parts))
                        _link_source(conn, vid, parts[0], parts[1], parts[2])
            elif md.exists():
                _insert_version(conn, resource_id, 1, md_body,
                                "initial (synced from RESOURCE.md)", None, now())
            _refresh_current(conn, resource_id)


def sync_from_disk(conn=None):
    own = conn is None
    if own:
        conn = connect()
    ensure_schema(conn)
    _sync_views(conn)
    _sync_sources(conn)
    _sync_resources(conn)
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
              for t in ("views", "sources", "resources", "resource_versions",
                        "version_sources")}
    if own:
        conn.close()
    return counts


# ---------------------------------------------------------------------------
# CLI (mirror of bramber.cli for direct module use)
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="bramber DB helper")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", action="store_true", help="create bramber.db (if absent) then sync")
    g.add_argument("--sync", action="store_true", help="reconcile the index from the .md tree")
    g.add_argument("--rebuild", action="store_true", help="delete bramber.db and recreate from disk")
    ap.add_argument("--root", help="project data root (default: $BRAMBER_ROOT or cwd)")
    ap.add_argument("--db", help="path to bramber.db (default: <root>/bramber.db or $BRAMBER_DB)")
    args = ap.parse_args()

    configure(root=args.root, db=args.db)

    if args.rebuild and DB_PATH.exists():
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                p.unlink()

    counts = sync_from_disk()
    action = "rebuilt" if args.rebuild else ("initialized" if args.init else "synced")
    print(f"[bramber] {action} {DB_PATH}")
    print("[bramber] " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
