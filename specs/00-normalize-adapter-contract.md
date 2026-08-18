# bramber — spec 00: the Normalize-Adapter Contract

> The single seam a domain implements to use bramber. bramber owns *integrate + serve* (domain-blind). The Adapter owns *normalize + extract* (domain-specific). Everything in this spec is the contract between them.
>
> Companion: `../MentalModeller/docs/factory-core-decision-brief.md` (why bramber exists). Engine ancestor: the predecessor factory (the ~90%-done generalized engine bramber is lifted from).

**Status:** design — fixing the interface before lifting the engine out of the predecessor factory.

---

## 1. The one seam

```
  SOURCE ─►┌──────────────── Adapter (domain) ────────────────┐
           │  discover_sources → normalize → extract_units      │
           │  + source identity (the staleness anchor)          │
           └───────────────────────┬────────────────────────────┘
                                    │  Extract + Units (the handoff)
                                    ▼
           ┌──────────────── bramber (domain-blind) ─────────────┐
           │  digests → resources → versions → lineage          │
           │  bramber.db (index) · MCP server · routing · evaluate │
           └────────────────────────────────────────────────────┘
                                    │
                  agents ◄── MCP ───┤── rendered markdown/HTML ──► humans
```

**Two hard rules that define the seam:**
1. **bramber never parses a source.** It does not fetch, read AST, embed, or interpret raw input. It only stores, versions, indexes, and serves what the Adapter hands it.
2. **The Adapter never writes to `bramber.db`, never writes a resource version, never touches the MCP surface.** It produces `Extract` + `Unit` objects and source identities; bramber persists them.

