# bramber — spec 01: the Engine Lift

> The mechanical plan to move the predecessor factory's `engine/*` + `docs/*` + `commands/*` + plugin scaffolding into the bramber package/plugin layout, generalize the two domain-specific points, and keep the round-trip invariant green throughout.
>
> Reads on: `00-normalize-adapter-contract.md` (the seam) and the brief. Source of the lift: the predecessor factory.

**Status:** plan. The scaffold (`bramber/` package + `bramber-plugin/`) implements this spec.

---

## 1. The invariant the lift must not break

The predecessor factory's `tests/test_roundtrip.py` asserts the load-bearing property: **write a resource version with source lineage, delete the DB, rebuild from the `.md` tree alone — the lineage returns identical.** This is "losing the DB is a non-event." Every step below keeps a ported version of this test green. The lift is done when the ported test passes against the bramber package.

---

## 2. Canonical renames (PRF → bramber)

bramber is a fresh package, so it adopts the decided vocabulary outright. One consistent rename table, applied everywhere (schema, `db.py`, `server.py`, test, templates, commands):

| PRF | bramber | Notes |
|---|---|---|
| `prf.db` | `bramber.db` | the derived index |
| `$PRF_ROOT` / `$PRF_DB` | `$BRAMBER_ROOT` / `$BRAMBER_DB` | env, set by `.mcp.json` / hook |
| `_orchestrator/` | `_bramber/` | working tree (inbox, extracts, routing) |
| `prfs/<slug>/` | `views/<slug>/` | the per-view tree |
| `lens.md` (the PRF perspective) | `view.md` | **integrate-layer** rename (per the contract) |
| table `prfs` | table `views` | columns: `slug, name, view_path` |
| `resources.prf_id` | `resources.view_id` | FK rename |
| MCP `prf://<prf>/<res>` | `bramber://<view>/<res>` | URIs |
| MCP tool `list_prfs` | `list_views` | tool rename |

**Not renamed:** "lens" stays the word for the *extract-layer cognitive angle* — it appears only inside a code adapter's engram payloads, never in the engine. The engine has no concept named "lens" after the lift; it has `views`.

---

## 3. What moves essentially verbatim

These carry over with only the §2 renames — no logic change:

- **`engine/server.py`** → `bramber/engine/server.py`. Read-only MCP server. Rename env (`BRAMBER_*`), URIs (`bramber://`), table (`views`), tool (`list_views`), and the `prfs`→`views` joins. Logic unchanged.
- **`engine/schema.sql`** → `bramber/engine/schema.sql`. Knowledge tables (`resources`, `resource_versions`, `version_sources`, `mandate_versions`) and operational tables (`runs`, `routing_decisions`, `evaluations`) are domain-blind — carry over with the `prfs`→`views` rename. Only `sources` changes (§4).
- **`db.py` writers** (`write_resource_version`, `_insert_version`, `_link_source`, `_refresh_current`, `_snapshot_text`, `add_run`, `upsert_*`) — carry over; stdlib-only preserved (the Stop hook must never fail on a missing dep).
- **The predecessor factory's ORCHESTRATOR and FORMAT-SPEC docs** → `bramber-plugin/docs/`. Apply renames; the extract/digest/RESOURCE/DETAILS/sources/version-snapshot/routing templates are unchanged in shape. FORMAT-SPEC gains the generalized **extract header** (§4) and the **view.md** template (replacing lens.md).
- **`commands/*.md`** (init, intake, orchestrate, process-prf→`process`, evaluate, consistency-pass, new-prf→`new-view`) → `bramber-plugin/commands/`. Apply renames; protocol unchanged.
- **plugin scaffolding** (`plugin.json`, `.mcp.json`, `hooks/hooks.json`) → `bramber-plugin/`. Repoint at the bramber package and `BRAMBER_*` env (§6).

---

## 4. Generalization G1+G2 — source identity & domain-blind sync

This is the only real engineering in the lift. Today `db.py` is text-bound in exactly two places, both in the disk→index path:

- `_sync_sources` globs `_orchestrator/extracts/*.md` and computes identity as `content_sha = sha256(body)`.
- `upsert_source` / the `sources` table key on `content_sha`.

**Design rule that keeps `--sync` fast and domain-blind:** the engine never imports an Adapter. The Adapter runs at **ingest time** (the `/orchestrate` command) and *materializes its extracts to disk* with a standard header. `--sync` (run by the Stop hook every turn) only reconstructs the index from those on-disk headers — a cheap parse, no AST walk, no fetch. So the expensive adapter work happens once per ingest; sync stays stdlib-only and oblivious to the domain.

