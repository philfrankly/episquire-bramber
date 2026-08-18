# foinse — spec 02: first code-domain run (ingest hook + first view)

> ## ⚠ SUPERSEDED 2026-07-21 — historical record, do not implement
>
> The code domain this spec builds was **withdrawn**: `CodeAdapter` and the `mentalmodeller`
> dependency are deleted, and so are the two views this spec's acceptance gate compiles.
> → the 2026-07-21 ruling *excise code adapter preserve code use case*
>
> Kept rather than deleted because `specs/00` and `specs/03` cite it, and because it is the
> record of how the seam was first proven end-to-end — which is the part that survived. Its
> successor is `specs/07-text-units-and-code-excision.md`.
>
> **File references below point at files that no longer exist.** That is expected of a
> superseded document and is why the reference-resolution guard skips it.

> Executable build plan for the two steps that produce the first engram-backed,
> MCP-served document from a real repo. Self-contained: a fresh session should be
> able to implement this from specs 00 + 01 + the existing `foinse/` code + this file.
>
> Prereqs already done (commits b79dddb, bcb018f): engine lifted, round-trip green;
> `CodeAdapter` wired and verified against the MentalModeller repo (210 symbols;
> `build_graph` → 6 engrams). See `specs/00` (the Adapter contract) and `specs/01`
> (the lift + the generalized extract header).

**Status:** plan. Acceptance gate at the bottom; implement until it passes.

---

## Goal

A headless end-to-end: point foinse at the MentalModeller repo, ingest its symbols
through the `CodeAdapter`, compile one **view** over the resulting engrams, and serve
the result as a versioned resource with lineage back to the source symbols. This proves
the brief's two-half composition (MM = normalize/extract; foinse = integrate/serve) all
the way to an MCP-readable document.

**Acceptance gate:** `foinse://api-surface/overview` is readable, version 1, with
`resource_lineage` returning ≥1 source — produced from real engrams, no engine edits.

---

## Design rule carried from spec 01

The **engine stays domain-blind and never imports an adapter.** All adapter-aware work
lives in two new modules outside `foinse/engine/`:
- `foinse/ingest.py` — runs an adapter, materializes extracts + units to disk.
- `foinse/compile.py` — projects units through a view into a RESOURCE.md (no adapter import).

`foinse/engine/db.py --sync` then indexes the on-disk artifacts exactly as today.

---

## Step 1 — the ingest hook (`/foinse:orchestrate` for code)

### 1a. `foinse/ingest.py`

```python
def ingest(adapter, data_root, *, run_id=None) -> list[dict]:
    """discover -> identity -> normalize -> extract_units for every source;
    materialize each to <data_root>/_foinse/extracts/<slug>.md (+ units json).
    Returns a manifest: [{slug, qname, extract_path, units_path, n_units}]."""
```

For each `Source` the adapter yields:
- `ident = adapter.identity(src)`, `ext = adapter.normalize(src)`, `units = adapter.extract_units(ext)`
- `slug = re.sub(r"[^0-9A-Za-z]+","_", src.ref).strip("_") + "__" + ident.key[:8]`
- write `_foinse/extracts/<slug>.md` with the **generalized header** (spec 01 §4), one line per key (flat frontmatter; `db.split_frontmatter` parses it):
  ```
  ---
  identity_kind: <ident.kind>
  identity_key: <ident.key>
  identity_json: <json.dumps(ident.data)>   # single line; contains ':' — fine, partition splits once
  source_type: <src.source_type>
  title: "<src.title>"
  date_ingested: <YYYY-MM-DD>
  ---
  <ext.body>
  ```
- write `_foinse/units/<slug>.json`: `{"extract_path": "_foinse/extracts/<slug>.md", "qname": src.ref, "units": [asdict(u) for u in units]}`

Skip writing an extract when `units` is empty AND `ext.body` is trivial? No — write all; the
view selection decides what surfaces. (Empty-engram symbols still register as sources, which
is correct: they were considered.)

### 1b. adapter registry + CLI

Add to `foinse/ingest.py`:
```python
def make_adapter(name, *, repo):     # "code" -> CodeAdapter(repo); "text" -> TextAdapter()
```
Add a `foinse ingest` subcommand to `foinse/cli.py`:
```
foinse ingest --adapter code --repo <code-repo> --root <foinse-data-root>
```
`--repo` is the code being documented (defaults to `--root`). It calls `db.configure(root=...)`
only for path resolution; ingest itself doesn't touch the DB (the Stop hook / `foinse sync` does).

