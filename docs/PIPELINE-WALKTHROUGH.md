# bramber — code execution walkthrough

**What this is:** the actual order of execution for one run, what does the iteration at each
step, and what the data looks like on disk between steps. Every artifact quoted below was
produced by running the real pipeline (the 2026-08-07 scan pipeline, `specs/09`) over a
2-source, 2-view fixture — nothing here is illustrative JSON written by hand.

**What this is not:** the conceptual explainer. `README.md` answers *why* the pipeline is
shaped this way. This document answers *what executes, in what order, over what*.

---

## 0. The one structural fact that makes tracing hard

**A run is not one process.** It is four separate process invocations plus one step that is not
code at all, with the filesystem as the only thing connecting them:

```
  bramber ingest        process 1   ─┐
  bramber sync          process 2    │  no shared memory, no call stack,
  (agent writes scans)    ← no code  │  no return values between these
  bramber materialize   process 3    │
  bramber compile       process 4   ─┘   ← per view; the only per-view step, and re-runnable
```

No debugger session spans that. There is no function that calls ingest and then calls compile.
Every arrow in the pipeline is a **file written by one process and read by another**, which is
why the project instructions' invariant 3 ("disk is the source of truth") is not an aspiration — it is a
description of the only mechanism available.

The practical consequence for tracing: **you can start anywhere.** Every phase boundary is a
directory you can `cat`. You never need to reconstruct upstream state in a debugger, because
upstream state is sitting on disk in its final form.

Note the bracket around the first four steps versus the last: everything through `materialize`
is **corpus work, done once per source**. `compile` is **view work, done as often as you like**
— it reads only `_bramber/units/` and one `view.md`, so a new view or an edited view is a
recompile, never a re-read.

### The one place the whole pipeline runs in a single process

`tests/test_scan.py` — `test_full_pipeline_ingest_scan_materialize_compile`. It calls
`ingest()` → writes scan files → `materialize()` → `sync_from_disk()` → `compile_view()` in
one Python process against a `tmp_path` root, with the agent's step stood in by a literal
markdown string. Its sibling `test_a_second_view_costs_no_second_scan` is the product claim as
code: it byte-compares the scans before and after adding and compiling a second view.

## 1. The fixture this document is traced against

Two inbox sources and two views:

- `acme-earnings-call.md` (transcript) — revenue grew 22%; guidance up; "the platform
  migration is on schedule" (the CFO's own claim).
- `widget-market-report.md` (article) — three vendors hold 70%; independently repeats the 22%
  revenue claim; integrators doubt the migration schedule.
- `views/market-overview/view.md` — selector `match.topics: revenue, market-structure`.
- `views/risk-register/view.md` — selector `match.topics: schedule-risk`.

The interesting structure is deliberate: one claim asserted by **both** sources
(corroboration), one pair of claims that **contradict** (assurance vs doubt about the same
schedule), and two views whose selections **overlap nowhere** — yet both are compiled from the
same store, produced by the same two scans.

## 2. Stage 0 — process start, every command

Every `bramber <cmd>` enters `bramber/cli.py:main`, which calls `db.configure(root, db)` —
resolving `$BRAMBER_ROOT`/`--root` into the module-level paths (`ROOT`, `DB_PATH`, `EXTRACTS`,
`VIEWS_DIR`) everything else reads. The engine (`bramber/engine/`) is stdlib-only; commands
import their heavier collaborators lazily inside their own branch, so `bramber sync` (the Stop
hook, every turn) never pays for — or fails on — anything it doesn't use.

## 3. Stage 1 — `bramber ingest`

`bramber.ingest.ingest(adapter, root)` drives the Adapter Protocol over every discovered
source: `discover_sources → identity → normalize → extract_units`, then materializes each
result to disk. For text, `extract_units` returns `[]` — extraction is interpretive, so it
happens at scan time (stage 5), not here.

Two files per source come out:

`_bramber/extracts/acme_earnings_call_md__8fd49ca7.md` — the normalized body under the
generalized header (`bramber/engine/header.py` declares the key set once; ingest renders
through it, `db._sync_sources` reads through it, and `render()` raises on drift):

```yaml
---
identity_kind: content_sha
identity_key: 8fd49ca73e97e525999d831834a4b8027946c944fb51f1f35ed2485c725f2bce
identity_json: {"ref": "acme-earnings-call.md"}
source_type: transcript
title: "Acme Q3 Earnings Call"
source_url: https://www.youtube.com/watch?v=fake-acme-q3
author: Acme IR
date_published: 2026-05-01
date_ingested: 2026-08-07
---
```

