# work/criteria/ — the terminal condition for a story, and the only thing that closes one

This directory holds **criteria sets**. `../screens/` holds the retired hazard screens and
`../screens/reviews/` holds unstamped adversarial reads. Three record kinds, one directory tree,
so the difference is written down here rather than left to whoever reads the filenames.

## What a criteria set is

A numbered set of conditions authored by walking the global hazard taxonomy
(`~/.claude/skills/acceptance-criteria/hazards.md`) **forward** against a change: for each of the
24 classes, does this change create that surface, and if so what observable condition proves it
handled? Each class yields a **criterion** or a justified **NO SURFACE**, plus one **UNCLASSED**
slot for what no class names.

Every criterion is:

- **executable** — it names the command that decides it,
- **binary** — starting state → expected outcome, one of two answers,
- **proven able to fail** — it names the mutation that reddens it, and that mutation was *run*.

The third is the one that matters, and it is bramber's own discipline generalized: *every safety
gate in this repo was verified red before being trusted.* A criterion nobody has watched fail
decorates rather than gates. Where a mutation was run for this directory, the result is recorded
in the criterion. Where it was not, the criterion says so.

**A story is green when every criterion in its frozen set passes.** There is no other verdict, and
no second opinion that can reopen it — a set frozen and passed stays passed. Anything discovered
afterwards is a **new** story with its own criteria, never an amendment to a closed gate.

## These four sets are RETROACTIVE, and that is a weaker thing

Ordinarily a set is authored **before implementation**, by an author who holds the intent and not
the code. These three were authored on 2026-08-11 against work that had already shipped, under the
skill's named retroactive mode, because the founder ruled that the three stories stranded in
`FIX-FIRST` convert to criteria sets rather than being closed out.

That means the author read the implementation. A criterion written while looking at passing code is
weaker evidence than one written blind, so **every criterion the code already satisfied is tagged
`[retro-satisfied]`** and a later reader is entitled to discount it accordingly. Criteria that are
currently **UNMET** are tagged too, and those are the ones worth reading first.

## Why these exist at all, given screening is discontinued here

The 2026-08-11 ruling *hazard screening is discontinued it has no stop state* discontinues the
screen in this repo and says the obligation is *withdrawn* — no debt to settle later. That ruling
stands for the screen. The founder separately ruled, the same day, that these three stories convert
to criteria sets; the two are recorded as a live edge in
`DevPracticesAudit/decisions/2026-08-11-terminal-condition-written-before-the-code.md`, and this
directory is that edge resolved in favour of conversion.

**This is not the screen returning.** The screen read a finished diff and asked *what is wrong
here*, a question with no stopping point. These ask *what would have to be true*, fix the answer in
advance, and stop when it is. Nothing in this directory blocks a commit, carries a taxonomy stamp,
or derives a review state.

**A criteria set does not discharge a screen, and no screen discharges a criteria set.** They are
not the same instrument pointed in two directions; they are different instruments.

## Filenames

`<story-slug>.md`, one per story, no date suffix — a criteria set is amended by a dated
`Supersedes:` block inside it, never by a second file. That is the opposite of the screens
convention next door, where each round was a new file, and deliberately so: a screen was an event
and a criteria set is a standing record.
