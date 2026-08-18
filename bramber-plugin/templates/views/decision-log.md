---
name: Decision Log
slug: <view-slug>
view_version: 1
maintainer: human
---

# Decision Log

> Genre starter: what was decided, by whom, on what basis — and what came undone. Adapt before
> first use — views are human-gated; only /bramber:evaluate changes this file after that.

## Thesis

Every decision the record shows being taken in <the effort>: what was decided, who owned it,
what basis was stated, and — the part most logs miss — **what happened to it afterwards**.
Decisions get reversed, quietly reopened, or honored in name while practice diverges; a log that
only records the taking is a list of intentions. A decision the minutes record as settled while
the discussion shows it still contested is logged as contested, with both citations — the
disagreement between record and room is exactly what a reader of this document needs to know.

## Projects

Claims about decisions: taken (owner, basis, date), pending (what blocks them, who must act),
reversed or reopened (by what, citing both the original and the change). Status is part of the
claim, and it moves with the evidence.

```selector
kind: claim
dedup_by: claim_key
order_by: recency
project: statement, recency, evidence_strength
section: Decisions
```

## Weighting

Order by recency — a decision log is read newest-first. Weight by authority and follow-through:
a decision by its accountable owner, later acted on, is settled; a decision recorded once and
never referenced again earns a lower grade and an open question. Reversals lead — they change
more downstream understanding than fresh decisions do.

## Discard

- Opinions and preferences that never became a commitment.
- Actions that are execution of an already-logged decision (they evidence follow-through; cite
  them on the parent claim rather than logging them separately).
- Procedural micro-decisions (scheduling, formatting) with no bearing on the effort's course.
