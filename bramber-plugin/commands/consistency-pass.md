---
description: After a view change is applied (via /bramber:evaluate), propagate that authoritative framing downward into factory-maintained resources. Downstream-only; never edits views; no source re-processing.
---

You are running the **consistency pass**. The trigger is that a human-gated framing file —
a `views/<slug>/view.md` — has changed, and factory-maintained resources may now reference
superseded framing.

## What this command does

1. **Read the authoritative framing** to establish current position:
   - the changed `views/<slug>/view.md` (and any others if multiple changed)
   - any resources with `maintainer: human` in frontmatter (these are also authoritative —
     read, never rewrite)

2. **Scan factory-maintained resources** (`maintainer: agent`) in the affected view(s) for
   references that may now be inconsistent. The likely surfaces are: "Implications" sections,
   "Current Understanding" claims that lean on a superseded thesis, cross-view framing, and
   any vocabulary the view edit changed. (Selection changes are already handled — a recompile
   over the shared store picks them up mechanically; this pass is for the prose that leans on
   the old framing.)

3. **For each inconsistency, apply a surgical update** with the Edit tool — only rewrite the
   references that contradict or supersede the authoritative framing. Preserve the substance
   and tightness of each resource. Each edit mints a new version: call
   `write_resource_version` in `bramber.engine.db` with a `change_summary` like "consistency
   pass: realign to <view-slug> v<n>" and lineage carrying forward the prior sources.

4. **Do NOT:**
   - rewrite resources wholesale,
   - edit any `view.md`,
   - edit `maintainer: human` resources,
   - fabricate facts not present in the authoritative framing,
   - re-process any sources or rewrite existing scans.

5. **Append to `changelog.md`** a dated entry listing each resource touched and what changed,
   and flag anything you couldn't reconcile.

## Principles

- **The views are the source of truth.** Factory-maintained resources follow them.
- **Substance over surface.** Don't churn cosmetic wording; update only where framing
  meaningfully contradicts.
- **Downstream-only.** This propagates authoritative changes into resources — never the
  reverse.
- **Prospective, not retroactive.** Scans and prior version snapshots are immutable; only
  the current resource view absorbs new framing.

If no inconsistencies are found, say so briefly and stop. Don't fabricate work.
