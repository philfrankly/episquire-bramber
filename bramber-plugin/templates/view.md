---
name: <View Display Name>
slug: <view-slug>
view_version: 1
maintainer: human
---

# <View Display Name>

> Read when compiling the <view-slug> view. Defines what to select, how to weight it, what to drop.
> Human-gated: only /bramber:evaluate changes this file. Adapt this starter before your first run.

## Thesis
<The document's point of view — what this view is FOR and what it believes is worth seeing.
 Write it like you're briefing a smart colleague on the angle you want. 1–3 paragraphs.
 This is the most important thing in the file; the shared claim store is projected through it.>

## Projects
<Which claims this view pulls from the shared store — the topics and evidence grades that
 separate signal from noise for THIS view. Be specific; this is the filter that keeps loud or
 off-topic material out. e.g. "claims tagged pricing or competition", "strong and moderate
 evidence only".>

<!--
The selector below is the executable form of the prose rule above: `bramber compile` runs it over
the shared store to project this view deterministically, with no model in the loop. Keep it — a
view without a selector fails at compile.

`dedup_by`, `order_by` and `project` are REQUIRED and have no defaults; a default would silently
render blank bullets for a unit shape that doesn't carry that field. `project` lists the payload
fields to render, and its FIRST field is the bullet's subject.

Narrow with `match.<field>`: a scalar field matches exactly (`match.evidence_strength: strong,
moderate`); a list-valued field matches any-of (`match.topics: pricing, competition` — use tags
that exist in the store; `bramber claims` shows them). Drop the `match.` lines for a view that
projects everything. Units carry claim_key / statement / evidence_strength / recency / topics.
-->

```selector
kind: claim
match.topics: <topic, topic>
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength
section: Claims
```

## Weighting
<What to lead with and trust most — which sources or grades of claim carry more weight here,
 and what the finished document should open with.>

## Discard
<What to leave out on purpose — material that doesn't belong in THIS view's document even if
 selected and true, so the document stays focused.>
