# bramber — spec 03: first text run (the generality gate)

> Executable build plan for the first **non-code** end-to-end: a competitive-intelligence-style text
> source flows source → extract → view → versioned resource with lineage, through the same
> domain-blind engine the code path uses. Self-contained: a fresh session should be able to
> implement this from specs 00 + 01 + 02 + the existing `bramber/` code + this file.
>
> Prereqs already done: engine lifted (round-trip green); `CodeAdapter` end-to-end (spec 02);
> view-driven selection generalized (`compile.py` reads a `selector` block per view).

**Status:** done — `bramber/adapters/text.py` filled; `tests/test_text_first_run.py` green;
engine untouched. Acceptance gate at the bottom.

---

## Why this spec exists

bramber claims to fit **any** selective-synthesis domain (CLAUDE.md "the bounds"). The code
path (spec 02) proves one domain. The original bramber instance was **text**
(the sibling instance and the predecessor factory): YouTube transcripts, web pages, and docs
→ a synthesized, provenance-tracked overview. This spec is the **falsifiable generality
test**: serve that text domain end-to-end and require **zero edits to `bramber/engine/` or
`bramber/compile.py`**. If the engine must change to add text, the seam was drawn wrong —
fix the seam, not the engine (spec 00 §1, §9).

Text is in fact the *native* case: `schema.sql` was lifted from the predecessor factory (a
text system) and generalized for code, so `content_sha` identity and the `sources.url` /
`source_type` columns are text-first. Proving text is proving the lift didn't break its origin.

---

## Goal

Point bramber at a `_bramber/inbox/` of already-normalized text sources, ingest them through the
`TextAdapter` (content_sha identity, **no units materialized**), author one `market-overview`
view, synthesize a resource from the extracts, and serve it as a versioned resource with
lineage back to the sources.

**Acceptance gate:** `bramber://market-overview/overview` is readable, version 1, with
`resource_lineage` returning every seeded source under `identity_kind='content_sha'` — and
`git diff --stat bramber/engine bramber/compile.py` is **empty**.

---

## Design rules carried from specs 01 + 02

1. **The engine stays domain-blind and never imports an adapter.** Adapter-aware work lives
   in `bramber/ingest.py` (already generic) and the `TextAdapter`. `bramber sync` reconstructs the
   index from on-disk extract headers — the same cheap, stdlib-only parse the code path uses.
2. **Text has no deterministic compile.** Code units are engrams `compile.py` selects via a
   `selector` block. **Text has no engrams.** A text resource is produced by the *agent*
   reading the extract(s) through a `view.md` and writing prose (Mode 2 of `/bramber:process`),
   then calling `db.write_resource_version`. `compile.py`'s selector path is code-only and is
   **not** invoked for text. A text `view.md` therefore has **no** `selector` block.
3. **Fetching is agent-driven.** The engine must stay stdlib-only (the Stop hook runs `bramber
   sync` every turn). So the `TextAdapter` does **no network I/O**: the agent fetches
   (`WebFetch` / `youtube-transcript-api` / `yt-dlp` / `pandoc`), deposits normalized markdown
   in `_bramber/inbox/`, and the adapter only reads / identifies / normalizes those files.

---

## Step 1 — the `TextAdapter` (the ingest half for text)

`bramber/adapters/text.py`, stdlib-only, agent-driven-fetch model. Inbox files carry flat
frontmatter (`source_url`, `source_type`, `title`, `author`, `date_published`) + a markdown body.

- `__init__`: `self._root = None` — remembers the inbox root across `discover → identity →
  normalize` (those receive only a `Source`). Adapter-layer state; the `CodeAdapter` holds
  `repo_root` for the same reason. No Protocol/engine change.
- `discover_sources(root)`: set `self._root`; scan `<root>/_bramber/inbox/*.md`; yield a `Source`
  per file (`source_type`/`title`/`url`/`author`/`date_published` from frontmatter; `ref` =
  filename). Empty if the inbox is absent.
