---
name: Business Analysis
slug: <view-slug>
view_version: 1
maintainer: human
---

# Business Analysis

> Genre starter: the current-state reading — how things actually work and where they break.
> Adapt before first use — views are human-gated; only /bramber:evaluate changes this file.

## Thesis

How <the process / the operation / the organization under study> actually works today, according
to the record — not the official version, the observed one: who does what, where the handoffs
are, where work stalls or gets redone, and what the root causes are as distinct from the
symptoms people complain about. The gap between how different participants *describe* the same
process is primary evidence — when two accounts of one workflow disagree, the analysis reports
the disagreement and what each party's version implies, because that gap is usually where the
breakage lives.

## Projects

Claims about the current state: process steps and their owners, volumes and durations where
sources state them, failure modes with their observed frequency, causes with their evidence.
Descriptive, not prescriptive — recommendations belong to another view.

```selector
kind: claim
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength, recency
section: Findings
```

## Weighting

Lead with findings corroborated by multiple participants or by both narrative and record. An
account from the person who does the work outranks an account from the person who supervises it,
where they conflict — but report the conflict rather than resolving it silently. Prefer the most
recent account where the record shows the process changing; keep the change visible.

## Discard

- Prescriptions and solution proposals (another view's job).
- The official process description where the record never shows it operating — unless the gap
  between official and actual is the finding.
- Personality framing; the unit of analysis is the process, not the people's characters.
