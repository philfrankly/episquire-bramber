# bramber — spec 05: run status & resume (stage 1 of spec 04)

> Executable build plan for the smallest, highest-leverage piece of the scaling design:
> knowing, at any moment, **what a run has done and what is still pending** — so a spend-limit
> kill, a classifier outage, or a process restart becomes one `bramber status` read and a resume
> of the pending set, not forensics. Self-contained: a fresh session should implement this from
> spec 04 (§5, §8 stage 1) + the existing `bramber/` code + this file.
>
> Reads on: 04 (why), 00 (the seam it must not cross). Realizes spec 04's "run manifest."

---

## 0. What exists, what this adds

Exists: `bramber ingest|sync|rebuild|select|compile|serve|stale|intake` (`bramber/cli.py`); the
disk tree (`_bramber/inbox`, `_bramber/extracts`, `_bramber/units`, `_bramber/routing`,
`_bramber/evaluations`, `views/<v>/digests`, `views/<v>/resources/<r>/`); `bramber/trace.py` as the
precedent for a **stdlib-only sibling module the engine never imports**.

This spec adds:
1. `bramber/run.py` — a stdlib-only module that (a) **derives** pipeline status from disk and
   (b) reads/writes a thin **advisory run-log**.
2. `bramber status [--view <slug>] [--json]` — the read affordance.
3. `_bramber/runs/*.jsonl` — the advisory run-log (gitignored, like `_bramber/traces/`).
4. A `/bramber:process` convention update: consult status, do only the pending, log outcomes.

**Non-negotiable:** `bramber/engine/` is untouched (`git diff --stat bramber/engine` stays empty),
`bramber/run.py` imports only stdlib + `bramber.engine.db` helpers (never the reverse), and the
engine never imports `run`. The Stop-hook sync path gains no new dependency.

## 1. The model — status is derived, the log is advisory

Spec 04 §5 called for a "run manifest." The bramber-idiomatic realization is **not** a stored
manifest that can drift from disk; it is:

- **Derived status (authoritative).** What is done is a fact on disk: a source is ingested iff its
  extract exists; a `(source × view)` is digested iff its digest file exists; a resource exists
  iff its `RESOURCE.md` exists. `derive_status()` reconciles *expected* against *present* and
  computes *pending* — exactly as `sync` derives the index. No new source of truth.
- **Advisory run-log (overlay).** Disk cannot distinguish *attempted-and-failed* from
  *never-reached* — the gap that made this session's recovery hard (a missing digest could be a
  spend-limit casualty or simply not-yet). So actors append per-item outcomes to
  `_bramber/runs/<ts>-<cmd>.jsonl`. Status overlays the latest outcome per item onto the derived
  present/pending. The log is advisory: delete `_bramber/runs/` and status is still correct about
  *what exists*, only losing the *why-missing* annotation. This keeps disk-is-truth intact.

## 2. File formats

**Run-log** `_bramber/runs/<YYYYmmdd-HHMMSS>-<cmd>.jsonl` — one JSON object per line, append-only:

```json
{"item": "<stable key>", "phase": "fetch|normalize|ingest|digest|author", "outcome": "ok|failed|skipped|discarded", "detail": "", "reason": ""}
```

`item` is the stable key for the unit of work: a source `ref` (fetch/normalize/ingest), a
`"<source-ref>|<view-slug>"` pair (digest), or a `"<view-slug>/<resource-slug>"` (author). Later
run-logs win over earlier for the same `(item, phase)` — outcome is last-writer.

**Status JSON** (`bramber status --json`), stable shape:

```json
{
  "root": "<abs path>",
  "inbox": {"links_pending_fetch": 0, "deposits": 22, "ingested": 22, "pending_ingest": []},
  "sources_indexed": 22,
  "views": {
    "market-overview": {
      "digests_present": 22, "digests_expected": 22, "digests_pending": [],
      "digests_failed": [], "digests_discarded": 1,
      "resources_present": 11, "resources_current": 11, "stale": []
    }
  }
}
```

`stale` is present but always `[]` until spec 04 stage 4 (`bramber stale`) lands; wiring the key now
keeps the shape stable.

## 3. `bramber/run.py` (stdlib + `bramber.engine.db` helpers only)

