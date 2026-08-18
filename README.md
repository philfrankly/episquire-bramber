# bramber

> **bram·ber** /ˈbræm.bər/ · *n. proper noun, English (a Saxon-founded village in West Sussex,
> seat of a ruined Norman castle); adopted here as a portmanteau of* **bramble** *— a tangled,
> thorny convergence, no two branches alike — and* **amber** *— fossil resin that takes something
> chaotic and organic and holds it whole, structure intact, made precious by time.*
>
> Previously named **foinse** (Irish, *a source*) — see the 2026-07-26 ruling *rename to bramber*.

**Compile many sources into one trustworthy document — and keep it honest as the sources pile up.**

bramber is a Claude Code plugin. You point it at a pile of material — research notes, articles,
meeting transcripts, interview write-ups — and it produces a small set of **living documents**, each
written from a point of view *you* define. Every claim in the output traces back to the exact
source it came from, every document is versioned, and — the part that matters most — a loud,
long-winded, or off-topic source **cannot bully its way into the result.**

Think of it as the difference between *asking* and *building*:

- A chatbot **answers a question** and forgets. The answer lives in the chat and evaporates.
- bramber **builds a document** that persists, versions itself, cites its sources, and can be
  rebuilt from scratch at any time.

If a chatbot is a conversation over your sources, bramber is a **compiler** for them: your sources
are the input, a *view* is the build target, and the output is a versioned artifact with a full
record of where every line came from.

---

## Why not just paste everything into a chatbot?

For a quick one-off question, you should — a chatbot is lower-friction and bramber would be
overkill. bramber earns its keep when your material is **large, keeps changing, and needs to be
trusted by other people.** Here's the difference:

| | Chatbot / uploaded docs | bramber |
|---|---|---|
| **Output** | A chat reply that disappears | A document on disk, versioned |
| **Citations** | Best-effort prose, sometimes wrong | Every claim linked to its exact source |
| **When a source changes** | It never notices | It can flag what's now out of date |
| **Ask again next week** | Different answer, no record | Same document, or a diffable new version |
| **A huge, loud source** | Tends to dominate the answer | Gets no extra say (see below) |

The last row is the whole point, so it gets its own section.

---

## The one idea that makes bramber trustworthy: **selection, not summarization**

Paste ten documents into a chatbot and ask for a summary, and the longest, most confident,
most repetitive source tends to win — not because it's *right*, but because it's *big*. That's
the failure mode bramber is built to prevent. It defends on three fronts.

**First, it dissolves every source into small, uniform pieces — once.** Before anything is
written, each source is *scanned* exactly one time and reduced to **units** — atomic claims,
one idea each, all the same shape, each graded for how strongly that source actually supports
it. A source's length, formatting, bold text, and rhetorical flourishes are stripped away in
this step. By the time any document is written, there is no "big source" left to shout — only a
set of plain, equal-sized units in one shared store that every document draws from. Because the
scan doesn't know or care which documents you'll want, you can add a new point of view next
month and compile it in seconds — no source is ever re-read.

The units are **produced by reading** — a model reads the source and enumerates what it
actually claims — and then **stored as data the engine counts.** That second half is what
lets bramber tell *"five sources each said this once"* apart from *"one source said it five times"*.
The first is corroboration and the second is volume, and a system that cannot separate them is
just a summarizer with extra steps.

**Second, you write a *view* that declares what it's looking for — and units that don't match
never enter the document.** A view is a short file you author (its heart is a **Thesis**: what
this document is *for*). When bramber compiles a view, a unit is included only if it fits that
view's declared interest. A 10,000-word vendor whitepaper and a 10-word footnote are both
reduced to *"the units that actually match this view"* — and if the whitepaper is mostly
promotion, most of it simply doesn't match. **Volume buys no influence.**

**Third, the view says what to trust and what to drop.** Alongside the Thesis, a view carries a
**Weighting** rule (what to lead with) and a **Discard** rule (what to leave out). These are
*your* standing instructions, authored once and human-gated — not a prompt you retype and not
something a source can override. And because every unit keeps a link back to its origin, a
weakly-supported claim stays visibly weak: you can see it traces to a single thin source.

So, concretely — the three kinds of noise, and how each is handled:

- **Verbose** → dissolved into units; a long source gets exactly as many seats as its matching
  units earn, no more.
- **Irrelevant** → filtered out by the view; if it doesn't match the Thesis, it isn't in the
  document.