### 1c. `/foinse:orchestrate` command body (code path)

Port the predecessor factory's `commands/orchestrate.md` with one substantive change: instead of
the text fetch→markdown step, it runs `foinse ingest --adapter code`. **Code routing note:** with
hundreds of symbols, the per-(source×view) checklist from PRF is the wrong granularity. For
the code domain, routing is *view-centric*: the operator picks which views to compile (every symbol
feeds every applicable view; the view's `Projects` rule does the selection). Skip the per-source
routing checklist for the `code` domain; document this divergence in the command.

---

## Step 2 — first view + compile (`/foinse:process`)

### 2a. Author `views/api-surface/view.md`

Use the `foinse-plugin/templates/view.md` shape. Selection rule (the `Projects` section) for the
first view, kept mechanical so it's testable:

> **Projects:** `surface`-lens engrams whose target is a *public* symbol — the last
> dotted segment of `qualified_name` does not start with `_`. One bullet per symbol,
> ordered by qualified name.

### 2b. `foinse/compile.py`

```python
def compile_view(data_root, view_slug, *, resource_slug="overview") -> dict:
    """Load _foinse/units/*.json, apply the view's selection, write a RESOURCE.md via
    db.write_resource_version with lineage. Returns the writer result."""
```
- Load every `_foinse/units/*.json`.
- Apply selection (v1: hardcode the api-surface rule above; later read it from `view.md`).
  Dedup selected engrams by `payload["engram_id"]` (spec: the engram id is the dedup key).
- Build a deterministic RESOURCE.md body (frontmatter per `FORMAT-SPEC` RESOURCE.md + a
  "## Public surface" section: one bullet `- `qname` — <rationale> (`file:line`)` per engram).
- Lineage `sources=[{"extract": <units.extract_path>, "digest": <units_path>,
  "contribution": <engram_id>}]` — one per contributing symbol. `db._link_source` keys on
  `extract_path`, so the extract must already be synced (run `foinse sync` before compile, or
  call `db.sync_from_disk` inside compile before writing).
- Call `db.write_resource_version(view_slug, resource_slug, title="API Surface", content=...,
  change_summary="initial compile", sources=...)`.

Add `foinse compile --view <slug> --root <data-root>` to the CLI.

### 2c. `/foinse:process` command body

Port the predecessor factory's `commands/process-prf.md` → `process.md`. Two modes:
- **deterministic baseline** (what `foinse compile` does) — the acceptance-test path.
- **agent-authored** (the real product) — the agent reads the selected engrams + the view
  thesis and writes prose `Current Understanding` / `Key surface` sections, then calls
  `write_resource_version`. This is where the document becomes good; the baseline just proves
  the pipe.

---

## Acceptance gate (headless, on the MentalModeller repo)

```bash
# from a throwaway foinse data root TMP, with foinse + mentalmodeller importable
foinse ingest  --adapter code --repo C:/Code/MentalModeller --root TMP   # writes _foinse/extracts + _foinse/units
mkdir -p TMP/views/api-surface && cp .../view.md TMP/views/api-surface/  # author the view
foinse sync    --root TMP                                                 # index the extracts (sources)
foinse compile --view api-surface --root TMP                              # writes RESOURCE.md v1 + lineage
foinse sync    --root TMP                                                 # re-index the new resource/version
```
Assert (via `db` or sqlite):
- `views` has `api-surface`; `resources` has `api-surface/overview`; `resource_versions` has v1.
- `resource_lineage("api-surface","overview")` returns ≥1 source.
- the snapshot `TMP/views/api-surface/resources/overview/versions/1.md` exists with `source:` lines.
- (optional, `pip install -e .[mcp]`) the MCP server reads `foinse://api-surface/overview`.

Write this as the *test_first_run* record (mirrors `tests/test_roundtrip.py`'s tmp-dir style; it
may import `mentalmodeller`, so guard with `pytest.importorskip("mentalmodeller")`).

---

## Notes / non-goals

- Engine untouched (gate fails if `engine/` needs edits — the seam was drawn wrong).
- `TextAdapter` still a stub; not needed for this gate.
- Per-module resources, richer views (`architecture`, `domain-glossary`, `patterns`), agent-authored
  prose, and `foinse stale` are follow-ons. This spec is the minimal real end-to-end.