…and `_bramber/units/acme_earnings_call_md__8fd49ca7.json`, which at this stage declares its
own emptiness rather than faking work: `"units": null` plus a `units_absent_reason` naming
`TextAdapter.extract_units` as the method responsible. The filename stem —
`<sanitized-ref>__<first 8 of identity_key>` — is the slug every later artifact keys on.

## 4. Stage 2 — `bramber sync`

`db.sync_from_disk` reconstructs the index from disk in three sub-syncs — `_sync_views`
(one row per `views/*/view.md`), `_sync_sources` (one row per extract, read through the shared
header declaration), `_sync_resources` (versions + lineage from the snapshots). No adapter
import, no source parsing — a cheap stdlib pass, which is what lets the Stop hook run it every
turn. After this stage: `views=2, sources=2, resources=0`.

## 5. Stage 3 — the agent writes scans (no code executes)

The one handwritten artifact, and the only interpretive step in the corpus half. One file per
source, named for its extract, in `_bramber/scans/`. Before writing each one the agent runs
`bramber claims --root <root>` — the corpus-global mint-or-reuse feed. When the second scan
was written, the feed already showed CLAIM-001..003 from the first, which is how the market
report's scan knew to **reuse** CLAIM-001 rather than mint a near-duplicate:

```markdown
---
source: _bramber/extracts/widget_market_report_md__013689e4.md
scan_date: 2026-08-07
discarded: false
---

## Claims

- **CLAIM-004** — Three vendors hold 70% of the widget market.
  - evidence: strong
  - recency: 2026-04-18
  - topics: market-structure
- **CLAIM-001** — Acme revenue grew 22% year over year, driven by the agents product line.
  - evidence: moderate
  - recency: 2026-04-18
  - topics: revenue
- **CLAIM-005** — The platform migration will not hold its schedule.
  - evidence: speculative
  - recency: 2026-04-18
  - topics: schedule-risk

## Contradictions
CLAIM-005 contests CLAIM-003 (the migration is on schedule) — first-party assurance versus
integrators' doubt; neither side is retracted.

## Notes
Reused CLAIM-001 from the earnings-call scan: same assertion, independently made.
```

Three disciplines visible in that one file: **reuse records corroboration** (CLAIM-001);
**disagreement never shares a key** (CLAIM-005 contests CLAIM-003 and gets its own key — dedup
may collapse restatement, never disagreement); and **grading, not hedging** (the doubt is
admissible, marked `speculative`). No view is mentioned anywhere — the scan does not know the
risk register exists.

## 6. Stage 4 — `bramber materialize`

`bramber.ingest.materialize(root)` — always corpus-wide; there is no scope flag, by design (a
scoped rewrite of a shared store is how the pre-redesign version silently truncated it). It
reads every scan through the one reader (`bramber/scan.py`), groups by `source:`, and rewrites
every extract's units envelope from scratch — units are derived data; merging would let a
deleted claim survive forever.

**The collapse — half of the product — happens here**: `scan.units_for_source` keys by
`claim_key` within one source, so a source restating a claim five times contributes one unit.
The other half deliberately does *not* happen here (see stage 7). What lands on disk:

```json
{
  "kind": "claim",
  "payload": {
    "claim_key": "CLAIM-001",
    "statement": "Acme revenue grew 22% year over year, driven by the agents product line.",
    "evidence_strength": "strong",
    "recency": "2026-05-01",
    "topics": ["revenue"]
  },
  "provenance": {
    "source_artifacts": [
      {
        "extract_path": "_bramber/extracts/acme_earnings_call_md__8fd49ca7.md",
        "scan_path": "_bramber/scans/acme_earnings_call_md__8fd49ca7.md",
        "reliability_tier": "reported"
      }
    ]
  }
}
```

`source_artifacts` is a **list even at length one** — the shape that lets a claim gain
corroborating sources at selection without a schema break. `reliability_tier` comes from a
fixed table keyed by source class, never from how convincing the text sounds. Output for this
fixture: `materialized 6 unit(s) across 2 source(s)` — 3 + 3, with the corroboration not yet
merged, because "what did THIS source assert" is the envelope's whole meaning.

## 7. Stage 5 — `bramber compile --view <slug>` (× as many views as you like)