- **Poorly supported** → down-weighted or discarded by the view's rules, and left visibly
  thin by its own provenance if it slips through.

**One honest caveat, and it is a real one.** *Reading* a source into units is model work: it takes judgment to
decide what a document actually claims, and no parser will do it. *Everything after that is
mechanical.* Which units a view admits is a deterministic filter — a predicate engine reading a
machine-readable rule out of your view, no judgment in the loop. Deduplication, corroboration
counting, and the reliability floor are arithmetic over declared data. The final prose is model
work again, guided by your Thesis.

So the guarantee is real but narrower than "airtight end to end": **once a claim exists, volume
cannot buy it influence.** What is not guaranteed is that the reading step extracted the right
claims in the first place. That is a genuine limitation and it is the one worth watching. It is
also not yet measured — see **Status** below, which says so plainly rather than pointing at a
number that does not exist.

---

## The five words bramber uses

| Word | Plain meaning |
|---|---|
| **Source** | A raw input — a document, an article, a transcript, a set of notes |
| **Unit** | One atomic finding pulled from a source (a claim, an entity, a fact) |
| **View** | A point of view you define; it decides which units become which document |
| **Resource** | The compiled document a view produces — versioned, with lineage |
| **Lineage** | The link from every line of a Resource back to the units and sources behind it |

The flow is always the same: **sources → units → (a view selects) → a Resource.**

---

## Quickstart (works today, no special setup)

The fastest way to see bramber work is with **text** — documents and notes. This path needs
nothing beyond Python's standard library.

**1. Install the engine.**

```bash
git clone https://github.com/philfrankly/episquire-bramber.git
cd episquire-bramber
pip install -e ".[mcp]"              # the engine + the MCP server used to serve your documents
pip install -e ".[mcp,embed]"        # …or add search over your claims (optional — see below)
```

The engine itself needs **nothing but the Python standard library**. Both extras are optional
and both degrade cleanly: without `[mcp]` you lose the server, and without `[embed]` every
search falls back to listing the whole claim store — same information, same discipline, just
less convenient at scale.

> **`[embed]` runs a small model on your own machine.** It downloads once (~50 MB) and then
> works offline. There is no API key, no account, and **no part of your corpus is ever sent
> anywhere** — which is the point: these documents are usually the material you are least able
> to hand to a third party.

**2. Add the plugin to Claude Code.** The simplest way to try it is to launch Claude Code with
the plugin directory loaded:

```bash
claude --plugin-dir ./bramber-plugin
```

