# Format Spec

> Exact templates and schemas referenced by `ORCHESTRATOR.md` and the `/bramber:*` commands.
> Load the section you need when you need it.

Frontmatter across a bramber project is **flat** (`key: value`) so the engine's
`db.split_frontmatter` can parse it without a YAML dependency. The one exception is the
repeating `source:` key in version snapshots (a pipe-triple), described below.

---

## Inbox Deposit

What lands in `_bramber/inbox/*.md` **before** ingest. The fetching agent writes this: fetch
the source, normalize to clean markdown, add this frontmatter. (Raw files and `link-*.txt`
deposited via the intake server are **not** yet in this shape — `/bramber:orchestrate`
normalizes them into it before ingest; the server itself only deposits raw bytes, and must
never normalize, since parsing sources never happens inside the bramber package.)

`bramber ingest` carries **`source_url` / `source_type` / `title` / `author` /
`date_published`** into the extract header and thence the index — one of those missing here
is NULL in the index forever, so fill what you know. `channel`, `publication` and
`transcript_source` stay in the inbox file (context for readers, not indexed);
`date_ingested` is stamped at ingest time regardless of what the deposit says.

```yaml
---
source_url: <original URL or file:// path>
source_type: <blog | report | transcript | video | podcast | data | opinion | announcement | research | pdf | doc>
title: "<title from source>"
channel: "<for videos / podcasts>"           # optional
publication: "<for blogs / articles>"        # optional
author: "<if identifiable>"
date_published: YYYY-MM-DD                    # omit if unknown
date_ingested: YYYY-MM-DD                     # today
transcript_source: <youtube-auto-generated | manual | …>  # transcripts only
---
```

Fetcher hints: web articles via `WebFetch`; YouTube via `youtube-transcript-api` (transcript)
+ `yt-dlp` (metadata); PDFs via `pdftotext` or Python extraction; `.docx` via `pandoc`;
markdown files copy directly with frontmatter added if missing. Clean ASR artifacts and filler
from transcripts at deposit time — **normalization quality is product quality**, and the body's
sha256 is the source's identity, so normalize once and keep it.

---

## Extract Header (written by `bramber ingest`; the engine parses it)

Every file in `_bramber/extracts/*.md`. The extract is **view-agnostic** — the normalized
source, shared by every view that reads it. You never write this header by hand; `bramber
ingest` materializes it from the adapter's output, and `bramber sync` rebuilds the index from
it (spec 01 §4 — the header is the only channel between an adapter and the engine).

```yaml
---
identity_kind: content_sha                    # the identity scheme; pluggable per adapter
identity_key: <stable dedupe hash>            # sha256 of the normalized body
identity_json: {"…"}                          # structured identity — the source's ref
source_type: <domain string>
title: "<…>"
source_url: <…>                               # present when the adapter supplied it
author: <…>                                   # present when the adapter supplied it
date_published: YYYY-MM-DD                    # present when the adapter supplied it
date_ingested: YYYY-MM-DD
---
```

Dedupe is by `identity_key` — for text, sha256 of the normalized body. If two deposits
normalize to the same body, the second upserts onto the first. Because identity is the *body*
hash, re-fetching a source whose upstream rendering changed (e.g. a re-run of YouTube ASR)
mints a **new** source: migrate existing extracts rather than re-fetching them.

---

## View

`views/<slug>/view.md`. One view's analytical framework — a projection of the shared claim
store onto a document. **Human-gated — updates are applied by `/bramber:evaluate` on your
approval; no other command edits it.** A view is cheap to add and cheap to re-run: it reads
the store, never a source.

````markdown
---
name: <View Display Name>
slug: <view-slug>
view_version: <integer, bump on human edit>
maintainer: human
---

# <View Display Name>

> Read when compiling the <slug> view. Defines what to select, how to weight it, what to drop.

## Thesis
<The frame. What this view believes is true and worth seeing. 1-3 paragraphs.>

