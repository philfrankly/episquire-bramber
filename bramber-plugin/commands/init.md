---
description: Scaffold a new bramber project in the current folder — the `_bramber/` working tree and your first `view.md` — then create the index. Run this once, first, in the folder where your knowledge base will live. Usage: /bramber:init [one-line description of what this project is for]
---

You are setting up a new bramber project in the current folder (`$BRAMBER_ROOT` / cwd). The goal is
to get the operator from an empty folder to "ready to add sources" in one command — without
overwriting anything that already exists.

The starter templates live in the plugin at `${CLAUDE_PLUGIN_ROOT}/templates/` (`view.md`, plus
the genre starters under `templates/views/`). The `view.md` template ships with a working
`selector` block — edit it, don't delete it; `bramber compile` needs one.

---

**1. Guard against clobbering.** Look at the current folder. If a non-empty `views/` directory is
present, this is already a bramber project — **stop and report**. Point the operator at editing
the existing view, or at adding a new one (`/bramber:new-view`). Never overwrite.

**2. Learn what this project is for.** If the command was given a description argument, use it.
Otherwise ask the operator two short questions and stop there — don't over-interview:
- In one line, what is this project for?
- What's the first document (view) you want, and what angle should it take?

**3. Create the working tree.** Make these folders (bramber's scratch space):
`_bramber/inbox/`, `_bramber/extracts/`, `_bramber/scans/`, `_bramber/units/`. `inbox/` is where
the operator drops sources; `scans/` is written by the scan step of `/bramber:orchestrate`;
`units/` is filled by `bramber materialize`, never at ingest.

**4. Scaffold the first view.** Create `views/<slug>/view.md` from
`${CLAUDE_PLUGIN_ROOT}/templates/view.md` (slugify the view name; set the frontmatter `name` and
`slug`, keep `view_version: 1`, `maintainer: human`). Write a real **Thesis** from the operator's
angle — this is the most important thing in the file. Then fill **Projects** with the topics and
evidence grades that separate signal from noise for this view, and **Weighting** / **Discard**
with what to trust and what to drop. Remind the operator the view is **human-gated** — they
should edit it to taste, and only `/bramber:evaluate` changes it later.

Keep the template's ` ```selector ` block — it is what `bramber compile` executes for the
deterministic baseline, and a view without one fails at compile. The default is the right
starting point for most views:

```selector
kind: claim
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength
section: Claims
```

`dedup_by`, `order_by` and `project` are **required** — they have no defaults on purpose. Narrow
the view with `match.<field>` predicates — `match.topics: <topic, topic>` to select by subject
(any-of over the claim's tags), or `match.evidence_strength: strong, moderate` for a view that
should only project well-evidenced claims — and adjust `project` (the first field is the
bullet's subject) if the operator's angle calls for it.

**5. Create the index and ignore the derived DB.** Run:

```
bramber init --root .
```

Then keep the derived database out of version control: add `bramber.db`, `bramber.db-wal`, and
`bramber.db-shm` to `.gitignore` (create the file if absent; don't duplicate lines already there).

**6. Tell them what's next.** Drop sources into `_bramber/inbox/`, then `/bramber:orchestrate`
(normalize, ingest, scan, materialize) → `/bramber:process <slug>` (project + author). Adding a
second view later costs no re-reading — it selects over the same shared claim store.

---

If the operator only wants the bare skeleton with no drafting, copy the template verbatim
and skip the drafting in step 4. Never overwrite an existing `view.md`.
