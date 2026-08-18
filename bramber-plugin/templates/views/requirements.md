---
name: Requirements
slug: <view-slug>
view_version: 1
maintainer: human
---

# Requirements

> Genre starter: what the effort must deliver, as traceable normative statements. Adapt before
> first use — views are human-gated; only /bramber:evaluate changes this file after that.

## Thesis

What <the effort> is required to deliver, stated as normative claims — each traceable to **who
asked for it, in which source, and how firmly**. A requirement is not a wish: the record must
show someone with standing asking for it, accepting it, or being held to it. Where two parties
require incompatible things — or use the same word to mean different obligations — that conflict
IS a requirement-level fact and belongs here as a contested claim, never averaged into a
compromise nobody stated.

Scope: <bound what counts — the system, the process, the program deliverables>.

## Projects

Normative claims: "must / shall / is required to", plus acceptance criteria and explicit
exclusions ("out of scope" is a requirement statement too). Each claim names its requester or
authority. Firmness follows the evidence: a requirement stated once in passing is `weak` until
the record corroborates it.

```selector
kind: claim
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength
match.evidence_strength: strong, moderate
section: Requirements
```

## Weighting

Lead with requirements that carry authority and corroboration — asked for by someone with
standing, confirmed or acted on elsewhere in the record. An emphatic single statement does not
outrank a quiet requirement the record keeps honoring. Contested requirements go in a section of
their own, with each side cited.

## Discard

- Aspirations nobody is held to.
- Solution designs masquerading as requirements (how, not what) — unless a source explicitly
  makes the how a condition of acceptance.
- Requirements already formally retired, except as a one-line trace to the retiring decision.
