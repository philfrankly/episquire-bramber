"""Module entry point so `python -m bramber.server` launches the MCP server.

Thin shim over bramber.engine.server (keeps the .mcp.json command stable even if the
engine module layout changes). Requires the `mcp` extra: pip install bramber-engine[mcp].
"""

import asyncio

from bramber.engine.server import main

if __name__ == "__main__":
    asyncio.run(main())
