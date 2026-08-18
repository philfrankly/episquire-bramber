---
description: Run the corpus half of a bramber run — normalize and ingest each deposit into a shared extract, scan each source once for anything claim-shaped (mint-or-reuse claim keys), and materialize the shared unit store every view selects over.
---

You are the orchestrator. This command runs the **corpus half** of a bramber run — the half that
reads sources. Each deposit becomes one `_bramber/extracts/*.md` (the normalized source), one
`_bramber/scans/*.md` (what it asserts), and its slice of the shared unit store. The view half
(`/bramber:process`) never reads a source at all — which is what makes views cheap to add and
re-run.

**The scan is view-agnostic — that is the design.** You read each source once, for anything
claim-shaped, with no view in mind. Do not pre-filter for any view's interests: selection is the
views' job, downstream, where re-running is free. The pipeline is
`ingest → scan (you) → materialize → compile`.

**Before you start, read:**
1. `${CLAUDE_PLUGIN_ROOT}/docs/ORCHESTRATOR.md` — the protocol contract (Stages 1–3).
2. `${CLAUDE_PLUGIN_ROOT}/docs/FORMAT-SPEC.md` § Inbox Deposit and § Scan Schema — the exact
   shapes for what you normalize and what you write.

The engine (`bramber.engine.db`) lives in the installed `bramber` package; all of *this project's*
data lives in the current folder (`$BRAMBER_ROOT`). Adapters run only here, at ingest time, and
write their output to disk. The Stop hook then runs `bramber sync` to index that output — the
engine itself never has to understand your sources.

> **Model tiers** (`${CLAUDE_PLUGIN_ROOT}/docs/ORCHESTRATOR.md` § Model tiers): **normalize** is
> the *cheap* tier (bulk cleanup); the **scan** is the *default* tier — it is the interpretive
> extraction and the main quality knob. Name tiers, not models.

---

## The flow

**1. Normalize + ingest.** For raw deposits (files, `link-*.txt` from `/bramber:intake`): fetch
and normalize each to clean markdown with the deposit frontmatter (FORMAT-SPEC § Inbox Deposit —
fetcher hints there), move the raw original to `_bramber/inbox/processed/`, then:

```
bramber ingest --root $BRAMBER_ROOT
bramber sync   --root $BRAMBER_ROOT
```

This deduplicates by content hash, so re-running is safe.

**2. Scan each unscanned source.** Get the pending set from
`bramber status --root $BRAMBER_ROOT --json` (`scans.pending`) — don't rediscover it by hand;
present scans are immutable, skip them. Then, **before writing any claim**, read the keys the
corpus has already minted:

```
bramber claims --pack _bramber/extracts/<slug>.md --root $BRAMBER_ROOT   # the candidate pack (preferred when the index exists)
bramber claims --root $BRAMBER_ROOT                                      # the full feed (the fallback; the flags degrade to it)
```

Each candidate row carries `reuse_as`, the statement, sources, support, evidence and topics —
and every shape carries the **complete topic vocabulary**. **Read the statement before
copying**: a shortlist nominates by similarity, and a near-neighbour can assert the opposite —
that one is a `## Contradictions` entry citing the candidate's `reuse_as` as a `side:`, never a
reuse. For each pending extract, write
`_bramber/scans/<extract-stem>.md` per FORMAT-SPEC § Scan Schema — **four sections are parsed and
each one produces units**, and a section left as prose contributes nothing, visibly (the envelope
records why, and `materialize` says how many sources it applied to):

- `## Claims` — every claim the source makes, graded (`evidence`), dated (`recency`), tagged
  (`topics`).
- `## Entities` — the named things it talks about, with `role` / `stance` / `status` / `aliases`.
- `## Novel Concepts` — vocabulary it introduces or redefines, with its `gloss`.
- `## Contradictions` — tensions between claims, each `side:` naming a key, an extract path and
  a position.

`## Notes` stays prose and is not parsed.