```
record(root, cmd: str, entries: list[dict]) -> Path
    # write entries (each {item, phase, outcome, detail?, reason?}) to
    # _bramber/runs/<ts>-<cmd>.jsonl (mkdir -p; ts from db.now()). Returns the path.

latest_outcomes(root) -> dict[str, dict]
    # read every _bramber/runs/*.jsonl in filename order; return {"<item>|<phase>": entry}
    # keeping the last occurrence. Tolerate malformed lines (skip, never raise).

derive_status(root, view: str | None = None) -> dict
    # pure disk derivation (no run-log):
    #  - links_pending_fetch = count _bramber/inbox/*.txt
    #  - deposits            = _bramber/inbox/*.md
    #  - ingested            = for each deposit, sha256(body) via db.sha256 matched against the
    #                          identity_key in each _bramber/extracts/*.md header (db.split_frontmatter);
    #                          pending_ingest = deposits whose sha has no extract
    #  - sources_indexed     = count _bramber/extracts/*.md
    #  - per view (all views/ dirs, or just `view`):
    #      digests_present   = views/<v>/digests/*.md
    #      digests_expected  = sources routed to <v>: if _bramber/routing/*.md approves specific
    #                          (source × view) pairs, use those; else (single-view / no routing)
    #                          every indexed source. Match by source ref stem.
    #      digests_pending   = expected − present  (report source refs)
    #      digests_discarded = digests whose frontmatter has discarded: true
    #      resources_present / resources_current = resources/*/RESOURCE.md and those with a
    #                          versions/*.md snapshot
    #      stale = []  (placeholder)

status(root, view=None) -> dict
    # derive_status overlaid with latest_outcomes: annotate digests_pending entries whose latest
    # (item, "digest") outcome is "failed" into digests_failed; leave truly-never-reached in pending.

format_status(s: dict) -> str
    # compact human table: inbox line, per-view "digests P/E (F failed, D discarded) · resources R"
    # + an explicit "pending: <refs>" / "failed: <refs>" tail when non-empty.
```

## 4. CLI wiring (`bramber/cli.py`)

Add a `status` subparser (with `with_root`): `bramber status [--view <slug>] [--json]`. Body:

```
from bramber import run
s = run.status(db.ROOT, view=args.view)
print(json.dumps(s, indent=2) if args.json else run.format_status(s))
```

No engine change; mirrors how `select` imports from `bramber.compile`.

## 5. The resume convention (`/bramber:process`)

One paragraph added to `bramber-plugin/commands/process.md` (Mode 2, text): before digesting, run
`bramber status --view <slug> --json` and digest **only** `digests_pending` (skip present — digests
are immutable — and skip anything whose latest outcome is `discarded`). After each digest, append
an outcome via the run-log shape (a one-line python `run.record(...)` call, or the fan-out
workflow does it in stage 3). A resume after any interruption is then: `bramber status` → digest the
pending → integrate. This is the whole behavioural payoff; it needs no fan-out (that is stage 3),
it just makes today's manual process resumable-by-reading instead of resumable-by-forensics.

## 6. Acceptance criteria

Green when all hold:

1. **Engine untouched:** `git diff --stat bramber/engine bramber/compile.py` empty.
2. **Real repo, real answer:** `bramber status --view market-overview --root <a-real-instance>`
   reports `sources_indexed: 22`, `digests_present: 22`, `digests_pending: []`,
   `digests_discarded: 1`, `resources_present: 11` — matching the committed clean-run corpus.
3. **Pending is exact:** on a synthetic root with 3 extracts and 2 digests for a view, status
   lists exactly the 1 missing source in `digests_pending`.
4. **Failure vs not-reached:** after `run.record(root, "digest", [{"item":"srcX|v","phase":"digest","outcome":"failed","reason":"spend limit"}])`, that source appears in `digests_failed`, not
   silently in bare `digests_pending`.
5. **Log is advisory:** delete `_bramber/runs/`; `derive_status` still returns correct present/pending
   (only `digests_failed` empties).
6. **Gates stay green:** `python -m pytest tests/` (roundtrip, first-run, compile-selector, trace,
   plugin-integrity) all pass; new `tests/test_run.py` covers §3.
7. `_bramber/runs/` added to `.gitignore` (both repos' patterns already ignore `_bramber/traces/`;
   add the sibling).

## 7. Non-goals (later stages of spec 04)

- **No fan-out.** Parallel digest/author orchestration is stage 3 (shipped workflow). This spec
  only makes the *pending set* legible and the manual/inline run resumable.
- **No taxonomy, no drift, no trust cadence.** Stage 4. `stale` stays `[]`.
- **No cost estimate.** Sizing/dry-run is stage 2; it will consume `derive_status`'s pending
  counts, which is why they are computed as lists, not just totals.
- **`bramber status` does not execute anything** — it only reports. Re-execution stays with the
  operator / `/bramber:process` until the fan-out workflow exists.
