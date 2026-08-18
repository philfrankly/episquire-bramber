# bramber commands

The `/bramber:*` slash commands, in the order you'd normally use them.

| Command | What it does | Status |
|---|---|---|
| `/bramber:init` | **Set up.** Scaffold a project in the current folder — your first view, the `_bramber/` working dirs, and the index. Run this first. Usage: `/bramber:init [one-line description]`. | **Implemented** |
| `/bramber:orchestrate` | **Read the corpus.** Normalize every new source into a shared extract, scan each source once for anything claim-shaped (mint-or-reuse claim keys), and materialize the shared claim store every view selects over. | **Implemented** |
| `/bramber:process` | **Compile a view.** Project the shared store through one view's selector into a versioned document with lineage. Reads no sources — cheap to re-run. Two modes: a deterministic baseline and an agent-authored prose version. Usage: `/bramber:process <view>` or `--all`. | **Implemented** |
| `/bramber:new-view` | **Add a view.** Scaffold a new `views/<slug>/view.md` — drafts a Thesis and a selector — and compile it against the existing store immediately, at no corpus cost. Usage: `/bramber:new-view [name: angle]`. | **Implemented** |
| `/bramber:intake` | **Deposit.** A browser form (drag-and-drop files, paste links) for dropping new sources into `_bramber/inbox/`. | **Implemented** |
| `/bramber:evaluate` | **Govern.** Review pending framing proposals and apply the ones you approve to a `view.md`, then recompile so the ruling takes effect. Views are human-gated — this is the only command that edits them. | **Implemented** |
| `/bramber:consistency-pass` | **Realign.** After a framing change is applied, propagate it down through agent-maintained documents. | **Implemented** |

**The everyday loop:** `/bramber:init` once to set up, then `/bramber:orchestrate` whenever
sources change (the paid half — it reads them) and `/bramber:process <view>` whenever you want a
document (the cheap half — it re-selects). Use `/bramber:new-view` any time you want another
point of view over the same store — it compiles instantly — and `/bramber:evaluate` whenever
proposals are pending (the report from each run tells you).
