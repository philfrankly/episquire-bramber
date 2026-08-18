#!/usr/bin/env python3
"""
bramber — thin MCP server (stdio).

Read-only over bramber.db (the index built by db.py) plus the .md tree. It never
writes, never reasons, never processes — all reasoning is the agent's job.
Targets the official `mcp` Python SDK (>=1.2); install via `pip install bramber-engine[mcp]`.

Ships inside the bramber plugin. The plugin's .mcp.json launches it with
BRAMBER_ROOT / BRAMBER_DB pointing at the consuming project (${CLAUDE_PROJECT_DIR}),
so one engine serves every project that installs the plugin.

Resource URIs
  bramber://<view-slug>/<resource-slug>            current (latest) version
  bramber://<view-slug>/<resource-slug>@<n>        a pinned version
  bramber://<view-slug>/<resource-slug>/details    on-demand DETAILS.md

Tools
  list_views · list_versions · resource_lineage · search_resources

Env: BRAMBER_DB (path to bramber.db), BRAMBER_ROOT (repo root, for DETAILS.md / disk fallback).

Lifted from the predecessor factory's engine/server.py per specs/01-engine-lift.md
(renames only: prfs->views, prf://->bramber://, list_prfs->list_views, PRF_*->BRAMBER_*).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

ROOT = Path(os.environ.get("BRAMBER_ROOT") or Path(__file__).resolve().parent.parent.parent)
DB_PATH = Path(os.environ.get("BRAMBER_DB") or (ROOT / "bramber.db"))

server = Server("bramber")


# ---------------------------------------------------------------------------
# read-only DB access (fresh ro connection per call; WAL -> consistent snapshot)
# ---------------------------------------------------------------------------

def q(sql: str, params: tuple = ()):
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def one(sql: str, params: tuple = ()):
    rows = q(sql, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# resources
# ---------------------------------------------------------------------------

@server.list_resources()
async def list_resources() -> list[types.Resource]:
    out: list[types.Resource] = []
    for r in q(
        """SELECT v.slug AS view, r.slug AS rslug, r.title, r.description
           FROM resources r JOIN views v ON v.id = r.view_id
           WHERE r.status = 'active'
           ORDER BY v.slug, r.slug"""
    ):
        out.append(types.Resource(
            uri=f"bramber://{r['view']}/{r['rslug']}",
            name=r["title"] or r["rslug"],
            description=r["description"] or f"Resource from the {r['view']} view.",
            mimeType="text/markdown",
        ))
    return out


@server.read_resource()
async def read_resource(uri) -> str:
    u = urlparse(str(uri))
    scheme, host, path = u.scheme, u.netloc, u.path.lstrip("/")

    if scheme == "bramber":
        view = host
        if path.endswith("/details"):
            rslug = path[: -len("/details")]
            details = ROOT / "views" / view / "resources" / rslug / "DETAILS.md"
            if not details.exists():
                raise ValueError(f"no DETAILS.md for {uri}")
            return details.read_text(encoding="utf-8")

        if "@" in path:
            rslug, _, vnum = path.partition("@")
            row = one(
                """SELECT rv.content FROM resource_versions rv
                   JOIN resources r ON r.id = rv.resource_id
                   JOIN views v ON v.id = r.view_id
                   WHERE v.slug=? AND r.slug=? AND rv.version_num=?""",
                (view, rslug, int(vnum)))
            if not row:
                raise ValueError(f"no version {vnum} for {uri}")
            return row["content"]

        rslug = path
        row = one(
            """SELECT rv.content FROM resources r
               JOIN views v ON v.id = r.view_id
               JOIN resource_versions rv ON rv.id = r.current_version_id
               WHERE v.slug=? AND r.slug=?""",
            (view, rslug))
        if row:
            return row["content"]
        disk = ROOT / "views" / view / "resources" / rslug / "RESOURCE.md"
        if disk.exists():
            return disk.read_text(encoding="utf-8")
        raise ValueError(f"unknown resource {uri}")

    raise ValueError(f"unsupported uri scheme: {uri}")


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

TOOLS = [
    types.Tool(
        name="list_views",
        description="List all views with status and resource counts.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="list_versions",
        description="List the version history of a resource (newest first).",
        inputSchema={"type": "object", "properties": {
            "view": {"type": "string"}, "resource": {"type": "string"}},
            "required": ["view", "resource"]},
    ),
    types.Tool(
        name="resource_lineage",
        description="Which sources caused a resource version (defaults to the current version).",
        inputSchema={"type": "object", "properties": {
            "view": {"type": "string"}, "resource": {"type": "string"},
            "version": {"type": "integer"}},
            "required": ["view", "resource"]},
    ),
    types.Tool(
        name="search_resources",
        description="Full-text-ish search over resource titles and current content.",
        inputSchema={"type": "object", "properties": {
            "query": {"type": "string"}, "view": {"type": "string"}},
            "required": ["query"]},
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


def _list_views():
    return [dict(r) for r in q(
        """SELECT v.slug, v.name, v.status,
                  (SELECT COUNT(*) FROM resources r WHERE r.view_id=v.id AND r.status='active') AS resources
           FROM views v ORDER BY v.slug""")]


def _list_versions(view, resource):
    return [dict(r) for r in q(
        """SELECT rv.version_num, rv.created_at, rv.change_summary, rv.content_sha
           FROM resource_versions rv
           JOIN resources r ON r.id = rv.resource_id
           JOIN views v ON v.id = r.view_id
           WHERE v.slug=? AND r.slug=?
           ORDER BY rv.version_num DESC""", (view, resource))]


def _resource_lineage(view, resource, version=None):
    if version is None:
        vrow = one(
            """SELECT r.current_version_id AS vid FROM resources r
               JOIN views v ON v.id=r.view_id WHERE v.slug=? AND r.slug=?""", (view, resource))
        vid = vrow["vid"] if vrow else None
    else:
        vrow = one(
            """SELECT rv.id AS vid FROM resource_versions rv
               JOIN resources r ON r.id=rv.resource_id JOIN views v ON v.id=r.view_id
               WHERE v.slug=? AND r.slug=? AND rv.version_num=?""", (view, resource, version))
        vid = vrow["vid"] if vrow else None
    if not vid:
        return {"view": view, "resource": resource, "version": version, "sources": []}
    sources = [dict(r) for r in q(
        """SELECT s.title, s.url, s.source_type, vs.contribution, vs.scan_path
           FROM version_sources vs JOIN sources s ON s.id = vs.source_id
           WHERE vs.version_id=?""", (vid,))]
    return {"view": view, "resource": resource, "version": version, "sources": sources}


def _search_resources(query, view=None):
    like = f"%{query}%"
    sql = ("""SELECT v.slug AS view, r.slug AS resource, r.title
              FROM resources r JOIN views v ON v.id=r.view_id
              LEFT JOIN resource_versions rv ON rv.id = r.current_version_id
              WHERE r.status='active' AND (r.title LIKE ? OR rv.content LIKE ?)""")
    params = [like, like]
    if view:
        sql += " AND v.slug=?"
        params.append(view)
    sql += " ORDER BY v.slug, r.slug"
    return [{"uri": f"bramber://{r['view']}/{r['resource']}", "title": r["title"]}
            for r in q(sql, tuple(params))]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    args = arguments or {}
    if name == "list_views":
        result = _list_views()
    elif name == "list_versions":
        result = _list_versions(args["view"], args["resource"])
    elif name == "resource_lineage":
        result = _resource_lineage(args["view"], args["resource"], args.get("version"))
    elif name == "search_resources":
        result = _search_resources(args["query"], args.get("view"))
    else:
        raise ValueError(f"unknown tool: {name}")
    return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
