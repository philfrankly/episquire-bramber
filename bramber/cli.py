"""bramber CLI — thin wrapper over the engine + the ingest/compile front half.

  bramber init     --root <project>                          # create bramber.db (if absent) then sync
  bramber sync     --root <project>                          # reconcile the index from the .md tree (Stop hook uses this)
  bramber serve-retrieval --root <project>                   # the sibling MCP server: search_units/contradictions_for/expand ([mcp]+[embed])
  bramber rebuild  --root <project>                          # delete bramber.db and recreate from disk
  bramber serve    --root <project>                          # launch the read-only MCP server (needs the [mcp] extra)
  bramber stale    --root <project>                          # mark resources stale whose sources changed (not yet implemented)
  bramber ingest   --root <project>                          # inbox -> _bramber/extracts (+ empty unit envelopes)
  bramber claims   --root <project>                          # the mint-or-reuse feed: full universe, or --like/--pack shortlists ([embed])
  bramber contradictions --for <key> --root <project>        # every recorded tension citing a stored key (sides flagged, never dropped)
  bramber materialize --root <project>                       # scans -> _bramber/units (the text domain's unit producer)
  bramber index    --root <project>                          # build/update the candidate index (needs the [embed] extra; --status is stdlib)
  bramber hygiene  --root <project>                          # file store-hygiene proposals to _bramber/evaluations/ (never auto-applied)
  bramber select   --view <slug> --root <project>            # the units a view projects, as JSON (the agent's Mode-2 feed)
  bramber meta-select --view <slug> --root <project>         # a meta view's ```feed blocks: the corpus read as a whole
  bramber compile  --view <slug> --root <project>            # project units through a view -> RESOURCE.md v+1 + lineage
  bramber intake   --root <project>                          # browser intake form (port 47825) -> _bramber/inbox/
  bramber status   --view <slug> --root <project>            # what's ingested/scanned/authored vs pending (resume aid)

The pipeline is `ingest -> scan (agent) -> materialize -> compile`. A source is scanned ONCE,
view-agnostically, for anything claim-shaped; `materialize` turns the scans' graded Claims into
the shared unit store; every view is a cheap, re-runnable selection over that store.

`ingest`, `materialize`, `select` and `compile` accept `--trace`: record every step's inputs and outputs to
`_bramber/traces/<ts>-<cmd>.{json,html}` and print the page path. The page shows, per step, what
went in, what came out, and — for `select` — the predicate that rejected each unit that did not
make it into the resource. Off by default and free when off.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bramber import meta as meta_mod
from bramber.engine import db


def _report_trace(tr, args) -> None:
    """Write the trace (if `--trace` was set) and point at the page.

    On **stderr**: `bramber select` writes JSON to stdout, so a notice there would break
    `bramber select --view x | jq`. A trace is a side-channel about the run, not its output.
    """
    if not tr.enabled:
        return
    page = tr.save(out_dir=getattr(args, "trace_dir", None))
    print(f"[bramber] trace: {page}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bramber", description="bramber knowledge-compilation engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_root(p):
        p.add_argument("--root", help="project data root (default: $BRAMBER_ROOT or cwd)")
        p.add_argument("--db", help="path to bramber.db (default: <root>/bramber.db or $BRAMBER_DB)")
        return p

    def with_trace(p):
        p.add_argument("--trace", action="store_true",
                       help="record each step's inputs/outputs to _bramber/traces/<ts>-<cmd>.html "
                            "(+ .json) and print the page path")
        p.add_argument("--trace-dir", help="write the trace elsewhere (default: <root>/_bramber/traces)")
        return p

    for cmd in ("init", "sync", "rebuild", "serve", "serve-retrieval", "stale", "intake"):
        with_root(sub.add_parser(cmd))

    with_trace(with_root(sub.add_parser("ingest")))

    # The feed's three shapes (specs/11 G8): no flag = the full universe; --like = ~10
    # nearest candidates for one draft statement; --pack = the pre-scan candidate pack for
    # one extract. One row shape everywhere; [embed]-absent or index-absent degrades to the
    # full feed with a stderr notice, never an error.
    p_claims = with_root(sub.add_parser("claims"))
    p_claims.add_argument("--like", metavar="STATEMENT",
                          help="Shape A: the nearest candidate keys for one draft claim "
                               "statement (needs the [embed] extra and a built index)")
    p_claims.add_argument("--pack", metavar="EXTRACT_REL",
                          help="Shape B: the pre-scan candidate pack for one extract, e.g. "
                               "_bramber/extracts/<slug>.md (needs [embed] and an index)")

    # `--for` is required: the primitive is "the tensions citing THIS key". The whole register
    # is already served by `meta-select --feed contradictions`; two documents do not share a
    # command distinguished by an absent flag.
    p_contra = with_root(sub.add_parser("contradictions"))
    p_contra.add_argument("--for", dest="for_key", required=True, metavar="KEY",
                          help="stored key as `bramber claims` prints it (e.g. "
                               "CLAIM-a3f21c04-007) whose citing tensions to serve")

    with_trace(with_root(sub.add_parser("materialize")))

    # The candidate index (specs/10 §4.1, specs/11 G8). `--status` is answerable stdlib-only;
    # build needs the [embed] extra and says so rather than degrading to a partial index.
    p_index = with_root(sub.add_parser("index"))
    p_index.add_argument("--rebuild", action="store_true",
                         help="discard the cache and re-embed everything (a changed embed "
                              "model does this implicitly)")
    p_index.add_argument("--status", action="store_true",
                         help="report coverage vs the unit store without building anything")

    p_select = with_trace(with_root(sub.add_parser("select")))
    p_select.add_argument("--view", required=True, help="view slug whose selected units to print")

    # A separate subcommand, not `select --all-views`. `select --view` is required, and that
    # requirement IS the contract "the exact set this view projects". Making it optional would put
    # two different documents behind one command distinguished by an absent flag.
    p_meta = with_trace(with_root(sub.add_parser("meta-select")))
    p_meta.add_argument("--view", help="meta view slug whose ```feed blocks to run (the "
                                       "versioned, human-gated form)")
    p_meta.add_argument("--feed", choices=meta_mod.JOIN_MODES,
                        help="run one feed ad hoc, without a view.md. For exploration only — a "
                             "document built this way has its definition in a shell history")
    p_meta.add_argument("--kind", help="unit kind (--feed units)")
    p_meta.add_argument("--dedup-by", help="payload field to merge on (--feed units)")
    p_meta.add_argument("--order-by", help="payload field to sort on (--feed units)")
    p_meta.add_argument("--project", help="comma-separated payload fields to render (--feed units)")

    p_compile = with_trace(with_root(sub.add_parser("compile")))
    p_compile.add_argument("--view", required=True, help="view slug to compile")
    p_compile.add_argument("--resource", default="overview", help="resource slug (default: overview)")

    # The store's hygiene sweep (specs/10 §5.2). Output is proposal FILES for the
    # /bramber:evaluate gate — the command never applies anything, so it takes no flags that
    # could be mistaken for a decision.
    with_root(sub.add_parser("hygiene"))

    p_status = with_root(sub.add_parser("status"))
    p_status.add_argument("--view", help="restrict to one view slug (default: all views)")
    p_status.add_argument("--json", action="store_true", help="emit the status object as JSON")

    args = ap.parse_args(argv)

    db.configure(root=args.root, db=args.db)

    if args.cmd in ("init", "sync", "rebuild"):
        if args.cmd == "rebuild" and db.DB_PATH.exists():
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(db.DB_PATH) + suffix)
                if p.exists():
                    p.unlink()
        counts = db.sync_from_disk()
        action = {"init": "initialized", "sync": "synced", "rebuild": "rebuilt"}[args.cmd]
        print(f"[bramber] {action} {db.DB_PATH}")
        print("[bramber] " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    elif args.cmd == "ingest":
        from bramber import trace as tracing
        from bramber.ingest import ingest, make_adapter
        tr = tracing.make(args.trace, "ingest", db.ROOT, {"adapter": "text"})
        manifest = ingest(make_adapter("text"), db.ROOT, trace=tr)
        print(f"[bramber] ingested {len(manifest)} source(s) -> "
              f"{db.ROOT / '_bramber' / 'extracts'}")
        print("[bramber] Run `bramber sync` to index. Units come from scans — write those, "
              "then `bramber materialize`.")
        _report_trace(tr, args)

    elif args.cmd == "claims":
        import json
        from bramber import scan as scan_mod
        # `is not None`, never truthiness: `--like ""` is a present (if empty) query, and
        # treating it as absent served the full feed with no notice — a silent degrade in
        # exactly the place notices exist (screen finding F3).
        if args.like is not None and args.pack is not None:
            raise SystemExit("[bramber] claims: pass at most one of --like / --pack — one "
                             "query per call, so the shown-candidate record stays attributable.")
        use_shortlist = args.like is not None or args.pack is not None
        if use_shortlist:
            from bramber import index as index_mod  # lazy: cli import graph stays stdlib-only
            if not index_mod.embed_available():
                # G7: the degrade is exact — full feed, no retrieval, no error. The notice
                # names why, because a full feed that was asked for a shortlist should say so.
                print("[bramber] claims: the [embed] extra is not installed — serving the "
                      "full feed instead. Same rows, same discipline; only recall differs. "
                      "`pip install bramber[embed]` to enable the shortlist.", file=sys.stderr)
                use_shortlist = False
            elif index_mod.load(db.ROOT) is None:
                print("[bramber] claims: no usable index on disk (missing, unreadable, or an "
                      "older index version) — serving the full feed instead. Run "
                      "`bramber index` to enable the shortlist.", file=sys.stderr)
                use_shortlist = False
        if use_shortlist and args.like is not None:
            print(json.dumps(scan_mod.feed_like(db.ROOT, args.like), indent=2))
        elif use_shortlist:
            print(json.dumps(scan_mod.feed_pack(db.ROOT, args.pack), indent=2))
        else:
            # The full feed. Every agent-assigned key, grouped by kind. `claims` stays the
            # top-level key for the readers that already parse it; `keys` carries the rest. A
            # kind that merges on a key must appear here or an agent has no way to know the
            # key is taken — see `scan.known_keys`.
            known = scan_mod.known_keys(db.ROOT)
            print(json.dumps({
                "count": len(known),
                "claims": [{"claim_key": e["key"], "statement": e["statement"],
                            "sources": e["sources"], "reuse_as": e["reuse_as"],
                            # Null `reuse_as` means this claim cannot be endorsed by copying a
                            # token; the reason travels with it so the agent is never left to
                            # infer that the field is simply missing.
                            "no_reuse_reason": e.get("no_reuse_reason")}
                           for e in known if e["kind"] == "claim"],
                "keys": known,
                "topics": scan_mod.topic_vocabulary(db.ROOT),
            }, indent=2))

    elif args.cmd == "contradictions":
        import json
        print(json.dumps(meta_mod.contradictions_for(db.ROOT, args.for_key), indent=2))

    elif args.cmd == "materialize":
        from bramber import trace as tracing
        from bramber.ingest import materialize
        tr = tracing.make(args.trace, "materialize", db.ROOT, {})
        res = materialize(db.ROOT, trace=tr)
        print(f"[bramber] materialized {res['units']} unit(s) across {res['sources']} source(s) "
              f"from scans")
        _report_trace(tr, args)

    elif args.cmd == "index":
        import json
        from bramber import index as index_mod  # lazy: the cli import graph stays stdlib-only
        if args.status:
            print(json.dumps(index_mod.status(db.ROOT), indent=2))
        else:
            res = index_mod.build(db.ROOT, rebuild=args.rebuild)
            print(f"[bramber] index: {res['entries']} entr(ies) over {res['envelopes']} "
                  f"envelope(s); embedded {res['embedded']}, reused {res['reused_vectors']} "
                  f"vector(s)"
                  + (f"; dropped {len(res['removed_envelopes'])} removed envelope(s)"
                     if res['removed_envelopes'] else ""))

    elif args.cmd == "hygiene":
        from bramber import hygiene as hygiene_mod  # lazy, though stdlib throughout
        res = hygiene_mod.sweep(db.ROOT)
        q = res["queues"]
        print(f"[bramber] hygiene: filed {len(res['proposals_filed'])} proposal(s) "
              f"(merge {q['merge']}, topic {q['topic']}, alias {q['alias']}, "
              f"ledger {q['ledger']}); {res['skipped_existing']} already examined")
        for p in res["proposals_filed"]:
            print(f"  {p}")
        for note in res["notes"]:
            print(f"[bramber] hygiene: {note}", file=sys.stderr)
        if res["proposals_filed"]:
            print("[bramber] Nothing was applied. Rule on the queue with /bramber:evaluate.")

    elif args.cmd == "status":
        import json
        from bramber import run
        s = run.status(db.ROOT, view=args.view)
        print(json.dumps(s, indent=2) if args.json else run.format_status(s))

    elif args.cmd == "select":
        import json
        from bramber import trace as tracing
        from bramber.compile import selection_for_view
        tr = tracing.make(args.trace, "select", db.ROOT, {"view": args.view})
        sel = selection_for_view(db.ROOT, args.view, trace=tr)
        print(json.dumps(sel, indent=2))
        _report_trace(tr, args)

    elif args.cmd == "meta-select":
        import json
        from bramber import trace as tracing
        if bool(args.view) == bool(args.feed):
            raise SystemExit(
                "[bramber] meta-select: pass exactly one of --view (run the ```feed blocks the "
                "view.md declares — versioned, human-gated, view_version stamped) or --feed (one "
                "feed ad hoc). Both, or neither, is ambiguous.")
        tr = tracing.make(args.trace, "meta-select", db.ROOT,
                          {"view": args.view, "feed": args.feed})
        if args.view:
            out = meta_mod.run_feeds(db.ROOT, args.view, trace=tr)
        elif args.feed == "sources":
            out = meta_mod.source_spine(db.ROOT, trace=tr)
        elif args.feed == "topics":
            out = meta_mod.topic_register(db.ROOT)
        elif args.feed == "contradictions":
            out = meta_mod.contradiction_register(db.ROOT, trace=tr)
        elif args.feed == "per-view":
            out = meta_mod.selections_by_view(db.ROOT, trace=tr)
        else:
            missing = [f"--{k.replace('_', '-')}" for k in
                       ("kind", "dedup_by", "order_by", "project") if not getattr(args, k)]
            if missing:
                raise SystemExit(
                    f"[bramber] meta-select --feed units needs {', '.join(missing)}. These have "
                    f"no defaults on purpose — a default would join on whatever field happened "
                    f"to exist and render the result as though it had been asked for.")
            out = meta_mod.select_across(
                db.ROOT, kind=args.kind, dedup_by=args.dedup_by, order_by=args.order_by,
                project=[f.strip() for f in args.project.split(",") if f.strip()], trace=tr)
        print(json.dumps(out, indent=2))
        _report_trace(tr, args)

    elif args.cmd == "compile":
        from bramber import trace as tracing
        from bramber.compile import compile_view
        tr = tracing.make(args.trace, "compile", db.ROOT,
                          {"view": args.view, "resource": args.resource})
        res = compile_view(db.ROOT, args.view, resource_slug=args.resource, trace=tr)
        if res.get("created"):
            print(f"[bramber] compiled {args.view}/{args.resource} -> version {res['version_num']}")
        else:
            print(f"[bramber] {args.view}/{args.resource} unchanged "
                  f"(version {res['version_num']}, no-op)")
        _report_trace(tr, args)

    elif args.cmd == "serve":
        import asyncio
        from bramber.engine import server  # imports `mcp`; needs the [mcp] extra
        asyncio.run(server.main())

    elif args.cmd == "serve-retrieval":
        import asyncio
        from bramber import retrieval_server  # imports `mcp`; the tools need [embed] too
        retrieval_server.ROOT = db.ROOT  # --root wins over the env default, like everywhere
        asyncio.run(retrieval_server.main())

    elif args.cmd == "intake":
        from bramber import intake_server  # stdlib-only; runs until Done/idle-timeout
        intake_server.main(root=db.ROOT)

    elif args.cmd == "stale":
        print("bramber stale: not yet implemented (see specs/00 §6, specs/01 §9)", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