- `identity(source)`: `content_sha` = sha256 of the stripped normalized body (byte-identical to
  `db.sha256`, so a re-sync recomputes the same key) → `SourceIdentity(kind="content_sha", …)`.
- `normalize(source)`: read the inbox file, strip frontmatter, return the `Extract`.
- `extract_units` returns `[]`; `changed` is `prev.key != cur.key`.

`ingest()` is unchanged: `_discover_root` falls back to the data root (TextAdapter has no
`repo_root`), `_slug` = sanitized `ref` + `__` + `identity_key[:8]`, and the header it writes
carries `identity_kind: content_sha`, which `_sync_sources` registers correctly.

```
bramber ingest --adapter text --root <bramber-data-root>   # reads _bramber/inbox, writes _bramber/extracts (+ empty units)
bramber sync   --root <bramber-data-root>                  # index the extracts as sources
```

---

## Step 2 — view + synthesis (`/bramber:process` Mode 2)

Author `views/market-overview/view.md` (the `bramber-plugin/templates/view.md` shape **minus**
the `selector` block — text is not mechanically selected). Then the agent reads the extracts
through the view's Thesis and writes prose `## Current Understanding` / `## Key …` sections,
and calls:

```python
db.write_resource_version("market-overview", "overview", title=..., content=...,
                          change_summary=..., sources=[{extract, digest, contribution} …])
```

`digest` may be `None` for the minimal path (PRF later writes a per-`(source × view)` digest
file and points `digest` at it). Lineage keys on each source's `extract_path`, which `bramber
sync` must have indexed first. The gate (`tests/test_text_first_run.py`) stands in for the
agent with deterministic markdown so it is an automated test.

---

## Acceptance gate (headless, no network, stdlib-only)

`tests/test_text_first_run.py` (**no** `importorskip` — text needs no optional dependency;
the code gate it once mirrored was deleted with the code domain on 2026-07-21):

1. seed 2–3 fake `_bramber/inbox/*.md` (a transcript, an article, a doc) — no network;
2. `ingest(make_adapter("text"), root)` → `n_units == 0` for every source;
3. author `views/market-overview/view.md` (no selector block);
4. `sync` → `views == 1`, `sources == N`;
5. synthesize the resource via `write_resource_version` (the agent stand-in) → v1;
6. re-`sync`, then assert:
   - sources registered, all `identity_kind == 'content_sha'`, `source_type` round-tripped;
   - `views`/`resources` rows exist; exactly version 1;
   - `resource_lineage` returns N sources, all `content_sha`;
   - the `versions/1.md` snapshot exists with `source:` lines and `## Current Understanding`;
   - **idempotence**: re-synthesizing identical content mints no new version.

**The falsifiability proof:** `git diff --stat bramber/engine bramber/compile.py` is empty after
the change — text was served by the unmodified engine.

---

## Notes / non-goals

- **Engine + `compile.py` untouched** (the gate fails the seam if either needs an edit).
- **`TextAdapter` does not fetch** — fetching is agent-driven (WebFetch / yt-dlp / pandoc →
  `_bramber/inbox/`). A network-fetching adapter behind a `bramber[text]` extra is a possible
  future, deliberately not taken here (keeps `pip install bramber` dependency-free for text).
- **Known seam imperfection (ingest-layer, not engine):** `ingest.py`'s extract header omits
  `source_url`/`author`/`date_published`, which `_sync_sources` reads → those `sources` columns
  are NULL for text. A ~3-line ingest-header fix when wanted; the gate asserts only the columns
  the header guarantees (`identity_kind`, `source_type`, `title`, `extract_path`).
- **Follow-ons** (the full sibling-instance rebuild): agent-authored Mode-2 synthesis prose;
  per-`(source × view)` digests; the Mode A/B routing checklist (`routing_decisions` table is
  already in the schema); the browser intake server; migrating the existing sources; `bramber
  stale`. None require an engine change.
