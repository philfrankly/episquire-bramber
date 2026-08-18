---
name: Risk Register
slug: <view-slug>
view_version: 1
maintainer: human
---

# Risk Register

> Genre starter: what could go wrong, graded by the evidence. Adapt before first use — views
> are human-gated; only /bramber:evaluate changes this file after that.

## Thesis

The exposures that could derail <the effort>: threats to its timeline, its people, its
dependencies, its standing with <whoever it answers to>. A risk register earns its keep by being
unflinching — the risks people mention once and never again, the single points of failure
everyone routes around, the assumptions nobody has tested. **Disagreement inside the record is
itself a risk**: when the people involved use the same word for different things, or a summary
contradicts the primary account, the effort is coordinating on an illusion, and that belongs
here as an exposure in its own right.

## Projects

Claims about exposure: what could fail, what it would cost, what it depends on, and who said so.
Speculation is admissible — much early risk signal is speculative — but graded `speculative`
with the speculator named. A risk corroborated across sources or recurring across time is
stronger signal than one loudly stated once.

```selector
kind: claim
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength, topics
section: Risks
```

## Weighting

Lead with exposures that are both corroborated and consequential. Recurrence across meetings
outranks emphasis within one. Keep unresolved questions attached to their risks — an open
question on a live risk is information, not clutter. Never let a later "we're fine now" silently
retire a risk the record shows re-emerging; state the re-emergence.

## Discard

- Generic risks that would be true of any effort, with no anchoring in these sources.
- Mitigation theater: reassurances with no stated mechanism, unless the reassurance itself
  contradicts evidence elsewhere — then the contradiction is the entry.
- Resolved risks, except as one-line traces to what resolved them.