If either rule is violated, the seam is in the wrong place and bramber is no longer domain-blind. (This mirrors the brief's falsifiable success test.)

---

## 2. Division of responsibility

| Concern | Owner |
|---|---|
| Discover what counts as a source; normalize it; produce units; compute source identity | **Adapter** (code) |
| Persist sources/extracts/digests/resources; version + lineage; rebuild from disk; MCP serve; routing checklist; evaluate loop; staleness scan | **bramber** (engine) |
| Interpretive steps — write a per-(source×view) digest's prose; compile units into a `RESOURCE.md`; propose lens/view & mandate edits | **agent**, guided by `view.md` + bramber's `FORMAT-SPEC` (no domain code) |
| Author the opinionation — `mandate.md`, each `view.md` | **human** (gated; only `/evaluate` edits them) |

The Adapter is the only thing a new domain *writes code for*. The agent-driven interpretive steps are reused from bramber's command + template layer unchanged.

---

## 3. Domain-blind data types

These are bramber's stable types. They mirror the predecessor factory's `engine/schema.sql`, generalized at exactly two points (source identity → §6; units → new).

- **Source** — a raw input. Carries an **identity** (§6), `source_type`, optional title/author/date, and the path to its `Extract`. Dedupe/equality is by identity, not by object.
- **Extract** — the normalized, **view-agnostic** representation of a source. Text: markdown. Code: a symbol record + its source slice. Lens-agnostic and view-agnostic; produced once per source, shared by every view.
- **Unit** *(new generalization)* — the atomic finding extracted from a source. Code: an **engram** `(target, lens)`. Text: a claim / entity / signal. Fields: `kind`, optional `lens` (set for code, null for text), `payload` (domain JSON), and `provenance` (back-pointer into the Extract: file/line range or symbol qname). Units are the shared pool that views project over.
- **View** *(was PRF's "PRF"/"lens")* — an integrate-layer projection. Backed by a human-authored `view.md` (§7). One row in bramber's `views` table (the existing `prfs` table, renamed conceptually; slug is an opaque string so no schema change is required).
- **Digest** — immutable record of one **source × view**: the units selected/produced for that pair plus the agent's compiled reading. Stamped with the `view_version` it was written under, so a later view edit never silently rewrites past meaning.
- **Resource** — the compiled **current** document for a view, integrating its digests. `RESOURCE.md` + `DETAILS.md` + `sources.md`, served over MCP.
- **ResourceVersion** — immutable snapshot of a Resource + its **lineage** (which sources/digests caused it). Append-only. Makes `bramber.db` rebuildable from disk.
- **Mandate** — project-level frame governing which views exist and how sources route. Versioned, human-gated.

> The `runs`, `routing_decisions`, and `evaluations` operational tables from `schema.sql` are bramber's unchanged workflow state. Nothing in §3 is domain-specific except the *contents* of `Extract`/`Unit`/`view.md`.

---

## 4. The Adapter Protocol

Illustrative Python (the package ships this as `bramber.Adapter`). A domain subclasses it; nothing else needs domain code.

```python
from typing import Iterable, Literal, Protocol, runtime_checkable

class SourceIdentity(Protocol):
    """Opaque, comparable, serializable. The staleness anchor (§6)."""
    kind: str                       # "content_sha" | "git_anchored" | ...
    def to_json(self) -> dict: ...

@runtime_checkable
class Adapter(Protocol):
    domain: str                     # "code" | "text" | ...
    # how units come to exist — lets bramber pick the right digest path (§5):
    unit_extraction: Literal["deterministic", "interpretive"]
    extraction_scope: Literal["view_agnostic", "per_view"]

    def discover_sources(self, root: str) -> Iterable["Source"]:
        """Enumerate sources under a project root (files/URLs; or symbols)."""

    def identity(self, source: "Source") -> SourceIdentity:
        """Compute the source's identity. content_sha for text; git+qname+
        extractor_version for code. bramber stores it; diffs drive staleness."""

    def normalize(self, source: "Source") -> "Extract":
        """Raw source → view-agnostic Extract. Runs once per source."""

    def extract_units(self, extract: "Extract",
                      view: "View | None" = None) -> list["Unit"]:
        """Produce units. view is None when extraction_scope == 'view_agnostic'
        (code: emit all engrams once). When 'per_view', called per view."""

    def changed(self, prev: SourceIdentity, cur: SourceIdentity) -> bool:
        """True if the source materially changed (drives `stale` marking).
        Default: prev != cur. Git adapters may scope to commits touching the symbol."""
```

bramber calls `discover_sources → identity → normalize → extract_units`; it then runs its own (domain-blind) digest/resource/version/serve machinery. The agent does the interpretive digest + compile, reading `view.md` + `FORMAT-SPEC`.

---

## 5. Two reference adapters (prove generality)

| | **TextAdapter** (the predecessor factory / a competitive-intelligence instance) | **CodeAdapter** (a code-domain instance) |
|---|---|---|
| `discover_sources` | files in `_orchestrator/inbox/` + URLs | symbols via `mentalmodeller.code_model.SymbolIndex` |
| `identity` | `content_sha` of normalized body (static) | **git-anchored:** `(commit, file_path, qualified_name, EXTRACTOR_VERSION)` |
| `normalize` | fetch/convert → markdown extract | `Symbol` record + source slice (`code_model` + `dep_graph`) |
| `extract_units` | `[]` — text units are derived per view by the agent | **deterministic:** `mentalmodeller.engrams` → engrams `(target, lens)` |
| `unit_extraction` | `interpretive` | `deterministic` |
| `extraction_scope` | `per_view` (agent reads extract through each `view.md`) | `view_agnostic` (engrams emitted once; views select over them) |
| `changed` | `prev != cur` | commit diff touching the symbol/qname |

The CodeAdapter is a **thin wrapper over MM's existing pipeline** (`extract_targets → triviality_filter → attach_lenses → classify_verification → sequence`, `mentalmodeller/engrams.py`). **The engram is the Unit.** It is extracted once, view-agnostically, and never re-derived downstream — satisfying the brief's "no double-extraction" rule.

---

## 6. Source identity & staleness (the code-driven addition)

Text sources are static; code is live. So **source identity is pluggable**, and it is the anchor for staleness and for two-location reconciliation (client perimeter ↔ consulting workspace, per the brief).

- **Identity kinds:** `content_sha` (text — current PRF behavior) and `git_anchored` (code — `commit + file_path + qualified_name + EXTRACTOR_VERSION`). MM already stamps `EXTRACTOR_VERSION` (`engrams.py:38`).
- **Schema delta (the only one bramber needs):** generalize `sources` to carry `identity_kind TEXT` + `identity_json TEXT`; keep `content_sha` as one identity kind for back-compat. Nothing else in `schema.sql` changes.
- **`bramber stale` (new CLI / MCP-free op):** re-run `discover_sources → identity`, diff against stored identities via `adapter.changed`, and mark affected resources `stale` (the schema already has a `stale` status) by walking `version_sources` lineage. Two clones at the same pinned commit reconcile to identical state.

Staleness is a bramber capability driven by Adapter-supplied identity — it is **not** something each domain re-implements.

---

## 7. Views (`view.md`)

A view is authored like PRF's `lens.md` (same shape: thesis, tracked questions, schema, weighting, discard) but named to the integrate layer. For the code-domain instance, the "schema" section is **selection** rather than free interpretation: which unit kinds the view projects.

```markdown
---
name: <View Display Name>
slug: <view-slug>
view_version: <int, bump on human edit>
maintainer: human
---
# <View Display Name>
> Read when compiling the <slug> view. Defines what to project, how to weight it, what to drop.

## Thesis            <the document's point of view>
## Projects          <which units this view selects — for code: which engram lenses / TargetKinds>
## Weighting         <which units/sources carry more>
## Discard           <what not to surface>
```

Starter code views (line up with `06-target-extensions-spec.md` TargetKinds):
- `architecture` — projects composition + `architecture_seam` engrams.
- `api-surface` — projects `surface` engrams of public symbols.
- `domain-glossary` — projects `domain_concept` engrams.
- `patterns` — projects `pattern_instance` engrams.

`view_version` is recorded in every digest (as `lens_version` is today), so view edits stay prospective.

---

## 8. Packaging

```
bramber/                      # pip package — the reusable core
  bramber/
    engine/  db.py  server.py  schema.sql   # lifted from the predecessor factory
    adapter.py                              # Adapter Protocol + SourceIdentity + base types
    adapters/                               # optional reference adapters (extras)
      text.py                               #   from the predecessor factory's behavior
      code.py                               #   wraps `mentalmodeller` (extra: bramber[code])
    cli.py                                  # bramber init | serve | sync | stale
  pyproject.toml                            # entry points: bramber.server (MCP), bramber (CLI)

bramber-plugin/               # thin Claude Code plugin — depends on bramber
  .claude-plugin/plugin.json
  .mcp.json                 # launches `python -m bramber.server` (PRF's server, unchanged)
  commands/                 # init, intake, orchestrate, process, evaluate, consistency, new-view
  templates/                # mandate.md, view.md starter
  hooks/hooks.json          # Stop hook → bramber sync
```

**An instance is data + a chosen Adapter:**
- `pip install bramber[code]` → use the bundled `CodeAdapter` (needs `mentalmodeller` on path), or `pip install bramber` and supply your own.
- author `view.md` files; run `bramber init`; install `bramber-plugin` for the slash-command UX.
- the MCP server (`bramber.server`) and schema are reused **unchanged** across all instances — that reuse is the whole point.

---

## 9. Invariants (the contract's guarantees)

1. bramber never parses a source; the Adapter never writes `bramber.db`/resources/MCP (§1).
2. The Unit (engram) is the handoff; it is never re-derived downstream (§5).
3. Disk is the source of truth; `bramber.db` is rebuildable; every version is snapshotted with lineage (`schema.sql` design decision 2).
4. Views and the mandate are human-gated; only `/evaluate` edits them; changes are prospective (`view_version` stamped on digests).
5. Source identity is the staleness anchor; staleness is a bramber op driven by Adapter identity, not per-domain code (§6).
6. Serving is local, portable, per-clone (no central host); agents read the MCP, humans read the rendered tree (brief §7).

---

## 10. Deferred / out of scope (pointers, not designs)

- **RAG retrieval** (n8nRAGKit): plugs in at two points — behind `search_resources` and in front of the integrate selection step (brief §6). In-perimeter clients may forbid code egress, so the Voyage/Cohere/Anthropic stack needs sign-off or local models. Deferred until the integrate step strains.
- **Sibling-instance migration** onto bramber: opportunistic; it works as a frozen single-view reference until touched.
- **Concurrent in-perimeter consumers** (a shared local bramber service vs per-developer stdio): a scaling question, not a v1 one.

---

## Next spec

`01-engine-lift.md` (not yet written): the mechanical plan to move the predecessor factory's `engine/*`, `docs/*`, `commands/*`, and plugin scaffolding into this layout, generalize the `sources` identity columns (§6), and keep `tests/test_roundtrip.py` green throughout.
