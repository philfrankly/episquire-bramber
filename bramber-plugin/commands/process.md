---
description: Compile one view over the shared claim store into a versioned document with lineage. Two modes — a deterministic baseline (`bramber compile`) and an agent-authored path that reads the selected units plus the view's thesis and writes real prose. Reads no sources; cheap to re-run. Usage: /bramber:process <view-slug> | --all
---

You are the view agent. This command runs the **view half** of a bramber run: it projects the
shared unit store through one view's selector and mints a new versioned `RESOURCE.md` with
lineage back to the sources that fed it. **It reads no sources and writes no scans** — the
corpus half (`/bramber:orchestrate`) already did `ingest → scan → materialize`. Because of
that, this command is cheap and re-runnable: a view can be compiled, edited (via
`/bramber:evaluate`), and compiled again without touching the corpus.

- **`/bramber:process <view-slug>`** — process that one view (e.g. `/bramber:process market-overview`).
- **`/bramber:process --all`** — process every view, alphabetically. Skip views with nothing to
  project.

If no argument is given, list the views and ask which to run. Don't guess.

**Model tiers** (`${CLAUDE_PLUGIN_ROOT}/docs/ORCHESTRATOR.md` § Model tiers): **author** and
**overview** at the *default* tier; the **carve** (deriving a view's resource set, when
integration invents new resources) at the *premium* tier. Tiers resolve to models via the
operator's rubric; name tiers, not models.

**Before you start, read:**
1. The view's `views/<slug>/view.md` — the **Thesis**, **Projects**, **Weighting**, and
   **Discard** sections govern both what's selected and how it's written. Note its
   `view_version`. Also skim the view's existing documents under `views/<slug>/resources/` so
   you rewrite rather than duplicate.
2. `${CLAUDE_PLUGIN_ROOT}/docs/FORMAT-SPEC.md` — the exact shapes for RESOURCE.md /
   DETAILS.md / sources.md, version snapshots, and the processing report.

If the corpus half hasn't run (`bramber status` shows pending scans), say so and point at
`/bramber:orchestrate` — do not scan sources here.

The engine writes both the `.md` snapshot and the index rows via `write_resource_version(...)` in
`bramber.engine.db` (call it with `$BRAMBER_ROOT` set, or `db.configure(root=...)` first). If the
new content is byte-identical to the last version, it's a no-op — no new version is minted.

---

## Two modes

### Mode 1 — deterministic baseline (`bramber compile`)

The mechanical path that proves the pipe works. It applies to **any** view with a selector:

```
bramber compile --view <slug> --root $BRAMBER_ROOT
bramber sync    --root $BRAMBER_ROOT
```

`compile_view` loads the shared `_bramber/units/*.json` store, reads the machine-readable
` ```selector ` block from the view's `view.md`, and applies it as a filter. Predicates are
ANDed and an absent one is not applied: `kind`, and `match.<field>` for any payload field —
scalar fields match exactly (`match.evidence_strength: strong, moderate`); list-valued fields
match any-of (`match.topics: pricing, competition`). The block also declares `dedup_by`,
`order_by` and `project` — all three **required**, no defaults — plus optional `section` /
`load_when` / `description`. It renders a deterministic document (frontmatter, a section
heading, one bullet per selected unit, `project`'s first field as the bullet subject) and writes
version *n+1* with one lineage row per (unit × contributing source). **Adding a view needs no
code and no corpus work — just a new `view.md` with a selector block.**

Each bullet closes with its support count (how many distinct sources assert it) and its
reliability floor. That count is the corroboration signal — a claim asserted once by five
sources is not the same as one asserted five times by one source, and the baseline is where the
difference first becomes visible. This mode gives a solid first draft, but the prose isn't the
finished product. That's Mode 2.

### Mode 2 — agent-authored (the real product)

This is where the document becomes good.

**Step 1 — read what the view selects.**

```
bramber select --view <slug> --root $BRAMBER_ROOT
```

This prints the exact set the view projects: `{view_slug, view_name, section, count,
corroborated, units:[...]}`, each entry carrying the full graded payload, its merged
`source_artifacts`, its **support** count and its **reliability_floor**. It's the same set
`bramber compile` uses, full instead of trimmed to a bullet — read it alongside the view's
**Thesis**, and never re-derive selection by hand, so you and the baseline always agree on
what the view projects. For depth behind any claim, follow its `source_artifacts` to the scan
(`scan_path`) and, if needed, the extract (`extract_path`) — spot-reading a scan is cheap;
re-reading the corpus is not this command's job.

**Step 2 — write prose** (integrate the selected units into the resource):

- Follow FORMAT-SPEC § RESOURCE.md: frontmatter, **Load this resource when**, then —
- **`## Current Understanding`** — the compiled best reading of this slice through this view, in
  the view's voice. State it directly; cross-reference sibling documents as `[[resource-slug]]`.
- **`## Key <players | patterns | forces | questions>`** — the most important items, each a
  one-line gist grounded in a specific claim. Lead with the view's **Weighting**, not raw order;
  a claim's support count and reliability floor are evidence for where it ranks, not a
  substitute for the argument.
- **`## Implications`** — what this means for this view's Thesis.
- Apply **Weighting** and **Discard**. Mark superseded claims explicitly — a document is the
  *current best understanding*, not an append log. Rewrite; don't accumulate. For a substantial
  resource, add `DETAILS.md` (depth) and `sources.md` (provenance) per FORMAT-SPEC.

**Step 3 — mint the version:**

```
write_resource_version(view_slug, resource_slug, title=..., content=...,
                       change_summary=..., sources=[{extract, scan, contribution} per source])
```

`extract` and `scan` come from each selected unit's provenance — every entry in its
`source_artifacts` list carries `extract_path` and `scan_path`. **Write one triple per
contributing source, not one per unit:** a claim asserted by three sources has three artifacts
and earns three lineage rows, and that is how corroboration survives into the record.
`contribution` is a one-line "what this source added." Lineage keys on the extract's path, which
`bramber sync` must have indexed first — so sync before you write. The `content` you pass is the
**full** RESOURCE.md text including its frontmatter (the engine writes it verbatim).

**Step 4 — close the loop:** run `bramber sync --root $BRAMBER_ROOT` and confirm the new version
and its lineage rows are indexed (the counts it prints should reflect your write). Append the
run's changelog entry (FORMAT-SPEC § Changelog Entry).

**Report** what you did in the shape of FORMAT-SPEC § Processing / Evaluation Report: which
documents were created or updated and at what version, what was selected versus left
unprojected, and any changes you'd propose to this view's `view.md` (write each as a
`status: pending` file in `_bramber/evaluations/` per FORMAT-SPEC § Evaluation Proposal, for
`/bramber:evaluate` to rule on — never edit `view.md` here).

---

## `--all` roll-up

After processing every qualifying view, emit a short roll-up: views processed
(`<slug>: N units → M documents`), views skipped (no matching units), any cross-view tensions
worth raising in `/bramber:evaluate`, and the next step.

Do not edit any `views/<slug>/view.md` directly. Views are human-gated; propose, never impose.