**Generalized extract header** (what every adapter writes; `db.py` parses it):

```yaml
---
identity_kind: content_sha | git_anchored        # default content_sha if absent
identity_key:  <stable dedupe hash>              # sha256(body) for text; sha256(canonical tuple) for code
identity_json: {"commit": "...", "path": "...", "qname": "...", "extractor_version": "..."}   # optional, code
source_type:   <domain string>
title:         "<...>"
# (text adapters keep source_url/author/date_published; ignored generically)
---
<normalized body>
```

**Schema delta to `sources`** (the only schema change beyond renames):

```sql
sources(
  ...,
  identity_kind TEXT NOT NULL DEFAULT 'content_sha',
  identity_key  TEXT NOT NULL,        -- the dedupe key (was content_sha)
  identity_json TEXT,                  -- structured identity for git-anchored, else NULL
  UNIQUE(identity_key)
)
```

`content_sha` is dropped in favour of `identity_key` (same role, kind-agnostic name). **Back-compat:** when `_sync_sources` reads a legacy text extract with no `identity_*` header, it defaults `identity_kind='content_sha'`, `identity_key=sha256(body)` — i.e. byte-for-byte the old behaviour, so the ported text round-trip test passes unchanged.

`upsert_source` gains `identity_kind` / `identity_json` params; `_link_source` keys lineage on `identity_key`/`extract_path` exactly as before.

## 5. Generalization G3 — `view.md` (accept both)

`_sync_views` (was `_sync_prfs`) reads `views/<slug>/view.md`. For migration tolerance it accepts `lens.md` as a fallback filename, preferring `view.md`. Name is taken from `name:`/`title:` frontmatter or the first `# ` heading, as today.

---

## 6. Packaging wiring

- **`pyproject.toml`** — package `bramber`; console entry `bramber = bramber.cli:main`; MCP entry runnable as `python -m bramber.server`. Core deps: none (engine is stdlib). Extras: `bramber[mcp]` → `mcp>=1.2`; `bramber[code]` → `mentalmodeller`.
- **`bramber-plugin/.mcp.json`** — launches `python -m bramber.server` with `BRAMBER_DB=${CLAUDE_PROJECT_DIR}/bramber.db`, `BRAMBER_ROOT=${CLAUDE_PROJECT_DIR}`. (Requires `bramber` importable on the plugin's Python — documented in the plugin README.)
- **`bramber-plugin/hooks/hooks.json`** — Stop hook runs `python -m bramber.cli sync --root ${CLAUDE_PROJECT_DIR}` (was `db.py --sync`).

---

## 7. Ordered steps (each keeps the test green)

1. **schema.sql** → port with `prfs`→`views` rename + the `sources` identity delta (§4).
2. **db.py** → port: `configure()` env rename + `_bramber`/`views` paths; `_sync_sources` reads the generalized header with content_sha fallback; `_sync_prfs`→`_sync_views` reads `view.md`|`lens.md`; writers carry over.
3. **test_roundtrip.py** → port to bramber names (`_bramber/extracts`, `views/<slug>/view.md`, `bramber.db`, `db.configure`), seeding a legacy-style text extract (no identity header) to prove back-compat. **Run it — must pass.** This is the lift's acceptance gate.
4. **server.py** → port with renames (untested at scaffold time: needs `bramber[mcp]`; smoke-test once the dep is installed).
5. **adapter.py** → the Protocol + base dataclasses (`Source`, `Extract`, `Unit`, `SourceIdentity`) per the contract.
6. **docs/commands/templates/plugin** → port with renames; add the `view.md` template + generalized extract header to FORMAT-SPEC.

---

## 8. Verification

- `cd bramber && python -m pytest tests/` (or `python tests/test_roundtrip.py`) → lineage survives rebuild. **The gate.**
- `python -m bramber.cli sync --root <seeded tmp>` → prints table counts, no error.
- (after `pip install -e bramber[mcp]`) the plugin's MCP server starts and `list_views` returns the seeded view.

---

## 9. Explicitly NOT in the lift

- Adapter *domain logic* — `TextAdapter` (port PRF's fetch→markdown normalize) and `CodeAdapter` (wrap `mentalmodeller`) are scaffolded as stubs against the Protocol; filling them is later work.
- The `bramber stale` staleness scan (contract §6) — its hook point is reserved in the CLI; implementation follows the first git-anchored adapter.
- RAG retrieval, sibling-instance migration (contract §10).