## Projects
<What this view pulls from the shared claim store — which topics and evidence grades separate
 signal from noise for THIS view.>

<Plus a machine-readable selector block, which `bramber compile` executes deterministically
 over the store. It is the executable form of the prose rule above:>

```selector
kind: claim
match.topics: <topic, topic>
dedup_by: claim_key
order_by: claim_key
project: statement, evidence_strength
section: Claims
```

## Weighting
<How much interpretive trust to place in source types / claim grades for THIS view, and what
 the finished document leads with.>

## Discard
<What to leave out of the finished document even when selected — presentation judgment for
 the authoring step, not a second selection pass.>
````

`view_version` is recorded on the resources this view compiles, so a later view edit never
silently rewrites the meaning of a past reading — the old versions stay in the chain.

**Selector keys.** Predicates are ANDed and an absent one is not applied: `kind` (the unit
kind, `claim` for scan-derived units) and `match.<field>` — the generic payload predicate over
any payload field. A **scalar** field matches on equality (`match.evidence_strength: strong,
moderate`); a **list-valued** field (like `topics`) matches if ANY of its values is allowed
(`match.topics: pricing, competition`). Three keys are **required and have no defaults**,
because a default would silently render blank bullets for any unit shape that happens not to
carry that field: `dedup_by` (the payload field selection dedupes and keys lineage on),
`order_by` (the payload field to sort on), and `project` (comma-separated payload fields to
render — **the first is the bullet's subject**, the rest render as `name: value`). `section`,
`load_when`, and `description` are optional presentation. A view missing a required key fails
loudly at compile rather than compiling something empty.

---

## Scan Schema (one per source)

`_bramber/scans/<extract-stem>.md` — named for the extract it reads, so the pairing is
mechanical. One source, read **once**, view-agnostically, for anything claim-shaped.
**Immutable** once written. This is the interpretive step where synthesis quality lives:
state claims decisively and grade the evidence — uncertainty is *graded*, not hedged away.

**A claim is bounded by form, not by topic**: an assertion the source makes that could be true
or false and that a reader could check against the source. The scan does not decide what
matters — every view's selector and authoring step do that downstream, where re-running is
cheap. Do not pre-filter for any particular view's interests.

The scan is also **the unit producer**. `bramber materialize` reads four sections below —
`## Claims`, `## Entities`, `## Novel Concepts` and `## Contradictions` — and derives the shared
`_bramber/units/<slug>.json` store from them, so **those four shapes are exact and machine-read.**

`## Notes` stays prose **permanently**: it is per-scan editorial argument about this source,
singular and non-repeating, with no dedup key and nothing to corroborate. Materializing it would
produce one unit per scan that merges with nothing.

**Writing a section in prose is allowed and costs nothing except that section's units.** A scan
written before these shapes existed still contributes every claim it always did; `materialize`
says once per run how many sources that applied to, and each envelope carries a per-kind
`kinds_absent` reason. Three reasons, deliberately distinguishable: the section is absent · the
section says `None identified` (**a real finding** — this source was examined and had none) · the
section has content in a shape the parser does not recognise (a migration, and the only case that
reports a line count).

```markdown
---
source: _bramber/extracts/<filename>
scan_date: YYYY-MM-DD
discarded: <true | false>          # true: nothing checkable asserted; body says why, briefly
---

## Claims

- **CLAIM-007** — Revenue grew 22% year over year, driven by the agents product line.
  - evidence: strong
  - recency: 2026-05-01
  - topics: revenue-trajectory, product-mix

## Entities

- **Acme Corp** — supplies the integration middleware and holds the Q3 slot.
  - role: vendor
  - stance: supports the current timetable
  - status: new
  - aliases: Acme, ACME Corporation
  - topics: vendor-risk

## Novel Concepts

- **cutover** — the window in which the old system stops and the new one starts.
  - status: new
  - relates_to: Acme Corp
  - topics: migration-sequencing

## Contradictions

- **CONTRA-001** — The minutes record the date as fixed; the transcript records it as under review.
  - side: CLAIM-ab12cd34-007 | _bramber/extracts/minutes_01__ab12cd34.md | recorded as fixed
  - side: CLAIM-ff00aa11-004 | _bramber/extracts/transcripts_01__ff00aa11.md | under review
  - resolution: the minutes postdate the meeting and omit the caveat the transcript carries
  - status: proposed
  - topics: deadline-integrity

## Notes
[The source's most important contribution, its evidentiary boundary stated honestly
 (adjacent evidence is not confirmation), and anything a future reader of this scan
 should know that the claims alone don't carry.]
```

**The Claims shape is exact — it is parsed.** One bullet per claim: `- **<CLAIM-KEY>** — <the
statement>`, then indented sub-bullets for its fields. Anything not in this shape is invisible
to `bramber materialize` and contributes no unit.

- `evidence` — one of `strong | moderate | weak | speculative`. (`evidence_strength` is
  accepted as a synonym.) It reaches the units as `evidence_strength`, so a view can select on
  it (`match.evidence_strength: strong, moderate`) or project it.
- `recency` — the date of the *underlying evidence*, not the publication date.
- `topics` — free-form tags for what the claim is about, comma-separated, lowercase-hyphenated.
  Reuse existing tags (visible in `bramber claims` output) before minting new ones — views
  select on these, and a synonym tag is a claim a view silently misses.

**Entities and Novel Concepts are keyed by their NAME.** The bold span is the identity,
normalized by casefold + whitespace-collapse. Nobody chose "Acme Corp" — the sources carry it —
so unlike a `CLAIM-NNN` there is no key to mint and no feed to check first. Fields:

- `role` — vendor / sponsor / regulator / system / team. (Not `kind`: that is the unit's own
  field and a payload key by that name would confuse every reader of an envelope.)
- `stance` — where the entity stands on something the programme is deciding.
- `status` — `new` on first appearance, `update` when the record revises what you knew.
- `aliases` — other surface forms in the sources, comma-separated. Write the aliases rather than
  silently normalizing to one spelling: an under-merge is visible and correctable, a wrong merge
  fabricates attribution.
- `relates_to` (Novel Concepts) — entities or terms this one depends on.

**A term two sources define incompatibly is the single most valuable thing in this section.**
Write each definition under the same bold name in that source's own scan, exactly as that source
has it. The glossary detects the divergence mechanically — same key, more than one distinct gloss
— and in an implementation programme that divergence is usually where the requirement everyone
thought was agreed turns out not to be.

**A contradiction's sides are `<KEY> | <extract-path> | <position>`.** Use the **stored** key as
`bramber claims` prints it — `CLAIM-a3f21c04-007`, not a bare `CLAIM-007`. A bare key names a
claim in no namespace and will not resolve against the store, and a tension whose sides all fail
to resolve cannot be served back to either claim it contests.

**For a claim you are minting in the scan you are writing, the feed has not printed the key
yet — derive it.** The namespace is the eight hex characters after `__` in the extract filename
you are reading, so a claim you author as `CLAIM-007` while scanning
`_bramber/extracts/minutes_01__ab12cd34.md` is stored as `CLAIM-ab12cd34-007`, and that is what a
`side:` must carry. This is the ordinary case, not an edge one: most tensions are *this* source's
claim against another's, so the own-source side is the one you cannot look up. For the other
source's side, copy the key from `bramber claims`. The extract
path is still carried because it makes a side checkable without trusting the key at all. A
`<view>/<KEY>` ref written against the withdrawn per-view shape is read for the part after the
slash rather than dropped — the claim it names is unambiguous now even though it was not when
written.

`CONTRA-NNN` keys are minted and reused from the same corpus-wide feed as claim keys — `bramber
claims` emits **every** agent-assigned key, claims and contradictions alike, under `keys`. Check it
before assigning a `CONTRA` key exactly as you would before assigning a `CLAIM` key: two sources
recording the same tension **reuse** the key and it gains support like anything else, and two
sources independently assigning the same key to *different* tensions would merge them into one
register entry claiming support neither source gave. The compared-with source named in a `side:`
does **not** become a source of the contradiction: it supplies the contrast, it does not assert
the tension, and folding it into provenance would inflate the support count.

**Minting and reusing are written differently, and the difference is the whole mechanism.**

- **To mint**, write a short bare key: `CLAIM-001`, `CONTRA-002`. Number from 1 within *this*
  scan; you do not need to know what any other source used. `materialize` stamps it with your
  source's namespace, so it becomes `CLAIM-<8 hex>-001` in the store.
- **To reuse**, copy the **full `reuse_as` token exactly as `bramber claims` prints it** —
  `CLAIM-a3f21c04-007=3f9a1c` — as the bullet's key. The tail after `=` is the **witness**: six
  hex quoting the statement you are endorsing. Key and witness travel as one atom; never
  assemble the token by hand.

Before scanning, read the mint-or-reuse feed. It has three shapes, one row everywhere — each
candidate row carries `reuse_as`, `statement`, `sources`, `support`, `evidence` and `topics`:

- `bramber claims --root $BRAMBER_ROOT` — the **full feed**: every key ever minted. The
  fallback and the audit view; at corpus scale its recall degrades, which is what the
  shortlists exist to fix.
- `bramber claims --pack _bramber/extracts/<slug>.md` — the **pre-scan candidate pack** (the
  bulk path): the ~100–300 keys similar to any section of the extract you are about to scan,
  plus the complete topic vocabulary. Read it once, then scan with no mid-scan round trips.
- `bramber claims --like "<draft statement>"` — the **per-claim check** (the escape hatch):
  the ~10 nearest keys for one statement you are about to mint, when the pack left you unsure.

Every shape serves the **complete topic vocabulary** under `topics` — topics are never
shortlisted, because a tag you cannot see is a synonym split you are about to create. If the
`[embed]` extra or the index is absent, the shortlist flags serve the full feed with a notice —
same rows, same discipline, only recall differs.

**Read the statement before copying.** A shortlist nominates by similarity, and similarity is
not sameness: a candidate row can be near your claim and assert something different — or its
opposite. Copy a `reuse_as` only after reading the row's `statement` and judging it the same
claim; a candidate that *contradicts* your draft is not a retrieval error, it is a finding —
mint your own key and record the tension in `## Contradictions`, citing the candidate's
`reuse_as` as a `side:`. If this source asserts a claim already keyed, copy that `reuse_as`.
That makes "source 4 asserts `CLAIM-a3f21c04-007`, first minted by source 1" an explicit,
auditable decision — readable from the key itself, since the key names its minting source. Every
`--pack`/`--like` call **that serves a shortlist** also records the candidates it showed you
(`_bramber/runs/`), so "the agent saw the key and minted anyway" is auditable evidence, not a
guess. A call that degraded to the full feed records nothing — the whole universe was shown,
and the stderr notice is the record that the degrade happened.

**Why the witness is required, not polite.** A reuse is an endorsement, and a key alone cannot
carry intent: a one-digit slip — or blending two feed rows while copying — lands on a
*neighbouring real key*, passes every existence check, and silently corroborates a claim your
source never discussed. That is fabricated support in the exact field this product is sold on.
The witness makes the endorsement a *quotation*: if the key and the witness name different
claims, `materialize` refuses the merge, keeps your claim as your own, and tells the operator
which key your witness actually matches. A reuse **without** a witness is refused the same way.
Nothing is guessed in either direction.

**Why the namespace exists.** Keys used to be counted upward from one corpus-wide feed, so two
agents scanning different sources both read the same high-water mark and both minted `CLAIM-042`
for unrelated claims. Selection merged them and reported two corroborating sources for a claim
neither made twice. A namespace makes that unreachable without any coordination between agents.

**A bare key is always a mint.** If two sources both write a bare `CLAIM-001`, they are two
different claims and will not merge; `materialize` says so on stderr rather than guessing, because
guessing reuse would restore the collision and guessing mint would silently delete corroboration.
When you mean corroboration, copy the `reuse_as` token.

Two consequences worth holding in mind while writing. Repeating a key *within one scan*
collapses to a single unit — an insistent source restating a position five times contributes
one claim, not five. Reusing a key *across sources* does not collapse: it raises the claim's
support count and adds a lineage row. **Never reuse a key for a claim that disagrees with the
original** — dedup may collapse restatement, never disagreement; a contested claim keeps its
own key and the disagreement goes in `## Contradictions`.

A source that asserts nothing checkable is recorded with `discarded: true` and a body that
briefly states why (one paragraph replaces the three sections). A discarded scan contributes
no units.

---

## RESOURCE.md

`views/<slug>/resources/<rslug>/RESOURCE.md`. The compiled current view — the served content.
Frontmatter description target 150–200 chars; body target 35–50 lines. This is the Mode-2
(agent-authored) shape; the deterministic baseline (`bramber compile`) writes a simpler bullet
body — one bullet per selected unit, from the view's `project` fields — with the same core
frontmatter.

```markdown
---
name: <resource-slug>
title: <Title>
description: "<One declarative sentence — routing aid plus one-line gist. No comma-stuffed entity lists.>"
view: <view-slug>
last_updated: YYYY-MM-DD
version: <current version number>
source_count: <number of contributing sources>
confidence: <high | medium | low>
maintainer: <agent | human>
---

# <Title>

**Load this resource when:** <2-3 sentences: trigger topics, entities, questions this answers.>

## Current Understanding
<One paragraph (5-10 lines): the compiled best view. State directly. Cross-ref siblings as
 [[resource-slug]].>

## Key <Components | Players | Patterns | Roles | etc.>
- **<Name>** — one-line gist.
- (4-8 bullets.)

## Implications
<One short paragraph on what this means for the project's purpose. Depth lives in DETAILS.md.>

## Where to Look
- **`DETAILS.md`** — <what's in the depth file>.
- **`sources.md`** — provenance.
- Cross-references: [[resource-1]] for <why>.
```

Each view should maintain one **`overview`** resource (its load-first orient view).
`overview` may omit `DETAILS.md` — depth lives in the resources it cross-references — but
while no sibling resources exist yet (a fresh or mono-source view), keep an overview
`DETAILS.md` so the depth has somewhere to live.

Frontmatter `version:` and `last_updated:` are **advisory reader aids** — the authoritative
values are the engine's `version_num` and `created_at` in the snapshot header, stamped by
`write_resource_version`. If unsure of the next version number, omit `version:` rather than
guess. A `[[resource-slug]]` cross-reference may point at a resource that doesn't exist yet
(it marks intended structure); never invent content for a dangling reference, and don't
propagate cross-project references from a view's Thesis into a resource body.

---

## DETAILS.md

No frontmatter. H1 title + depth sections: full claims with evidence strength, full entity
inventory, full implications, open questions, contradictions & tensions. Loaded on demand
from `RESOURCE.md`.

## sources.md

```markdown
# Sources — <Resource Title>

## Contributing Sources

### YYYY-MM-DD — <Author / Channel>, "<Source Title>" (<Publication> <date>)
- Extract: `_bramber/extracts/<filename>`
- Scan: `_bramber/scans/<filename>`
- Contributed:
  - <What this source added to this resource.>
```

---

## Version Snapshot

`views/<slug>/resources/<rslug>/versions/<n>.md`. An immutable snapshot of `RESOURCE.md` at
version `n`, **plus lineage**. This is what makes `bramber.db` rebuildable, so the format is
exact. `bramber.engine.db` writes and reads it; if you write it yourself, match this precisely:

```markdown
---
resource: <view-slug>/<resource-slug>
version: <n>
created_at: <ISO8601>
content_sha: <sha256 of the body below>
change_summary: <one line: what changed and why>
source: <extract-path> | <scan-path> | <one-line contribution>
source: <extract-path> | <scan-path> | <one-line contribution>
---
<the full RESOURCE.md body content at version n>
```

Each `source:` line is a pipe-triple: **extract path, scan path, contribution** — the scan
path is the `_bramber/scans/…` file that source's claims came from. Repeat the key once per
contributing source; a claim asserted by three sources writes three rows, which is what makes
corroboration expressible in lineage. These become `version_sources` lineage rows. The easiest
way to produce a correct snapshot is to call `write_resource_version(...)` in
`bramber.engine.db` (after `configure(root=...)`), which writes `RESOURCE.md` and the snapshot
and records the DB rows in one step.

Two things the writer does **verbatim**, so know them: the `content` you pass is the FULL
`RESOURCE.md` text *including its frontmatter* (pass only a body and you mint a
frontmatter-less resource, with no error); and the snapshot embeds that full content right
after its own frontmatter — two adjacent `---` blocks in `versions/<n>.md` is correct, not a
bug.

---

## Changelog Entry

`changelog.md` (project root), append-only, newest last. One dated entry per run that
changed anything:

```markdown
## YYYY-MM-DD — <command> [<view-slug>]
- <resource or file touched>: <what changed, one line>
- proposals: <evaluation files written / decided, or "none">
```

---

## Processing / Evaluation Report

Emit after `/bramber:process` and `/bramber:evaluate`.

```markdown
## Report — YYYY-MM-DD — <command> [<view-slug>]

### Units Projected
- <count> selected (<count> corroborated) through <view-slug>

### Resources Updated
- <view-slug>/<resource>: v<n-1> → v<n> — <what changed and why>

### Resources Created
- <view-slug>/<resource>: <why this was needed>

### Proposed View Updates (<view-slug>)
- <topic-selection change / weighting change / discard tweak, or "None">

### Flags for Human Review
- <cross-view contradictions, conflicts with maintainer:human resources, or "None">

### Errors / Skipped
- <anything that couldn't be processed, with reason>
```

Recorded proposals are written as **Evaluation Proposal files** (next section) and are
reconciled when the operator approves or rejects them in `/bramber:evaluate`.

---

## Evaluation Proposal

`_bramber/evaluations/YYYY-MM-DD-view-<target>[-<n>].md`. The pending-proposal queue for
`/bramber:evaluate`, **disk-first**: proposals are files, so they survive `bramber rebuild` like
everything else (disk is truth; the DB's `evaluations` table is a future index over these
files — no command writes it by hand). Written by `/bramber:process`; status is updated in
place by `/bramber:evaluate` and by no other command.

```markdown
---
scope: view
target: <view-slug>
status: <pending | approved | rejected>
proposed_by: <command that raised it>
created: YYYY-MM-DD
decided: <omit this key while pending; /bramber:evaluate adds it with the ruling date>
---

## Recommendation
<The exact change proposed — quote the current wording and the proposed wording.>

## Rationale
<Why — which scans/sources/tensions motivated it.>
```

**Store-hygiene proposals** (`YYYY-MM-DD-store-<queue>-<n>.md`, filed by `bramber hygiene`)
use the same file shape with `scope: store`, `target: <merge | topic | alias | ledger>`, and a
`subject:` key — the pair or key under examination, stable across sweeps. The subject is the
dedup identity: a sweep never re-files a subject any existing proposal carries, **whatever its
status** — a rejected proposal is itself a record that the pair was examined. The
Recommendation names the exact repair (almost always one token edit in one scan); nothing is
ever applied outside the `/bramber:evaluate` gate, and a similarity score in the Rationale
*nominated* the pair — it never decides.
