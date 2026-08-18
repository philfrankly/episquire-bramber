#!/usr/bin/env python3
"""bramber — the retrieval MCP server (stdio). The sibling, not the engine.

Read-only tools over the unit store and the candidate index, per `specs/10` §6 as ruled by
`specs/11` S3. **`bramber/engine/server.py` is untouched by design**: the engine surface
serves the compiled views deterministically (resources, versions, lineage — the questions a
human anticipated); this surface answers the ones nobody did, and both cite the same store.
An assistant session composes the two servers.

Requires both extras: `[mcp]` (this module imports the SDK eagerly, exactly like the engine
server) and `[embed]` (search embeds the query; the index it reads was built by
`bramber index`). Launched by `bramber serve-retrieval`; never imported by anything else, so
a stdlib-only install never pays for either dependency.

Tools
  search_units        hybrid query + the selector's own `match.<field>` filters
  contradictions_for  every recorded tension citing a stored key, sides flagged
  expand              depth-bounded traversal over relationships the record contains

All logic lives in `bramber.retrieval` — this file is registration, so every tool is
testable without an MCP client.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from bramber import retrieval

ROOT = Path(os.environ.get("BRAMBER_ROOT") or Path.cwd())

server = Server("bramber-retrieval")

TOOLS = [
    types.Tool(
        name="search_units",
        description=(
            "Hybrid (embedding + keyword) search over the shared unit store. Returns full "
            "units with support, reliability floor, variants and provenance — every citation "
            "resolves on disk. `match` uses the view selector's predicate vocabulary: any-of "
            "over list-valued payload fields, exact over scalars."),
        inputSchema={"type": "object", "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer", "default": 10},
            "kinds": {"type": "array", "items": {"type": "string"}},
            "match": {"type": "object",
                      "additionalProperties": {"type": "array", "items": {"type": "string"}}}},
            "required": ["query"]},
    ),
    types.Tool(
        name="contradictions_for",
        description=(
            "Every recorded contradiction whose sides cite this exact stored key. Sides are "
            "served flagged (`unresolved`, `side_witness_mismatch`), never dropped or "
            "re-pointed. A key nobody cites returns count 0. **Read `unattributable` before "
            "concluding a claim is uncontested**: it carries tensions with a side that "
            "resolves to nothing, which may be naming this claim — count 0 with a non-empty "
            "`unattributable` means the record cannot answer, not that there is no tension."),
        inputSchema={"type": "object", "properties": {
            "claim_key": {"type": "string"}},
            "required": ["claim_key"]},
    ),
    types.Tool(
        name="expand",
        description=(
            "Depth-bounded traversal from one unit over relationships the record contains "
            "(provenance, topics, contradiction sides, relates_to, aliases). Inferred "
            "same-source/shared-topic adjacency is returned separately as `co_nominated` — "
            "a nomination, never an asserted edge."),
        inputSchema={"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["claim", "contradiction", "entity", "term"]},
            "key": {"type": "string"},
            "depth": {"type": "integer", "default": 1}},
            "required": ["kind", "key"]},
    ),
]


@server.list_tools()
async def list_tools() -> list:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    args = arguments or {}
    try:
        if name == "search_units":
            result = retrieval.search_units(
                ROOT, args["query"], k=int(args.get("k") or 10),
                kinds=args.get("kinds"), match=args.get("match"))
        elif name == "contradictions_for":
            result = retrieval.contradictions_for(ROOT, args["claim_key"])
        elif name == "expand":
            result = retrieval.expand(ROOT, args["kind"], args["key"],
                                      depth=int(args.get("depth") or 1))
        else:
            raise ValueError(f"unknown tool: {name}")
    except SystemExit as e:
        # The library layer refuses loudly (no usable index, no [embed] extra) with
        # SystemExit — right for a CLI, fatal for a server. Serve the refusal in-band:
        # the message already tells the caller exactly what to run.
        return [types.TextContent(type="text", text=str(e))]
    return [types.TextContent(type="text",
                              text=json.dumps(result, indent=2, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
