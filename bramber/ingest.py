"""bramber ingest — the domain-aware front half of an ingest run.

Canonical spec: specs/09-view-agnostic-claim-scan.md (supersedes specs/07 §3's per-view
materialization; specs/02 §1 before that).

`ingest()` runs an Adapter (discover -> identity -> normalize -> extract_units) over
every source and *materializes* the result to disk: one extract `.md` per source (with
the generalized header from spec 01 §4, which `db.split_frontmatter` parses) and one
units `.json` per source (for text, filled later by `materialize` from the agent's scans).

The split is deliberate (spec 01 §4): the expensive, domain-specific adapter work happens
once, here, at ingest time. The engine's `--sync` (run by the Stop hook every turn) then
reconstructs the index from these on-disk headers with **no adapter import** — a cheap
parse, stdlib-only, oblivious to the domain. So this module imports an adapter; the engine
never does.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from bramber import trace as _trace
from bramber.engine import db
from bramber.engine import header as header_schema


def make_adapter(name: str = "text", **_ignored):
    """Construct a reference adapter by name.

    One adapter ships: `text`. A `code` adapter existed and was withdrawn — it wrapped an
    extraction engine that was never publicly installable, so the path could not be run by
    anyone who cloned the repo (the 2026-07-21 ruling "excise code adapter preserve code use case").
    The seam it plugged into is unchanged, which is the part worth keeping: a new domain is
    still one Adapter and no engine edit.
    """
    if name == "text":
        from bramber.adapters.text import TextAdapter
        return TextAdapter()
    raise ValueError(f"unknown adapter {name!r} (only 'text' ships today)")


def write_units_envelope(units_dir, slug, extract_rel, qname, units, *,
                         produced_by: str, absent_reason: str,
                         kinds_absent: dict | None = None,
                         kinds_unparsed: dict | None = None) -> Path:
    """**The one writer** of `_bramber/units/<slug>.json`.

    Two callers produce units — `ingest` (the adapter, at ingest time) and `materialize`
    (scans, later) — and they must not each carry their own idea of the envelope's shape. That
    is the writer-vs-writer form of the drift that produced the NULL-url bug, and it is cheaper
    to prevent than to detect.

    A source that produced nothing writes `units: null` plus a stated reason, never `[]`: an
    empty list is indistinguishable from "extraction ran and legitimately found nothing", so a
    directory of correctly-named 200-byte `{"units": []}` files read as work that had happened
    and misrepresented the text path for the whole life of the repo (specs/07 §5.4).
    """
    envelope = {"extract_path": extract_rel, "qname": qname, "units_produced_by": produced_by}
    if kinds_absent:
        # Per-kind absence, alongside the whole-source `units_absent_reason`. Same discipline one
        # level finer: a source can legitimately produce claims and no entities, and "the section
        # says None identified" is different information from "this scan predates the
        # machine-readable block". Collapsing them loses the only signal that distinguishes a
        # finding from a migration.
        envelope["kinds_absent"] = dict(sorted(kinds_absent.items()))
    if kinds_unparsed:
        # A count, per kind, of content lines the parser could not place. Present even when that
        # kind produced units — the whole point is the partial case, which `kinds_absent` cannot
        # express because it only fires when a kind produced nothing at all.
        envelope["kinds_unparsed"] = dict(sorted(kinds_unparsed.items()))
    if units:
        envelope["units"] = [asdict(u) if not isinstance(u, dict) else u for u in units]
    else:
        envelope["units"] = None
        envelope["units_absent_reason"] = absent_reason
    path = Path(units_dir) / f"{slug}.json"
    path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    return path


def _reconcile_store(extracts_dir: Path, units_dir: Path, scans: list) -> list:
    """Bring the derived store back in line with the extracts, before anything reads either.

    `materialize` iterates EXTRACTS, so a source whose identity changed leaves its old
    `_bramber/units/<slug>.json` behind and the per-source loop never revisits it. Five readers
    then glob that directory unconditionally — `compile._resolve` among them — so a stale
    envelope projects into a `RESOURCE.md` and its units count as a second contributing source.
    One source corroborating itself across an edit is fabricated attribution, which `specs/07
    §3.2` calls the unrecoverable direction. Invariant 3 ("disk is truth, the DB is rebuildable")
    holds only while disk is CORRECT: an orphan is a disk state no rebuild can detect, because
    the rebuild reads the same orphan.

    Two orphan classes, handled oppositely, because one is derived and the other is authored:

      - a unit envelope is DERIVED and costs one `materialize` to rebuild, so an orphan is
        deleted;
      - a scan is the agent's interpretive read — the one artifact here nobody can regenerate —
        so an orphan scan is REFUSED, never deleted.

    Refusing first is also what makes the deletion safe. The failure mode of a destructive
    reconcile is running it against a half-populated `extracts/` (an interrupted copy, a partial
    ingest) and discarding a live store; in that state most scans are orphaned, so the refusal
    fires before anything is unlinked. The expensive artifact guards the cheap one, so no
    heuristic has to guess whether a small `extracts/` is intentional.

    Ordered before `resolve_keys` on purpose: `read_all` feeds EVERY scan into the ledger,
    including one whose source is gone, so a stranded scan's keys would otherwise enter the
    minted set this run's store and notices are built from. It does **not** close that channel
    corpus-wide — `scan.known_keys` reads the scans directly, so `bramber claims` still publishes
    a stranded key until the scan itself is repaired. Halting here is what forces that repair
    before the next source is scanned against a stale feed.
    """
    live = {f.stem for f in extracts_dir.glob("*.md")} if extracts_dir.exists() else set()

    stranded = sorted((s.path, s.source) for s in scans
                      if s.source and Path(s.source).stem not in live)
    if stranded:
        detail = "\n  ".join(f"{path}  ->  {src}" for path, src in stranded)
        raise SystemExit(
            f"[bramber] materialize: {len(stranded)} scan(s) name a source that is no longer on "
            f"disk:\n  {detail}\n\nA scan is agent-authored interpretive work, so it is never "
            f"deleted here and the run stops instead. Its source was re-ingested under a new "
            f"identity (an edited body changes `content_sha`, hence the slug) or removed "
            f"outright. Either re-point the scan's `source:` at the current extract and "
            f"re-materialize, or delete the scan if that source is gone for good. Continuing "
            f"would drop this source's claims from every view with no other notice — and the "
            f"scan describes text the corpus no longer holds, so it cannot simply be kept.")

    orphans = sorted(f for f in units_dir.glob("*.json") if f.stem not in live)
    for f in orphans:
        f.unlink()
    return [f.stem for f in orphans]


def materialize(data_root, *, trace=None) -> dict:
    """Re-derive `_bramber/units/*.json` from the scans on disk (specs/09).

    The text domain's unit-production step. It is **idempotent and destructive by design**: units
    are derived data, scans are the input, and disk is the source of truth — so this rebuilds
    every source's envelope from scratch rather than merging into what is already there. Merging
    would let a deleted claim survive forever in a file nobody reads.

    Destructive **corpus-wide**, not merely per file: `_reconcile_store` runs first and removes
    every envelope whose extract is gone. Without it the per-source loop, which iterates extracts,
    could only ever overwrite — never retire — and the docstring above was true of each file while
    false of the directory.

    Always corpus-wide, never scoped: the unit store is shared by every view, so a scoped
    rewrite would silently truncate what the other views read. (The old `--view` scope did
    exactly that — reproduced 2026-08-07 — and is gone with the per-view digest itself.)

    Runs per-source, so what lands on disk stays "what THIS source asserted". Corroboration
    across sources is counted later, at selection — see `compile.select_units`.
    """
    from bramber import scan as scan_mod

    trace = trace or _trace.NULL_TRACE
    data_root = Path(data_root).resolve()
    extracts_dir = data_root / "_bramber" / "extracts"
    units_dir = data_root / "_bramber" / "units"
    units_dir.mkdir(parents=True, exist_ok=True)

    step = trace.step("materialize", "Read every scan and re-derive the units each source "
                                     "contributes. Claims repeated within one source collapse "
                                     "here; across sources they are counted, not collapsed.")

    scans = scan_mod.read_all(data_root)
    # The pre-run reconcile: refuse a stranded scan, retire an orphaned envelope. Ahead of
    # `by_source`, `resolve_keys` and every write, so neither orphan class can reach the ledger
    # or the store. → work/findings/2026-08-12-materialize-orphans-and-the-bare-key-notice.md §F1
    orphans_removed = _reconcile_store(extracts_dir, units_dir, scans)
    if orphans_removed:
        # One line, with the count. The store is corrected by the time this prints, so it is a
        # record of a repair rather than a defect report — but it is still a corpus-wide deletion
        # and nothing else would say it happened.
        print(f"[bramber] {len(orphans_removed)} orphaned unit envelope(s) removed: their source "
              f"is no longer in `_bramber/extracts/`, and every reader of the unit store "
              f"(`compile` included) globs that directory unconditionally.", file=sys.stderr)

    by_source: dict[str, list] = {}
    for s in scans:
        if s.source:
            by_source.setdefault(s.source, []).append(s)
    step.inputs["scans read"] = len(scans)
    step.inputs["orphaned envelopes removed"] = len(orphans_removed)

    # source_type per slug, off the extract header — the reliability tier is assigned by source
    # class from a fixed table, never chosen by the adapter or derived from the content.
    source_type_by_slug: dict[str, str] = {}
    if extracts_dir.exists():
        for f in sorted(extracts_dir.glob("*.md")):
            fields, _, _ = db.split_frontmatter(f.read_text(encoding="utf-8"))
            source_type_by_slug[f.stem] = fields.get("source_type") or ""

    # Before anything merges: no two sources may share a key namespace. Checked here because
    # this is the one place that sees every extract at once, and because a violation must stop
    # the run rather than produce a store whose support counts are wrong for two sources.
    all_extracts = [f"_bramber/extracts/{f.name}"
                    for f in (sorted(extracts_dir.glob("*.md")) if extracts_dir.exists() else [])]
    scan_mod.check_srcref_uniqueness(all_extracts)
    # ONE corpus-wide classification, computed here and passed down. Whether a key is a reuse
    # depends on what other sources minted, so it cannot be decided per source — and deciding it
    # twice (once for the feed, once for the store) is how the publish→copy round trip breaks.
    keys = scan_mod.resolve_keys(scans, all_extracts)
    ambiguous, unresolvable = keys.ambiguous, keys.unresolvable

    written, total = 0, 0
    legacy_kinds: set[str] = set()
    lost_sources: set[str] = set()
    truncated_sources: set[str] = set()
    for f in sorted(extracts_dir.glob("*.md")) if extracts_dir.exists() else []:
        slug = f.stem
        extract_rel = f"_bramber/extracts/{slug}.md"
        source_scans = by_source.get(extract_rel, [])
        units = scan_mod.units_for_source(source_scans, source_type_by_slug, keys=keys)
        # A kind is only reported absent if it produced nothing here. One source normally has one
        # scan now, but the loop does not assume it: a kind found by any scan of this source is a
        # finding, and another scan's silence must not mask it.
        kinds_absent: dict[str, str] = {}
        produced_kinds = {u.kind for u in units}
        for sc in source_scans:
            for kind, why in (sc.kinds_absent or {}).items():
                if kind not in produced_kinds:
                    kinds_absent.setdefault(kind, why)
        if any("predates the machine-readable block" in w for w in kinds_absent.values()):
            legacy_kinds.add(slug)
        # Lines inside a parsed section that matched nothing — counted whether or not the kind
        # produced units, because the case worth seeing is the section that yielded two bullets of
        # three. A whole-section absence reason cannot express that, and a partial loss is the
        # likelier one: the author is a language model writing markdown.
        kinds_unparsed: dict[str, dict] = {}
        for sc in source_scans:
            for kind, counts in (sc.kinds_unparsed or {}).items():
                acc = kinds_unparsed.setdefault(kind, {"lost": 0, "truncated": 0})
                acc["lost"] += counts.get("lost", 0)
                acc["truncated"] += counts.get("truncated", 0)
        if any(c["lost"] for c in kinds_unparsed.values()):
            lost_sources.add(slug)
        if any(c["truncated"] for c in kinds_unparsed.values()):
            truncated_sources.add(slug)
        write_units_envelope(
            units_dir, slug, extract_rel, slug, units,
            produced_by="bramber.scan (agent-authored scans)",
            absent_reason=("no scan for this source asserts any claim — it is either not yet "
                           "scanned, or was scanned and marked discarded"),
            kinds_absent=kinds_absent,
            kinds_unparsed=kinds_unparsed,
        )
        written += 1
        total += len(units)
        step.row("ok" if units else "empty", slug, group=slug,
                 detail=f"{len(units)} unit(s)" if units else None,
                 reason=None if units else "no claims from this source's scan")

    step.outputs["sources written"] = written
    step.outputs["units materialized"] = total
    if legacy_kinds:
        step.outputs["sources with prose-only sections"] = len(legacy_kinds)
    if lost_sources:
        step.outputs["sources with a malformed item bullet (no unit)"] = len(lost_sources)
    if truncated_sources:
        step.outputs["sources with a truncated item (unit missing fields)"] = len(truncated_sources)
    step.close()

    if legacy_kinds:
        # Visible, countable, non-fatal. A scan is agent prose, so an unrecognised section takes
        # the prose rule and yields nothing — but bare silence here would read as "this corpus has
        # no entities and no contradictions", which is a conclusion nobody drew and the corpus
        # cannot support. Saying it once per run is the difference between a migration and a
        # finding.
        print(f"[bramber] {len(legacy_kinds)} source(s) carry scans whose Entities / "
              f"Contradictions / Novel Concepts sections are prose-only — no units of those kinds "
              f"were materialized from them. Per-source reasons are in each envelope's "
              f"`kinds_absent`.", file=sys.stderr)

    # The bare-key notice is RETIRED (2026-08-12). `ambiguous` is still computed and still
    # returned below — it costs nothing and the merge-precision eval measures against it — but
    # it is no longer reported, here or in `hygiene`.
    #
    # It was a MIGRATION guard: before namespacing, a bare key repeated across sources meant
    # corroboration and merged, so a repeat was a decision someone had to make. Its own founding
    # record states that on the day it was written no corpus had been scanned under this pipeline
    # (the 2026-08-07 ruling "keys are minted in a source owned namespace"), so the population it
    # guarded was empty then and has stayed empty.
    #
    # After namespacing the grouping key kept its shape and lost its meaning. FORMAT-SPEC tells
    # every scan to number from 1, so sources share ordinals BY CONSTRUCTION and the bucket
    # re-derives the claims-per-source histogram: on the first real corpus (27 sources) it was a
    # monotone staircase, 30 keys over 544 (key, source) pairs, 46,623 characters — printed third
    # of ten notices, larger by itself than the window the seven after it needed to be read in.
    # Those seven are every row of `orchestrate.md`'s notice table, which the orchestrator is
    # required to report and which say a skipped notice is a defect that ships silently.
    #
    # The residual hazard — an author who MEANT corroboration and wrote bare — is not lost with
    # it. That is a semantic question and `hygiene`'s near-duplicate merge queue is the instrument
    # for it; grouping by ordinal never could be, because the ordinal is orthogonal to the mistake.
    # → decisions/2026-08-12-the-bare-key-notice-is-retired.md

    def _key_lines(bucket):
        return "\n".join(
            f"    {key!r} written by: {', '.join(srcs)}"
            + (f"\n      -> its witness matches {keys.suggestions[key]!r} — if that was the "
               f"intent, re-copy that reuse_as" if key in keys.suggestions else "")
            for key, srcs in sorted(bucket.items()))

    if unresolvable:
        # A reuse that resolved to nothing. It becomes an ordinary independent claim carrying
        # support 1 — the exact opposite of what writing a qualified key was meant to do — and
        # nothing else would ever say so.
        print(f"[bramber] {len(unresolvable)} key(s) look like a reuse but resolve to nothing "
              f"this corpus minted:\n{_key_lines(unresolvable)}\n"
              f"  A reuse must name a key some source actually minted — either the 8-hex "
              f"namespace names no source here, or it names one that never minted that number. "
              f"Each was treated as an INDEPENDENT claim in its author's own namespace, so it "
              f"corroborates nothing and cannot merge with another copy of the same mistake. If "
              f"one of these was meant as a corroboration, re-copy the `reuse_as` token from "
              f"`bramber claims`. If it was genuinely a new claim that happens to look "
              f"namespaced, nothing is wrong and this notice is the confirmation.",
              file=sys.stderr)

    if keys.unwitnessed:
        # The key resolves; the endorsement quotes nothing. Merging on it would reopen the
        # wrong-minted-key hole for exactly the keys where it matters, so it was refused.
        print(f"[bramber] {len(keys.unwitnessed)} reuse(s) name a minted key but carry no "
              f"witness:\n{_key_lines(keys.unwitnessed)}\n"
              f"  A reuse is an endorsement, and an endorsement must quote what it endorses: "
              f"copy the full `reuse_as` token from `bramber claims` (`KEY=xxxxxx`), not the key "
              f"alone. A bare key one slip away from a NEIGHBOURING real key would corroborate "
              f"the wrong claim with no error anywhere — the witness is what makes that "
              f"impossible. Each of these was kept as an INDEPENDENT claim in its author's own "
              f"namespace; re-copy the token to record the corroboration.", file=sys.stderr)

    if keys.witness_mismatch:
        # THE misdirection case: without the witness these would have merged silently onto the
        # wrong claim — fabricated support, undetectable from the artifact.
        print(f"[bramber] {len(keys.witness_mismatch)} reuse(s) carry a witness that does NOT "
              f"match the statement their key names:\n{_key_lines(keys.witness_mismatch)}\n"
              f"  The key and the witness were copied from different feed rows, or the key "
              f"slipped onto a neighbouring mint. Without the witness this would have merged "
              f"silently onto the wrong claim; instead each was kept as an INDEPENDENT claim in "
              f"its author's own namespace. Re-copy the intended `reuse_as` token whole.",
              file=sys.stderr)

    if keys.lost_endorsement:
        # The fifth loudness bucket, and the only one whose subject is a key the corpus REALLY
        # minted. `stray_witness` deliberately stays return-only (a witness on a genuinely new
        # key costs nothing); this one reaches stderr because a corroboration the ledger
        # declined to record is the failure the product is sold against.
        # → decisions/2026-08-10-a-key-that-cannot-round-trip-is-never-published-as-reusable.md
        print(f"[bramber] {len(keys.lost_endorsement)} endorsement(s) named a key this corpus "
              f"MINTED and were still dropped:\n{_key_lines(keys.lost_endorsement)}\n"
              f"  A verbatim copy was re-stamped into the endorser's own namespace instead of "
              f"merging, so the support is not recorded. Since `_stamp` became total every stored "
              f"key carries a readable namespace, so this should be UNREACHABLE — reaching it "
              f"means a stored key was produced that its own reader classifies as a fresh mint. "
              f"Report it; do not repair it by editing the scan.", file=sys.stderr)

    if keys.key_collisions:
        # Not a degrade: both claims survive, distinct, exactly as authored. It reaches stderr
        # because the stored key is no longer the natural image of the authored one — the agent
        # wrote two keys one character apart, and the next reader of that scan should not have to
        # deduce from a stored key why it grew a segment.
        # → decisions/2026-08-11-stamp-is-made-total-the-migration-premise-was-false.md
        print(f"[bramber] {len(keys.key_collisions)} hyphen-free key(s) collided with another key "
              f"of the same source and had their sentinel segment escalated:\n"
              f"{_key_lines(keys.key_collisions)}\n"
              f"  Both claims are intact and distinct — nothing merged. Give the hyphen-free key "
              f"an explicit number (`FINDING` -> `FINDING-002`) so its stored key is the ordinary "
              f"stamp of what you wrote, then re-materialize.", file=sys.stderr)

    # Two notices, because they are two different facts and one sentence covering both is false
    # for whichever it does not name. An operator told "produced no unit" who then finds every
    # item present concludes the warning was noise — and stops reading the next one.
    if lost_sources:
        print(f"[bramber] {len(lost_sources)} source(s) carry a malformed item bullet — those "
              f"items produced NO unit. Likely a dropped `**` or `:` where `—` belongs. Per-kind "
              f"counts are in each envelope's `kinds_unparsed.lost`.", file=sys.stderr)

    if truncated_sources:
        print(f"[bramber] {len(truncated_sources)} source(s) carry an item with a line the parser "
              f"could not place — those items DID produce a unit, missing every field after that "
              f"line. Likely a field value wrapped onto a second line, or a nested sub-list. The "
              f"unit is real but under-populated, so a view selecting on a missing field will "
              f"silently exclude it. Per-kind counts are in each envelope's "
              f"`kinds_unparsed.truncated`.", file=sys.stderr)

    # Topics carried by exactly one source. Not an error and not stderr — telemetry. A topic is
    # itself an identity with no mint-or-reuse feed (specs/09 §7 accepts a synonym split as a
    # discipline cost), so the singleton list is the cheapest drift signal available: a synonym
    # split manufactures singletons, and a reader scanning this list sees the near-misses that a
    # per-scan author never can.
    topic_sources: dict[str, set] = {}
    for uf in sorted(units_dir.glob("*.json")):
        env = json.loads(uf.read_text(encoding="utf-8"))
        for u in (env.get("units") or []):
            for t in (u.get("payload") or {}).get("topics") or []:
                topic_sources.setdefault(str(t), set()).add(env.get("extract_path"))
    singleton_topics = sorted(t for t, srcs in topic_sources.items() if len(srcs) == 1)

    return {"sources": written, "units": total, "legacy_section_sources": sorted(legacy_kinds),
            "orphans_removed": orphans_removed,
            "lost_sources": sorted(lost_sources),
            "truncated_sources": sorted(truncated_sources),
            "ambiguous_bare_keys": sorted(f"{k}:{key}" for k, key in ambiguous),
            "unresolvable_keys": sorted(unresolvable),
            "unwitnessed_keys": sorted(keys.unwitnessed),
            "witness_mismatch_keys": sorted(keys.witness_mismatch),
            "stray_witness_keys": list(keys.stray_witness),
            "lost_endorsement_keys": sorted(keys.lost_endorsement),
            "key_collision_keys": sorted(keys.key_collisions),
            "singleton_topics": singleton_topics}


def _slug(ref: str, identity_key: str) -> str:
    """A filesystem-safe, identity-anchored slug for a source's on-disk artifacts.

    `<sanitized ref>__<first 8 of identity key>`. The identity suffix keeps two
    same-named sources (or a renamed-but-same-content source) from colliding.
    """
    base = re.sub(r"[^0-9A-Za-z]+", "_", ref or "").strip("_")
    return f"{base}__{identity_key[:8]}"


def _discover_root(adapter, data_root: Path) -> str:
    """Where the adapter enumerates sources — the bramber data root (its `_bramber/inbox`).

    Kept as a seam rather than inlined: an adapter whose sources live somewhere other than the
    data root declares it with a `discover_root` attribute, and ingest needs no edit. That is
    the shape of the seam, and it survived the withdrawal of the one adapter that used it.
    """
    return getattr(adapter, "discover_root", None) or str(data_root)


def ingest(adapter, data_root, *, run_id=None, trace=None) -> list[dict]:
    """discover -> identity -> normalize -> extract_units for every source; materialize
    each to <data_root>/_bramber/extracts/<slug>.md (+ units json).

    Returns a manifest: [{slug, qname, extract_path, units_path, n_units}].

    Every source is written, even when it yields no units — an unscanned source still
    registers as a source (it was considered); the *view* selection decides what surfaces.

    With `trace` set, the four steps recorded mirror the Adapter Protocol one-for-one
    (discover -> identity -> normalize -> extract_units, then materialize), so the page is
    also a readable account of what this domain's adapter actually did at the seam.
    """
    trace = trace or _trace.NULL_TRACE
    data_root = Path(data_root).resolve()
    extracts_dir = data_root / "_bramber" / "extracts"
    units_dir = data_root / "_bramber" / "units"
    extracts_dir.mkdir(parents=True, exist_ok=True)
    units_dir.mkdir(parents=True, exist_ok=True)

    today = db.now()[:10]
    discover_root = _discover_root(adapter, data_root)

    # Steps are opened once and accrue a row per source as the loop runs, so the page reads
    # as "here is what discover did across every source", not one step-set per source.
    st_discover = trace.step("discover_sources",
                             "The adapter enumerates what exists. bramber never parses a source.")
    st_identity = trace.step("identity", "The adapter computes each source's identity — the "
                                         "dedup key and the staleness anchor.")
    st_normalize = trace.step("normalize", "The adapter renders each source to a domain-blind "
                                           "Extract (markdown body).")
    st_units = trace.step("extract_units", "The adapter extracts Units — the handoff. Never "
                                           "re-derived downstream; views only select over these.")
    st_write = trace.step("materialize", "bramber writes extract + units to disk with the "
                                         "generalized header `bramber sync` later parses.")
    st_discover.inputs["adapter"] = type(adapter).__name__
    st_discover.inputs["discover root"] = discover_root

    # Each adapter call is timed into its own step, so the page reports how long *each
    # phase* took across every source — not the loop's wall clock repeated five times.
    manifest: list[dict] = []
    with st_discover.timing():
        sources = list(adapter.discover_sources(discover_root))
    for src in sources:
        # The WHOLE Source, not a hand-picked summary: a trace that records a subset can
        # only ever show what the recorder thought mattered. Everything the adapter supplied
        # is on the page, so a field the pipeline later drops is visible as a drop.
        src_fields = asdict(src)
        st_discover.row("ok", src.ref, detail=f"type={src.source_type}; title={src.title!r}",
                        data=src_fields)

        with st_identity.timing():
            ident = adapter.identity(src)
        st_identity.row("ok", src.ref, detail=f"{ident.kind} / {ident.key[:12]}…",
                        data={"kind": ident.kind, "key": ident.key, "data": ident.data})

        with st_normalize.timing():
            ext = adapter.normalize(src)
        st_normalize.row("ok", src.ref, detail=f"{len(ext.body or '')} chars",
                         data={"body": _trace.clip(ext.body)})

        with st_units.timing():
            units = adapter.extract_units(ext)

        # A row per *unit*, grouped under the source that produced it — the whole yield of
        # this source, visible without filtering for it.
        st_units.group(src.ref, source_type=src.source_type, produced=len(units))
        if not units:
            st_units.row("empty", src.ref, group=src.ref,
                         reason="the adapter extracted no units from this source — it is still "
                                "registered (it was considered), but projects nothing")
        for u in units:
            d = asdict(u)
            payload = d.get("payload", {})
            # No payload field is named here: ingest does not know what any domain calls its
            # subject, and guessing one is how the old projection rendered blank bullets. The
            # whole unit is on the trace page as `data`, which is strictly more informative.
            st_units.row(
                "ok", src.ref, tag=u.kind, group=src.ref, data=d,
            )

        slug = _slug(src.ref, ident.key)
        extract_rel = f"_bramber/extracts/{slug}.md"
        units_rel = f"_bramber/units/{slug}.json"

        with st_write.timing():
            # One value per declared header field. `header.render` raises unless this dict
            # covers the declaration exactly, so a field added on the engine's side breaks
            # ingest *here* instead of quietly indexing NULL. That inversion is the point of
            # specs/06 T1.1: the writer no longer carries its own list of keys, and the
            # channel between adapter and engine has one definition rather than two that
            # happen to agree until someone edits one of them.
            header = header_schema.render({
                "identity_kind":  ident.kind,
                "identity_key":   ident.key,
                "identity_json":  json.dumps(ident.data),
                "source_type":    src.source_type,
                "title":          src.title,
                "source_url":     src.url,
                "author":         src.author,
                "date_published": src.date_published,
                "date_ingested":  today,
            })
            (extracts_dir / f"{slug}.md").write_text(
                "\n".join(header) + (ext.body or "").rstrip("\n") + "\n",
                encoding="utf-8",
            )

            write_units_envelope(
                units_dir, slug, extract_rel, src.ref, units,
                produced_by=f"{type(adapter).__name__}.extract_units",
                absent_reason=(
                    f"{type(adapter).__name__}.extract_units returned no units for this source; "
                    f"it is registered as a source and projects into no view. For text this is "
                    f"expected at ingest — extraction is interpretive, so units are materialized "
                    f"later from the agent's scan (`bramber materialize`)."
                ),
            )

        st_write.row("ok", src.ref, detail=f"{extract_rel} + {units_rel}",
                     data={"header": header, "slug": slug})

        manifest.append({
            "slug": slug,
            "qname": src.ref,
            "extract_path": extract_rel,
            "units_path": units_rel,
            "n_units": len(units),
        })

    n_units = sum(m["n_units"] for m in manifest)
    st_discover.outputs["sources discovered"] = len(manifest)
    st_identity.outputs["identity kinds"] = sorted({r["data"]["kind"] for r in st_identity.rows})
    st_units.outputs["units extracted"] = n_units
    st_units.outputs["sources yielding no units"] = sum(1 for m in manifest if not m["n_units"])
    st_units.note("Units are the handoff: extracted once, view-agnostically, and never "
                  "re-derived. Every view downstream only *selects* over exactly these.")
    st_write.outputs["extracts dir"] = str(extracts_dir)
    st_write.outputs["units dir"] = str(units_dir)
    st_write.note("`bramber sync` reconstructs the index from these headers with no adapter "
                  "import — that is what keeps the engine domain-blind.")
    for st in (st_discover, st_identity, st_normalize, st_units, st_write):
        st.close()

    return manifest
