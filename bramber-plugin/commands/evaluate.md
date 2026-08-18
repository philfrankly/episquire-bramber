---
description: Run the propose-approve loop — review pending view updates, then APPLY the changes the human approves (and only those) to each view.md, and recompile so the ruling takes effect.
---

> **Model tier** (`${CLAUDE_PLUGIN_ROOT}/docs/ORCHESTRATOR.md` § Model tiers): evaluation is a
> *premium*-tier job — framing changes are high-stakes, low-volume, and human-gated. Name the
> tier, not a model.

You are running the evaluation loop. The discipline is **approval-gated, then applied**: you
present each proposed framing change, the human approves or rejects it, and you **apply exactly
the approved ones** — no manual pasting. Approval is the gate; application is bookkeeping.
**This is the only command permitted to write any `view.md`, and only the approved subset.**

**Before you start, read these:**
1. `${CLAUDE_PLUGIN_ROOT}/docs/ORCHESTRATOR.md` — the protocol contract (Stage 5)
2. every `views/*/view.md`
3. every `status: pending` file in `_bramber/evaluations/` (FORMAT-SPEC § Evaluation Proposal
   — the disk-first queue; never read or write the DB for this), plus any resources changed
   since the last evaluation

## View updates

For each pending proposal with `scope: view` (raised by `/bramber:process` — topic-selection
changes, weighting changes, discard tweaks, thesis tensions), present it to the user with
its rationale and ask approve/reject:
- On **approve**: apply the change to `views/<slug>/view.md` with the Edit tool — a surgical
  edit to the relevant section (Thesis / Projects / selector / Weighting / Discard) — and
  **bump `view_version`** in the frontmatter. Update the proposal file: `status: approved`,
  `decided: <today>`.
- On **reject**: update the proposal file to `status: rejected`, `decided: <today>`. Make no
  framing edit.

If several approved proposals target the same `view.md`, apply all of them, then bump
`view_version` **once**.

**A view change takes effect by recompiling, and recompiling is cheap** — selection runs over
the unchanged shared store; no source is re-read. After applying an approved change, run
`bramber compile --view <slug> --root $BRAMBER_ROOT` (or the Mode-2 path in `/bramber:process`)
so the ruling is visible in the document, not just in the framing file. Old versions stay in
the chain, where lineage keeps them — a view change never rewrites a past reading.

## Store repairs

For each pending proposal with `scope: store` (raised by `bramber hygiene` — merge proposals,
topic-drift pairs, alias suggestions, ledger repairs), present it with its rationale and ask
approve/reject:
- On **approve**: the repair is what the proposal's Recommendation names — almost always **one
  token edit in one scan** (replace a bullet key with a `reuse_as` token, fold an `aliases:`
  entry, re-tag a topic), applied with the Edit tool under this gate, followed by
  `bramber materialize --root $BRAMBER_ROOT` so the store re-derives, then a recompile of any
  affected view. This is the ledger's repair doctrine: scans are immutable *to the agent
  process*, not immune to human-gated correction, and disk-is-truth makes the rebuild total.
- On **reject**: `status: rejected`, `decided: <today>` — and nothing else. A rejected
  proposal is itself a record that the pair was examined; the sweep will not re-raise it.

Never merge on similarity: a merge proposal's score *nominated* the pair, and only this
approval decides. A pair whose statements disagree is a `## Contradictions` entry, not a
merge, whatever the score says.

## Cross-view review

Having reviewed new/changed resources across all views, raise any of your own proposals as new
`status: pending` files:
- a new view worth creating (then point the user at `/bramber:new-view` — adding one costs no
  corpus work),
- a cross-view contradiction (a resource in one view disagrees with one in another — both cite
  the shared store, so name the claim keys in contention),
- a topic vocabulary problem (synonym `topics` tags splitting what should be one selectable
  subject — propose the canonical tag; fixing it means re-scanning only the affected sources).

## After

- If you applied any view change, append a dated entry to `changelog.md` listing each file
  touched, the version bump, and a one-line summary — the audit trail for a self-applied
  framing edit. (Git is the backstop: every applied change is a reviewable, revertible diff.)
- Because framing changed, recommend (and the user may run) `/bramber:consistency-pass` to
  propagate the new authoritative wording downward into factory-maintained resources.

Emit a short report: which view changes were **applied** (with their new versions and whether
the recompile ran), which were **rejected**, and what `/bramber:consistency-pass` should
realign. If there are no pending evaluations and no new resources to assess, say so and stop —
don't fabricate work.

**Boundary:** apply only what the human approved in this run; never apply a rejected
proposal; never edit framing outside this approval gate. `/bramber:evaluate` is the sole
command that **modifies the content of an existing** `view.md` (`/bramber:init` and
`/bramber:new-view` only *scaffold* new framing files). Every other command — orchestrate,
process, consistency-pass — proposes, never edits framing.
