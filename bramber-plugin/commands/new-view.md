---
description: Scaffold a new view in an existing bramber project — a `views/<slug>/view.md` with a drafted Thesis and a working selector — then compile it against the shared claim store, at no corpus cost. Usage: /bramber:new-view [name, or "name: the angle it takes"]
---

You are adding a new view to an existing bramber project (cwd / `$BRAMBER_ROOT`). A view is a point
of view that compiles the project's shared claim store into its own document. **Adding one costs
no corpus work** — the store already exists; a view is a selection over it, so it can be compiled
the moment it is scaffolded and recompiled any time it changes. This command scaffolds the view
file and hands the framing back to the operator to finalize — views are human-gated, so you
draft, they own.

The starter template is `${CLAUDE_PLUGIN_ROOT}/templates/view.md`, and
`${CLAUDE_PLUGIN_ROOT}/templates/views/` holds **genre starters** (stakeholder-brief,
requirements, risk-register, business-analysis, commercial, decision-log — see its README) with
the Thesis/Weighting/Discard prose already shaped for the genre. When the operator's angle
matches a genre, start from that file instead of the blank one. Every starter ships with a
working ` ```selector ` block — every view needs one, so edit it rather than delete it.

---

**1. Confirm this is a bramber project.** If `views/` does not exist in the current folder, this
folder isn't initialized — **stop** and tell the operator to run `/bramber:init` first.

**2. Get the view's name and angle.** Use the argument if given (e.g.
`/bramber:new-view technical-risks: what could go wrong and why`); otherwise ask two short
questions — what should this view be called, and what angle should it take? Slugify the name for
`<slug>`.

**3. Guard against collision.** If `views/<slug>/view.md` already exists, **stop** — that view is
already there. Offer a different slug or point the operator at editing the existing one. Never
overwrite.

**4. Know what the selector can reference.** Units are materialized from the per-source scans,
so a unit's `kind` is `claim` and its payload always carries `claim_key`, `statement`,
`evidence_strength` (`strong | moderate | weak | speculative`), `recency`, and `topics` (a list
of tags). Those are the field names available to `dedup_by` / `order_by` / `project` /
`match.<field>`. Run `bramber claims --root $BRAMBER_ROOT` to see what the store actually
holds — the topics in use are the vocabulary a new selector can select on. Skim a sibling
`views/*/view.md` for a selector worth imitating.

**5. Scaffold the view.** Create `views/<slug>/view.md` from the template (set the frontmatter
`name` and `slug`, keep `view_version: 1`, `maintainer: human`). Write a real **Thesis** from the
operator's angle — this is the most important part — then fill **Projects** / **Weighting** /
**Discard**.

Keep the template's ` ```selector ` block:

```selector
kind: claim
match.topics: <topic, topic>
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength
section: Claims
```

`dedup_by`, `order_by` and `project` are **required** — they have no defaults, and a view
missing one fails loudly at compile instead of rendering blank bullets. Narrow with
`match.topics` (any-of over each claim's tags — use tags that exist in the store, from step 4)
and/or `match.evidence_strength: strong, moderate` for a view that should carry only
well-evidenced claims; drop the `match.` predicates entirely for a view that projects the whole
store. Adjust `project` (the first field is the bullet's subject) if the angle calls for it.

Present the drafted view and invite the operator to adjust it — they own the framing.

**6. Register it.** Run `bramber sync --root .` so the new view is indexed right away (the Stop hook
also re-syncs every turn).

**7. Compile it now.** This is the payoff of the shared store — no re-reading, no waiting:

```
bramber compile --view <slug> --root .
```

If the store is empty (no sources scanned yet), the compile writes an honest empty document and
the real content arrives after `/bramber:orchestrate` runs; say so. Otherwise show the operator
what their new view projects, and point at `/bramber:process <slug>` for the agent-authored
prose version.

---

Never overwrite an existing `view.md`. If the operator only wants a blank view, copy the
template verbatim and skip the drafting in step 5.
