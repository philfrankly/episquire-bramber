---
name: Commercial Position
slug: <view-slug>
view_version: 1
maintainer: human
---

# Commercial Position

> Genre starter: money and obligations — costs, exposure, opportunity. Adapt before first use —
> views are human-gated; only /bramber:evaluate changes this file after that.

## Thesis

The commercial read of <the effort / the account / the venture>: what it costs, what revenue or
value is at risk, what obligations bind it — contracts, vendors, service commitments — and what
opportunities the record shows opening or closing. Quantified where the sources quantify;
explicitly graded where they only gesture ("significant", "a large share") — a vague quantifier
reported as vague is honest, a vague quantifier hardened into a number is fabrication. What
would a person deciding whether to fund, price, or renegotiate this need to know?

## Projects

Claims bearing on money and obligation: costs incurred or committed, value at risk with the
mechanism of the risk, contractual and vendor exposure, commercial opportunities with their
conditions. Each carries who stated it and how well the record supports it.

```selector
kind: claim
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength, recency
section: Claims
```

## Weighting

Lead with what changes the commercial picture most: committed spend, revenue mechanisms at risk,
obligations with dates attached. Corroboration outranks emphasis; a figure stated once by the
person accountable for it outranks a figure repeated often by people who are not. Where sources
disagree on a number or an obligation, state both with their provenance — never average.

## Discard

- Operational detail with no commercial consequence stated or reasonably implied.
- Value language with no checkable content.
- Numbers that appear nowhere in the sources. If a quantity matters and the record lacks it,
  the honest entry is the gap itself, graded as an open question.
