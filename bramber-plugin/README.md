# bramber-plugin

The Claude Code surface for **bramber** — the slash commands, the protocol docs, the MCP server
declaration, and a Stop hook that keeps your document index in sync. The plugin is thin; the
actual engine ships as the `bramber` Python package.

## What's in here

- **`commands/`** — the `/bramber:*` slash commands you run (`orchestrate`, `process`, and the
  helper commands). See [`commands/README.md`](commands/README.md) for what each one does.
- **`docs/`** — `ORCHESTRATOR.md` (the protocol contract) and `FORMAT-SPEC.md` (the exact
  templates for extracts, scans, resources, snapshots, and reports). Every command reads these.
- **`.mcp.json`** — declares the read-only `bramber` MCP server so Claude can query your compiled
  documents. Points at your current project folder.
- **`hooks/hooks.json`** — a Stop hook that re-indexes your documents from disk after every turn,
  so the index never drifts from what's on disk.
- **`templates/`** — the starter `view.md` (including the `selector` block every view needs) and
  a library of genre starters, copied in by `/bramber:init` and `/bramber:new-view`.

## Requirements

The plugin needs the `bramber` Python package importable by the Python that Claude Code launches:

```bash
pip install -e .          # from the repo root, during development
# or, once published:  pip install bramber-engine[mcp]
```

The MCP server and the sync hook register automatically the moment the plugin is enabled — no
extra configuration. Load the plugin for a session with `claude --plugin-dir ./bramber-plugin`, or
install it persistently via Claude Code's plugin marketplace.

## How the pieces sit

Your project holds only *your* data — `views/<slug>/`, the `_bramber/` working folder (inbox,
extracts, scans, the derived unit store), and the derived (throwaway) `bramber.db`. The engine
lives in the package, not in your project. That separation is deliberate: the engine never needs
to know what your sources are. Each source is read once — normalized, then scanned for its
claims — and every view is a cheap, re-runnable projection over that shared store.