Once loaded, the `/bramber:*` commands become available; the MCP server and the auto-sync hook
register themselves — no extra setup. (To keep it around permanently instead of passing the flag
each time, add `bramber-plugin/` through Claude Code's plugin marketplace — see the
[plugin docs](https://code.claude.com/docs/en/plugins.md).)

**3. Scaffold your project.** In the folder where you want your knowledge base to live:

```
/bramber:init
```

It asks a couple of quick questions — what the project is for and what your first document
should cover — then sets up your first view, the `_bramber/` working folders, and the index.
(You can also seed it with a one-liner: `/bramber:init research notes on battery supply chains`.)

**4. Add your material.** Drop documents into `_bramber/inbox/` (Markdown or plain text).

**5. Sharpen your view's Thesis.** Open `views/<slug>/view.md` and refine the **Thesis** that
`/bramber:init` drafted — one or two paragraphs on what this document is *for* and what's worth
seeing. This is the most important thing you'll write; it's the lens everything is compiled
through.

**6. Read the corpus once, then compile.**

```
/bramber:orchestrate      # normalizes your sources and scans each one — once — into the shared claim store
/bramber:process <view>   # compiles your view over that store into a document (no source is re-read)
```

Your finished document lands in `views/<slug>/resources/` — versioned, with a link from every
point back to the source it came from. Add more sources later and run it again; you get a new
version you can diff against the last.

Add a source that repeats what you already had and the affected lines gain a *source count*
rather than a second entry. That is the part to watch: agreement between sources accumulates,
repetition inside one source does not.

---

## Writing a view (the part worth spending time on)

A view is a short Markdown file with four sections. You'll spend most of your effort here,
because the view is what makes the output *yours* rather than a generic summary.

- **Thesis** — what this document is for, and what it believes is worth seeing. Write this like
  you're briefing a smart colleague on the angle you want.
- **Projects** — which claims this view pulls from the shared store (by topic tags and evidence
  grade — the selector is the machine-readable form of this).
- **Weighting** — what to lead with and trust most.
- **Discard** — what to leave out on purpose.

Two views over the *same* sources produce two different documents — an "executive summary" view
and a "technical risks" view select from the same store through different eyes. That's the
design: one scanned set of claims, many honest projections. Add another angle any time with
`/bramber:new-view` — it compiles immediately, because the reading is already done.

Views are **human-gated** — a source can never edit your view. Only you (through
`/bramber:evaluate`) change what a document is looking for.

---

## What about documenting code?

bramber briefly shipped an adapter that documented a codebase — each symbol as a source, compiled
into views like *API Surface* and *Architecture*. It has been **withdrawn**, on purpose.

It depended on an external extraction engine that was never publicly installable, so the path
could not actually be run by anyone who cloned this repo. Keeping unrunnable code in the tree to
support a claim on the README is the exact failure this project is built to avoid, and carrying
two domains made bramber read like two half-products instead of one whole one.

The use-case is preserved as a **requirement for a future adapter**, not as shipped code — the
seam it plugged into is unchanged, which is the part worth keeping.

---

## How it stays honest over time

- **Versioned.** Every compile writes a new numbered version only if the content actually
  changed. Re-running with no new sources is a no-op — no version churn.
- **Traceable.** Every Resource version records exactly which sources fed it. Open any document
  and walk it back to the evidence.
- **Rebuildable.** The documents on disk are the source of truth. The search index
  (`bramber.db`) is derived and can be thrown away and rebuilt at any time — losing it is a
  non-event.
- **Served over MCP.** Your compiled documents are exposed to Claude read-only, so you can ask
  questions against your *curated* knowledge base instead of re-reading raw sources every time.

---

## Under the hood (for the curious)

bramber is split so that the engine never has to know what your sources *are*. One small piece —
the **Adapter** — is the only part that understands a specific kind of material (it turns a
source into units). Everything after that — storing, versioning, tracking lineage, indexing,
serving — is domain-blind and uses only Python's standard library, so it never breaks on a
missing dependency. Adding a whole new kind of source means writing one Adapter; adding a new
document over sources you already have means writing one new view, no code at all.

---

## Status

Early and honest about it (`v0.0.0`):

- **Text synthesis** — runnable today, standard library only. This is the recommended starting
  point, and it is what bramber is *for*.
- **Units, corroboration, and mechanical selection** — landed 2026-07-21. Claims become stored
  units with a stable key; repeating a claim within one source collapses to one unit, while five
  sources asserting it counts to five. Every unit carries a support count and a reliability floor,
  and both appear in the compiled document.
- **View-agnostic scanning** — landed 2026-08-07. Each source is read once into a shared claim
  store; every view is a cheap, re-runnable projection over it. Adding or editing a view costs
  no re-reading (the 2026-08-07 ruling *view agnostic claims compiler only*).
- **In use** — bramber compiles a 45-source research corpus into 13 views today, every source
  read exactly once. That run is the cost structure working rather than argued: 45 scans served
  13 views, where a per-view design would have needed 585 reads. It is published as a
  demo you can read and re-run: the compiler side at
  [`episquire-robotics-bramber`](https://github.com/philfrankly/episquire-robotics-bramber),
  and the view-blind source corpus it reads at
  [`episquire-robotics-corpus`](https://github.com/philfrankly/episquire-robotics-corpus).
- **Measured** — **not yet, and I would rather say so than imply otherwise.** The
  length-independence guarantee above is *structural* — it is the selection code, and you can
  read it — but no published number stands behind it. Building a generalized evaluation, one that
  measures the cost structure and the selection guarantee without being tied to a single corpus
  or a single domain, is what I am working on now. Until it lands, treat everything on this page
  as an argument you can check in the source, not as a result.
- **Code documentation** — **withdrawn.** bramber briefly shipped an adapter that documented a
  codebase by treating each symbol as a source. It depended on an external extractor that was
  never publicly installable, so nobody could run it, and keeping it made bramber read like two
  products. The use-case is preserved as a requirement for a future adapter, not as shipped code.
- **Commands** — all seven are implemented: `init`, `intake`, `orchestrate`, `process`,
  `evaluate`, `consistency-pass`, `new-view`.
- **Staleness** — automatic "this source changed, re-check these documents" is designed but not
  yet wired up (`bramber stale` currently says so and exits).

If you're trying it on your own notes or research and something is unclear, that's a
documentation bug worth reporting.
