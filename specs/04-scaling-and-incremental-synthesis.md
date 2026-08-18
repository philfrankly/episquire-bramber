# bramber — spec 04: scaling & incremental synthesis (design)

> How `/bramber:process` becomes one operation that is *elegant at 3 sources and correct at 300* —
> and how solving that also delivers incremental update, staleness, resumability, and cost
> legibility, because they are the same mechanism seen from different sides.
>
> Design-first. Unlike specs 00–03 this is not yet an executable build plan; it fixes the model
> and names the open decisions (§7) before any code. Reads on: 00 (the seam), 02/03 (the runs it
> generalizes). Motivated by the 2026-07 clean run, where a 22-source corpus only completed
> because the operator hand-authored the fan-out the tool should own.

---

## 1. The shaping problem

Today `/bramber:process <view>` assumes one agent can hold a view's whole job in context: digest
each source, integrate them into resources, done. That is genuinely elegant for a small load —
one coherent act of judgment — and it should stay exactly that for small loads. It simply does
not survive scale: at 22 sources the digests alone are ~320 claims, and no single context both
reads them all and authors ten resources well. The clean run worked only because the operator
manually decomposed it into fan-out workflows. **A tool a researcher can run must own that
decomposition, and must choose it without the operator choosing.**

The prize is not just "handles big repos." It is that the *same* architecture that scales also
gives us incremental update (add one source to a live repo), `bramber stale` (know what's behind),
run resumability (survive a spend limit), and cost legibility (know before you run) — all of
which are on the polish list as if they were separate. They are not. §2 is why.

## 2. The thesis: the pipeline is a resumable map-reduce over digests keyed by resource

Look at the five phases by how they break with scale:

| Phase | Shape | Scales by | Breaks at scale? |
|---|---|---|---|
| fetch / normalize | per source | fan-out (map) | no — bounded by external rate limits, not context |
| digest (source × view) | per source | fan-out (map) | no — embarrassingly parallel |
| **integrate** | **across all digests** | **???** | **yes — this is the whole problem** |
| version / serve | per resource | already per-unit | no |

Four of five phases are already `map` — one agent per source, run wide. The one that breaks is
**integrate**, and it breaks because it is a `reduce`: it reads *across* digests to decide the
resource set and to write each resource from the digests that feed it.

The insight that unlocks everything: **integrate is a reduce over digests, keyed by resource, and
the taxonomy is the grouping function.** Once you see it that way:

- **Small load** — grouping + reduce fit in one context. Run them inline in one agent. *This is
  today's behaviour, and it is the correct degenerate case; keep it.*
- **Big load** — grouping is a fan-out-able pass that emits `{resource → [digests]}`; the reduce
  is one author agent per resource, each reading only its group. Fan-out both.
- **A single group too big for one context** (a resource fed by 200 sources) — the reduce nests:
  map-summarise the group in batches, then reduce the summaries. Same operator command.
- **Incremental update** — a new source is digested (map of one), routed into the existing
  grouping (which resources does it touch?), and only the touched groups are re-reduced.
- **Staleness** — is the read side of the same fact: a resource is stale when a digest in its
  group is newer than the resource's version, or when its `view_version` moved. `bramber stale`
  computes the delta; incremental update consumes it. **Stale and incremental update are one
  feature.**

So most of the polish list is one architecture: *a resumable, adaptively-sized map-reduce over
digests keyed by resource, with the grouping (taxonomy) as persistent, human-gatable state.*

## 3. Adaptive execution — the operator never chooses small vs big

`/bramber:process <view>` first **sizes** the job — counts un-digested sources, estimates total
digest volume, counts resources needing (re)authoring — and picks the shape:

- below a threshold (a handful of sources, digests that fit one context): **inline** — one agent,
  digest + integrate, exactly today.
- above it: **fan-out** — parallel digests, a grouping pass, parallel authors, nested reduce for
  any oversized group.

The threshold is a property of context budget, not a mode the operator sets. The same sizing step
that picks the shape is also the **dry-run**: it can print the plan and its rough cost *before
executing* (§6). One mechanism, three payoffs — adaptivity, legibility, and the estimate a
researcher needs before spending.

## 4. Integration, decomposed (the hard reduce)

Three sub-steps, each an inspectable disk artifact so the whole thing is resumable and auditable:

1. **Route / group** — decide `{resource-slug → [digest paths]}`. **Operates on routing-cards,
   not full digests** (this is what makes the 300-source ceiling a single grouping agent rather
   than a hierarchical cluster — see §7.1). Each digest emits, alongside its full body, a compact
   *card*: its claims' tracked-question tags, a one-line gist, and its entity list (~150 tokens).
   300 cards ≈ 45k tokens — one agent reads them all and emits the carve; the full digest is read
   only later, by the author of the resource it lands in. For a first run this *derives* the
   taxonomy from the cards; for a live repo it *reuses* the persisted taxonomy and only routes new
   cards into it. Routing a card to a resource is largely mechanical (the tags do most of the
   work); only the *carve itself* (what resources exist) is deep judgment, and it is the human
   gate whose cadence §7.4 governs.
2. **Author** — one agent per resource, reading only its group + the view. Fan-out. A group over
   the context ceiling triggers a nested map-reduce (batch-summarise → synthesise) transparently.
3. **Overview** — a final reduce over the authored resources (not the digests). Always last,
   always one agent (it is small by construction — it reads resource tops, not raw claims).

The carve is the one genuinely global judgment and therefore: (a) the human gate, (b) the thing
that must stay **stable** across incremental updates (a resource set that thrashes every time a
source is added is unusable), which is why it is persisted, not re-derived each run, and evolved
only through proposals (`/bramber:evaluate` territory). "When has enough drifted to re-carve?" is a
real question §7 leaves open.

## 5. Resumability & incremental update fall out for free

bramber already has 90% of this: disk is truth, ingest is idempotent, digests are immutable, every
version is snapshotted. The missing piece is a **run manifest** — a per-run record of what each
phase produced, keyed by stable identity (source identity_key, resource slug). Resume is then
"diff the manifest against disk and do what's missing"; a spend-limit kill mid-run becomes a
one-command continue instead of forensics. Incremental update is the same diff with one new source
in the input set. This is the affordance the clean run needed five times and had to fake by hand.

## 6. Cost & scope legibility

Because sizing (§3) happens before execution, `/bramber:process` can always answer, up front:
"N sources to digest, M resources to (re)author, ≈K agent-calls, run a subset with `--only
<slug>` or `--sample N`." A researcher scoping a 300-source repo can dry-run, cost it, and run a
5-source slice first. The estimate is a by-product of the sizing the tool already does to choose
its shape — not new machinery.

## 7. Decisions (resolved 2026-07-18)

1. **Scale ceiling: ~300 sources.** This is the number the rest of the design is sized to. Its
   key consequence: at 300, the grouping pass cannot read every full digest (~300 × ~2k tokens ≈
   600k+, expensive and context-marginal), so it reads **routing-cards** instead (§4.1) — ~45k
   tokens for 300, comfortably one agent. Routing-cards therefore push the point where *hierarchical*
   clustering (cluster → name) becomes necessary well past 300 (cards stay one-agent to ~1–2k
   sources), so **we do not build clustering now**; it is a documented later ceiling, not this
   design's problem. Full digests are only ever read by the single resource-author they belong to,
   which fan-out already bounds.
2. **Taxonomy: persist, re-carve on a drift metric.** The carve is persisted view-level state;
   new cards route into it; it is not re-derived each run. A **drift metric** — a small composite:
   (a) share of recent cards that route weakly or fall to a catch-all (the territory grew a limb
   the carve doesn't cover), (b) any group past a size/heterogeneity split threshold, (c) rising
   cross-resource claim redundancy (the carve axes are wrong) — is computed each run. When it
   crosses threshold, bramber does **not** auto-re-carve; it **raises a re-carve proposal into
   `_bramber/evaluations/`**, exactly like every other framing change, and `/bramber:evaluate` decides.
   Drift is thus one of the two triggers that re-summon human attention (§7.4).
3. **Orchestration: bramber ships a versioned, tested fan-out workflow (option B)** the command
   invokes. Implications, made explicit (per your "may not see full implications"): (i) it couples
   the *scale* path to the harness providing a fan-out primitive — but the **inline small-load path
   never depends on it**, so a missing primitive degrades bramber to "small loads only," never to
   broken; (ii) the workflow becomes a bramber-versioned artifact carrying its own tests, maintained
   beside the engine and commands; (iii) runs become reproducible and auditable (a named,
   version-stamped harness) instead of improvised per run. The engine invariant is untouched — the
   engine still never calls a model; orchestration lives wholly in the agent layer.
4. **Human gates: a cadence set by view trust × drift, not by N.** A view carries a **trust
   level**. A new view starts **high-supervision** — carve, routing, and resource proposals all
   surfaced (the 5-source "demands attention" experience). Clean approvals (few or no corrections)
   raise trust; a rejected proposal or a hand-edit lowers it. As trust rises, per-run approval
   **fades to spaced sanity checks** (every Nth run / every M new sources) — momentum gathers.
   Drift (§7.2) overrides the spacing: it re-summons a check regardless of trust. One corollary
   this exposes: a **new view is never first-run against the full 300** — it is broken in on a
   `--sample` slice (§6), earns trust there, then opened to the corpus. So `--sample` is not only a
   cost lever; it is the trust on-ramp. Approval is a dial (view maturity × drift), not a switch —
   which is precisely how the same tool feels attentive at 5 sources and keeps momentum at 300.

## 8. Staged build (once §7 is settled)

1. **Run manifest + resume** — smallest, unblocks everything, pays off immediately (§5).
2. **Sizing + dry-run** — the adaptivity/legibility mechanism (§3, §6); also the safety rail
   against another unscoped spend-limit run.
3. **Fan-out integrate** — the shipped orchestration workflow (§4) behind the *unchanged*
   `/bramber:process` surface; inline path preserved for small loads.
4. **Persisted taxonomy + drift metric + view-trust cadence + `bramber stale` + incremental update**
   — the living-repo set (§2, §4, §7.2, §7.4): the features that make bramber worth using for
   *maintained* research bases specifically, and that turn the human gate from a switch into a
   trust-earned dial.

Each stage is independently shippable and leaves the small-load experience untouched. Routing-cards
(§4.1) are a prerequisite folded into stage 3, since fan-out integrate needs them.

## 9. Assumptions of record

- **Scale target ~300 sources/view**; hierarchical taxonomy clustering deferred as a later ceiling.
- **Fan-out depends on an agent-layer orchestration primitive** in the operating harness; small
  (inline) loads do not.
- **Taxonomy and its re-carve are human-gated** via `/bramber:evaluate`; the drift metric only
  *proposes*, never applies — consistent with bramber's framing-is-human-gated invariant.
