---
name: <Audience> Brief
slug: <view-slug>
view_version: 1
maintainer: human
---

# <Audience> Brief

> Genre starter: a decision-ready account for a named audience. Adapt before first use —
> views are human-gated; only /bramber:evaluate changes this file after that.

## Thesis

The current best reading of <the effort> for **<the audience — a steering group, a sponsor, a
regulator, a client>**: what has materially changed, what needs a decision from them, and what
is genuinely contested. This document exists so its reader can act without attending the
meetings — which means it must carry the disagreements and the uncertainty, not just the
progress. A brief that only reports good news is a brief the audience cannot trust.

What this audience can act on is the filter: <name the audience's levers — budget, authority,
scope, escalation>. Material they cannot act on is context at best and noise at worst.

## Projects

Graded claims that change what this audience knows or decides: status shifts, new commitments,
emerged conflicts, closed questions. One idea per claim, each carrying the evidence strength the
sources actually support.

```selector
kind: claim
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength, recency
section: Claims
```

## Weighting

Lead with what is both corroborated and consequential for this audience. Corroboration across
sources outranks emphasis within one — a point several sources make once is stronger than a
point one source makes repeatedly. Where the record disagrees with itself — including where a
summary document disagrees with the primary account it summarizes — state the contest and cite
both sides; do not silently pick a winner.

## Discard

- Internal mechanics the audience has no lever over.
- Restatements of things this audience already decided, unless the record shows them coming
  undone.
- Speculation without a stated basis, unless the speculation itself is the news — then grade it
  `speculative` and say who is speculating.