**Minting and reusing look different, and that difference is the mechanism.** To mint, write a
bare key (`CLAIM-001`) numbered from 1 within this scan — `materialize` stamps it with the
source's own namespace, so you never need to know what another source used and two agents can
never collide. To reuse, copy the **full `reuse_as` token exactly as `bramber claims` prints it**
(`CLAIM-a3f21c04-007=3f9a1c`) as the bullet's key — the `=3f9a1c` tail is a witness quoting the
statement you endorse, and a reuse without it (or with the wrong one) is refused and reported
rather than merged, because a key one slip away from a neighbouring real key would otherwise
corroborate the wrong claim silently. A bare key is always a mint; when you mean "this source
also asserts that claim", copy the whole token.

Reuse is the only mechanism that records corroboration, and **never reuse a key for a claim that
disagrees with the original** — a contested claim gets its own key and the conflict goes in
`## Contradictions`. **The same rule governs `CONTRA-NNN`, and the same feed publishes it** —
`bramber claims` emits every agent-assigned key under `keys`, not just claims. Reuse existing
`topics` tags before minting synonyms — views select on them.

**Entities and Novel Concepts are keyed by their name, so there is no key to mint** — write the
name as the source spells it and record other spellings in `aliases`. Where two sources define a
term incompatibly, write each definition in its own scan exactly as that source has it: the
glossary detects the divergence mechanically, and that divergence is usually the most valuable
thing in the corpus. Normalizing them to one gloss destroys the finding.

A source that asserts nothing checkable is recorded with `discarded: true` and a brief why —
a valid outcome, not a failure. As you finish (or fail) each source, append an outcome so a
resumed run can tell failed from never-reached:
`python -c "from bramber import run; run.record(r'$BRAMBER_ROOT', 'scan', [{'item': '<extract-rel>', 'phase': 'scan', 'outcome': 'ok'}])"`
(use `'failed'` with a `'reason'` on error).

**3. Materialize the shared store — between scans, not only at the end.**

```
bramber materialize --root $BRAMBER_ROOT
bramber index       --root $BRAMBER_ROOT   # where the [embed] extra is installed
bramber sync        --root $BRAMBER_ROOT
```

Run this after **each** scan: materialize is a cheap stdlib parse, and it is what admits the
source you just scanned into the next source's candidate pool — the index derives from the
materialized store, never from scans, so an unmaterialized scan is invisible to every `--pack`.
It re-derives `_bramber/units/*.json` corpus-wide (units are derived data; scans are the
input). Claims repeated within one source collapse to one unit here; claims shared across
sources are counted, not collapsed, at selection.

**`materialize` writes notices to stderr, and they are about YOUR scans — read them.** Each one
names a defect in something you just wrote, and each is repairable by editing that scan and
re-running:

| Notice | What it means | Repair |
|---|---|---|
| a malformed item bullet | that item produced **no unit** at all | fix the bullet (a dropped `**`, or `:` where `—` belongs) |
| an item the parser could not place | the unit exists but is **missing every field after that line** | unwrap the wrapped field value, or flatten the nested sub-list |
| an endorsement was dropped | you cited a key the corpus really minted and the **support was not recorded** | repair the minting scan's key, per the notice |
| a reuse is unresolvable / unwitnessed / mismatched | the endorsement was **refused**, not merged | re-copy the whole `reuse_as` token from `bramber claims` |
| a hyphen-free key had its sentinel segment escalated | **nothing merged** — both claims are intact — but the stored key is no longer the plain stamp of what you wrote | give the hyphen-free key an explicit number (`FINDING` → `FINDING-002`) |

None of these fail the run, and that is the point: the store is still written, so a notice you
skip is a defect that ships silently.

**4. Report.** Sources ingested, scanned, discarded; claims minted vs reused (the reuse count is
the corroboration signal); **every `materialize` notice above that fired, with its count** — a
run that reports "12 sources scanned" while a truncated item quietly dropped a claim's `topics`
has told the reader the opposite of what happened; and the next step: `/bramber:process <view>`
for each view worth compiling — or `/bramber:new-view` if the store now supports an angle no
current view projects.

If there is nothing to ingest and nothing to scan, say so and stop — don't fabricate a run.
Never edit any `view.md` directly; views are human-gated.