`compile.compile_view` syncs, reads the view's ```` ```selector ```` block
(`parse_selector` — `dedup_by`/`order_by`/`project` required, no defaults, loud failure), then
runs the one selection pass, `select_units`, over every envelope in `_bramber/units/`.

**Selection predicates:** `kind`, plus `match.<field>` over any payload field — exact for
scalars, **any-of for list-valued fields**, which is what makes `match.topics: revenue,
market-structure` work against `topics: ["revenue"]`. A rejected unit gets its reason recorded
(`--trace` shows every considered unit and the predicate that killed it).

**The count — the other half of the product — happens here.** When the widget report's
CLAIM-001 arrives and the key is already selected from the earnings call, the artifacts
**merge**: support becomes 2, and the floor is `min()` over both tiers. Across sources bramber
counts; it never collapses. The rendered bullet carries both numbers:

```markdown
## Claims
- **Acme revenue grew 22% year over year, driven by the agents product line.** — evidence_strength: strong  _(2 sources · floor: reported)_
- **Management guided to accelerating enterprise adoption into Q4.** — evidence_strength: moderate  _(1 source · floor: reported)_
- **Three vendors hold 70% of the widget market.** — evidence_strength: strong  _(1 source · floor: reported)_
```

The risk register — compiled seconds later, **from the same store, with zero additional
corpus work** — selects a disjoint set, and the contradiction pair surfaces side by side,
unmerged, each citing its own side:

```markdown
## Risks
- **The platform migration is on schedule.** — evidence_strength: moderate · recency: 2026-05-01  _(1 source · floor: reported)_
- **The platform migration will not hold its schedule.** — evidence_strength: speculative · recency: 2026-04-18  _(1 source · floor: reported)_
```

`write_resource_version` then mints version 1 of each resource: `RESOURCE.md`, an immutable
snapshot, and one lineage row per (unit × contributing source). The snapshot's `source:`
pipe-triples are the on-disk form of the lineage graph — note CLAIM-001 earns **two** rows,
one per corroborating source:

```
source: _bramber/extracts/acme_earnings_call_md__8fd49ca7.md | _bramber/scans/acme_earnings_call_md__8fd49ca7.md | CLAIM-001
source: _bramber/extracts/widget_market_report_md__013689e4.md | _bramber/scans/widget_market_report_md__013689e4.md | CLAIM-001
source: _bramber/extracts/acme_earnings_call_md__8fd49ca7.md | _bramber/scans/acme_earnings_call_md__8fd49ca7.md | CLAIM-002
source: _bramber/extracts/widget_market_report_md__013689e4.md | _bramber/scans/widget_market_report_md__013689e4.md | CLAIM-004
```

Because those triples live in the snapshot on disk, deleting `bramber.db` and running
`bramber rebuild` reconstructs every lineage edge — invariant 3, exercised for real in
`tests/test_scan.py::test_claims_and_support_survive_a_db_delete_and_rebuild`.

Re-running `compile` with nothing changed is a content-sha no-op: no version 2, no churn. The
agent-authored path (`/bramber:process` Mode 2) replaces the deterministic render with prose
but consumes the **same** `select_units` output via `bramber select`, so the baseline and the
authored document can never disagree about what the view projects.

## 8. What `bramber status` derives at the end

```
bramber status — <root>
  inbox: 2 deposit(s), 2 ingested, 0 pending ingest, 0 link(s) to fetch
  sources indexed: 2
  scans: 2/2 (0 failed, 0 discarded)
  view market-overview: resources 1 (1 versioned)
  view risk-register: resources 1 (1 versioned)
```

All derived from disk (`bramber/run.py`), nothing stored: a source is ingested iff its extract
exists, scanned iff a scan names its extract, and a view's state is just its resources. The
advisory run-log (`_bramber/runs/*.jsonl`) overlays one distinction disk cannot make —
attempted-and-failed versus never-reached — and deleting it changes no count.

## 9. The costs, located

| Step | Cost | Cadence |
|---|---|---|
| normalize + ingest | cheap model + mechanical | once per source |
| **scan** | **the interpretive spend** | **once per source — never per view** |
| materialize | mechanical | corpus-wide, idempotent |
| compile / select | mechanical | per view, as often as wanted |
| author (Mode 2) | model, bounded by the selection | per resource, when prose is wanted |

The row in bold is the redesign (`specs/09`,
the 2026-08-07 ruling *view agnostic claims compiler only*): extraction is O(sources), and a
view — added, edited, or re-ruled — costs a recompile over data already on disk.
