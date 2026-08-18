"""bramber hygiene — the index pointed inward: nomination queues, one human gate.

Canonical spec: `specs/10-retrieval-over-the-claim-store.md` §5.2, as ruled by
`specs/11-retrieval-over-the-witnessed-ledger.md` M5.

**Every output is a proposal file; nothing is ever applied.** The sweep points the same
machinery that shortlists candidates at the store itself, and files what it finds as
evaluation proposals (`_bramber/evaluations/`, FORMAT-SPEC shape) for `/bramber:evaluate` —
the one human gate. The nominate/decide/assert boundary holds with no exception here: a
similarity score may *nominate* a pair for examination; only a human ruling decides; and an
approved merge becomes real through the ledger's own repair doctrine — **one token edit**
(the operator picks the mint that survives; the other minter's bullet key becomes the
survivor's `reuse_as`) in one scan, then `materialize`.
Nothing in this module writes a scan, a unit, or a view.

Four queues:

  - **merge proposals** — near-duplicate claim pairs: high similarity, distinct keys. Scored
    from the index's stored vectors (no embedding call — the vectors were paid for at build)
    plus the stdlib keyword half. The residual risk of the shortlist regime is the missed
    candidate that becomes a near-duplicate mint; this queue is where those get caught late
    instead of never.
  - **topic drift** — `specs/09` §7 defers a tag registry "until drift is observed"; this is
    the observer. Candidate pairs are token-overlapping tags where at least one side is a
    singleton (carried by exactly one source) — a synonym split manufactures singletons, so
    the singleton list is the pre-filter that keeps the queue short and the finding real.
  - **alias suggestions** — two entity keys sharing a name token and a topic propose an
    `aliases` folding. `_norm_key` stays deliberately dumb; this queue is where the
    under-merges it accepts get examined instead of merely tolerated.
  - **ledger telemetry** — the degrade buckets `resolve_keys` already computes (unresolvable
    / unwitnessed / witness-mismatch reuses, lost endorsements, stray witnesses). Each is a
    probable intended corroboration that landed on the safe side; the
    proposal names the one-token repair, with the resolver's own suggestion when the witness
    identifies the intended mint.

A situation once filed is never re-filed — a rejected proposal is itself a record that the
pair was examined, and re-raising it every sweep would train the operator to stop reading
the queue. Identity is the `subject:` frontmatter key, checked against every existing
proposal regardless of status; for ledger repairs the subject names the key AND the sources
making the mistake, so a NEW source repeating an examined mistake is a new situation and
files.

Two bounds, accepted knowingly rather than hidden: **concurrent sweeps race** on the
read-existing-subjects-then-write sequence — the worst case is a duplicate proposal file,
which is noise an operator sees twice, never a corrupt or silently-missing record (the same
disk-is-truth trade `identity-is-a-ledger` §5.3 accepts for materialize). And the merge
queue's near-dup scan is **all-pairs over claim entries** — deliberate, because a
token-bucket prefilter would miss exactly the disjoint-phrasing paraphrases embeddings
exist to catch; fine to thousands of claims, and the thing to shard when a corpus outgrows
it.

Sits at the compile layer (domain-blind by correction): imports `scan`, `meta`, `index`,
never the engine's internals, and the engine never imports it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from bramber import index as index_mod
from bramber import meta as meta_mod
from bramber import scan as scan_mod
from bramber.engine import db

# Cosine over the index's stored (unit-normalized) claim vectors at or above this nominates a
# merge examination. Deliberately conservative: this queue exists to catch near-duplicate
# MINTS, and a threshold low enough to pair every thematically-adjacent claim would bury the
# real ones. A missed pair here costs nothing that was not already lost at scan time.
NEAR_DUP_THRESHOLD = 0.82
# Or: the keyword half — fraction of the shorter statement's tokens the longer one covers.
NEAR_DUP_TOKEN_THRESHOLD = 0.8

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall((text or "").casefold()))


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


# ---------------------------------------------------------------------------
# the proposal file — the ONLY thing this module writes
# ---------------------------------------------------------------------------

def _evaluations_dir(root) -> Path:
    return Path(root).resolve() / "_bramber" / "evaluations"

def _existing_subjects(root) -> set:
    out = set()
    ev = _evaluations_dir(root)
    if not ev.exists():
        return out
    for f in sorted(ev.glob("*.md")):
        fields, _, _ = db.split_frontmatter(f.read_text(encoding="utf-8"))
        if fields.get("subject"):
            out.add(fields["subject"])
    return out


def _write_proposal(root, queue: str, subject: str, recommendation: str,
                    rationale: str) -> Path:
    ev = _evaluations_dir(root)
    ev.mkdir(parents=True, exist_ok=True)
    today = db.now()[:10]
    n = 1
    while (path := ev / f"{today}-store-{queue}-{n}.md").exists():
        n += 1
    # Write-then-rename, so a crash mid-write leaves no half-proposal that parses as a
    # subject and permanently suppresses the real one (screen finding F7).
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        f"---\n"
        f"scope: store\n"
        f"target: {queue}\n"
        f"subject: {subject}\n"
        f"status: pending\n"
        f"proposed_by: bramber hygiene\n"
        f"created: {today}\n"
        f"---\n\n"
        f"## Recommendation\n{recommendation}\n\n"
        f"## Rationale\n{rationale}\n",
        encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------------------
# the queues
# ---------------------------------------------------------------------------

def _merge_pairs(root) -> list:
    """Near-duplicate claim pairs from the index's stored vectors — distinct final keys whose
    retrieval texts sit close. Two sources that MEANT the same claim and failed to reuse are
    exactly this shape; two sources that reused correctly share a key and never pair."""
    idx = index_mod.load(root)
    if idx is None:
        return []
    claims = [e for e in idx["entries"] if e["kind"] == "claim" and e.get("vector")]
    best: dict = {}
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            if a["key"] == b["key"]:
                continue
            cos = sum(x * y for x, y in zip(a["vector"], b["vector"]))
            ta, tb = _tokens(a["text"]), _tokens(b["text"])
            short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            kw = len(short & long_) / len(short) if short else 0.0
            if cos >= NEAR_DUP_THRESHOLD or kw >= NEAR_DUP_TOKEN_THRESHOLD:
                pair = tuple(sorted((a["key"], b["key"])))
                score = max(cos, kw)
                if score > best.get(pair, 0.0):
                    best[pair] = score
    return sorted(({"keys": list(p), "score": round(s, 4)} for p, s in best.items()),
                  key=lambda d: (-d["score"], d["keys"]))


def _topic_pairs(root, singleton_topics: set) -> list:
    """Token-overlapping tag pairs where at least one side is a singleton — the synonym-split
    shape. The vocabulary is small and the tags are compound words, so token overlap is the
    honest stdlib observer; a pair with no shared token is not observably drifting."""
    vocab = scan_mod.topic_vocabulary(root)
    out = []
    for i, a in enumerate(vocab):
        for b in vocab[i + 1:]:
            if a not in singleton_topics and b not in singleton_topics:
                continue
            j = _jaccard(_tokens(a), _tokens(b))
            if j >= 0.5:
                out.append({"tags": [a, b], "overlap": round(j, 4)})
    return sorted(out, key=lambda d: (-d["overlap"], d["tags"]))


def _alias_pairs(root) -> list:
    """Two entity keys sharing a substantive name token AND a topic. `_norm_key` under-merges
    by design (a wrong merge fabricates attribution); this is where its accepted misses get
    a second look with a human deciding."""
    entities: dict = {}
    for rec in meta_mod.unit_records(root):
        u = rec["unit"]
        if u.get("kind") != "entity":
            continue
        p = u.get("payload") or {}
        key = p.get("entity_key")
        if not key:
            continue
        e = entities.setdefault(key, {"names": set(), "topics": set()})
        e["names"] |= _tokens(p.get("entity_name") or "")
        for alias in p.get("aliases") or []:
            e["names"] |= _tokens(alias)
        e["topics"] |= {str(t) for t in p.get("topics") or []}
    keys = sorted(entities)
    out = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            shared_names = {t for t in entities[a]["names"] & entities[b]["names"]
                            if len(t) > 2}
            shared_topics = entities[a]["topics"] & entities[b]["topics"]
            if shared_names and shared_topics:
                out.append({"keys": [a, b], "shared_names": sorted(shared_names),
                            "shared_topics": sorted(shared_topics)})
    return out


def _minter_scan(key: str, entry: dict) -> Optional[str]:
    """The scan file holding this key's MINT — the source whose namespace the key carries.

    A merge repair edits the minter's bullet, and the minter is readable from the key itself
    (the namespace segment is the minting source's srcref). Endorsers' scans are never the
    edit target: removing an endorsement would drop recorded support, not merge anything.
    """
    ns = scan_mod._namespace_of(key)
    for src in entry.get("sources") or []:
        if scan_mod.srcref_for(src) == ns:
            stem = Path(src).stem
            return f"_bramber/scans/{stem}.md"
    return None


def sweep(data_root) -> dict:
    """Run every queue and file what is new. Returns a summary; writes ONLY proposal files.

    Stdlib end to end: the merge queue reads vectors the index already stores, so a sweep
    costs no embedding call and runs on an install without the `[embed]` extra — with no
    index on disk that one queue is skipped, named in `notes`, and the ledger, topic and
    alias queues run regardless (their inputs are the scans and the unit store).
    """
    root = Path(data_root).resolve()
    existing = _existing_subjects(root)
    filed: list = []
    skipped = 0
    notes: list = []
    counts = {"merge": 0, "topic": 0, "alias": 0, "ledger": 0}

    def file(queue: str, subject: str, recommendation: str, rationale: str) -> None:
        nonlocal skipped
        if subject in existing:
            skipped += 1
            return
        existing.add(subject)
        counts[queue] += 1
        filed.append(str(_write_proposal(root, queue, subject, recommendation, rationale)
                         .relative_to(root)).replace("\\", "/"))

    # Keyed by (kind, key), never by key alone: an agent may author the same key string in
    # two sections, and a flat map would let a contradiction's entry answer for a claim's —
    # the merge rationale would then quote the wrong statement (screen finding F3).
    statements = {(e["kind"], e["key"]): e for e in scan_mod.known_keys(root)}

    # -- merge proposals (index near-dups) --------------------------------------------------
    if index_mod.load(root) is None:
        notes.append("merge queue skipped: no index on disk (run `bramber index`); the "
                     "ledger, topic and alias queues ran normally")
    else:
        behind = index_mod.status(root)["stale"]
        if behind:
            notes.append(f"merge queue ran over a STALE index ({len(behind)} envelope(s) "
                         f"behind the store: {', '.join(behind)}); nominations may lag a "
                         f"repair — run `bramber index` and re-sweep for current pairs")
    for pair in _merge_pairs(root):
        a, b = pair["keys"]
        ea, eb = statements.get(("claim", a)), statements.get(("claim", b))
        if ea is None or eb is None:
            continue  # the index lags a repair; the store is truth
        # BOTH repair tokens, with each mint's own scan named, and NO ordering claim: the
        # pair is string-sorted, and namespaces are content hashes, so "earlier"/"later" is
        # not derivable here — a mislabeled survivor token, applied as instructed, replaces
        # a mint's key with its own token and the approved merge silently records nothing
        # (screen finding F1, reproduced). Which mint survives is the operator's judgment;
        # the proposal's job is to make either choice a correct one-token edit.
        sa = _minter_scan(a, ea) or "the scan of the source whose namespace the key carries"
        sb = _minter_scan(b, eb) or "the scan of the source whose namespace the key carries"
        def _keep(keep_key: str, edit_scan: str, keep_entry: dict) -> str:
            """One direction of the merge, or an honest refusal of it.

            A mint whose stored key publishes no `reuse_as` cannot be the survivor: pasting its
            bare key mints again and the approved merge records nothing — F1's failure arriving
            through a different door. Emitting the token as `None` would instruct exactly that.
            """
            token = keep_entry.get("reuse_as")
            if not token:
                return (f"- to keep `{keep_key}`: **not available** — that key publishes no "
                        f"`reuse_as`. {keep_entry.get('no_reuse_reason') or ''} Keep the other "
                        f"mint instead, or repair this key first.\n")
            return (f"- to keep `{keep_key}`: in `{edit_scan}`, replace the bullet key of the "
                    f"statement quoted below with `{token}`\n")

        file("merge", f"claim-pair {a} {b}",
             f"Rule this pair: merge / keep apart / contradiction. If they are one claim, "
             f"choose the mint that SURVIVES — no mint order is inferred here, and either "
             f"choice is one token edit followed by `bramber materialize`:\n\n"
             + _keep(a, sb, ea) + _keep(b, sa, eb) +
             f"\nIf they disagree, they are a `## Contradictions` entry, not a merge.",
             f"Similarity {pair['score']} between distinct keys — two sources may have meant "
             f"one claim and missed the reuse.\n\n"
             f"- `{a}` ({ea['support']} source(s)): {ea['statement']}\n"
             f"- `{b}` ({eb['support']} source(s)): {eb['statement']}\n\n"
             f"A rejected proposal is itself a record that the pair was examined.")

    # -- ledger telemetry (read-only resolve over the scans) --------------------------------
    scans = [s for s in scan_mod.read_all(root) if not s.discarded and s.source]
    keys = scan_mod.resolve_keys(scans, [s.source for s in scans])

    def _ledger(bucket: dict, what: str, fix: str) -> None:
        for key, sources in sorted(bucket.items()):
            suggestion = keys.suggestions.get(key)
            hint = (f" Its witness matches `{suggestion}` — if that was the intent, the "
                    f"repair is replacing the authored key with that mint's `reuse_as` from "
                    f"`bramber claims`." if suggestion else "")
            # The subject names the key AND the sources making the mistake: a proposal
            # examines a situation, and a NEW source repeating an already-examined mistake
            # is a new situation that must file — a key-only subject would suppress it
            # forever after the first ruling (screen finding F4).
            file("ledger", f"ledger {what} {key} [{', '.join(sorted(sources))}]",
                 f"{fix}{hint} Apply by editing the scan under human gate, then "
                 f"`bramber materialize`.",
                 f"`{key}` written by: {', '.join(sources)}. Each was kept as an independent "
                 f"claim in its author's own namespace — safe, but if a corroboration was "
                 f"meant, that support is currently unrecorded.")

    _ledger(keys.unresolvable, "unresolvable",
            "A reuse-shaped key resolves to nothing this corpus minted — probably a mistyped "
            "copy. Re-copy the intended `reuse_as` token whole, or confirm it as an "
            "independent claim.")
    _ledger(keys.unwitnessed, "unwitnessed",
            "A reuse names a minted key but quotes nothing. Re-copy the full `reuse_as` "
            "token (`KEY=xxxxxx`) to record the endorsement.")
    _ledger(keys.witness_mismatch, "witness-mismatch",
            "The key and the witness name different claims — copied from different feed "
            "rows. Re-copy the intended `reuse_as` token whole.")
    _ledger(keys.lost_endorsement, "lost-endorsement",
            "An endorsement named a key this corpus really minted and was still dropped: that "
            "key's stored form carries no readable namespace, so it was re-stamped into the "
            "endorser's own. Repair the MINTING scan's key to a hyphenated form (`CLAIM-001`), "
            "then re-materialize — after which the feed publishes a token that round-trips.")
    for key in keys.stray_witness:
        # A witness rode a MINT. Nothing merged on it, so nothing is corrupted — but the
        # author either meant a reuse (and lost a corroboration) or misread the convention
        # (and will misread it again). M5 lists this bucket as a queue input; it files
        # like the rest (screen finding F2).
        file("ledger", f"ledger stray-witness {key}",
             f"A witness tail rode the bare mint `{key}` — a witness on your own new key "
             f"endorses nothing. If a corroboration was intended, replace the bullet key "
             f"with the intended mint's full `reuse_as` from `bramber claims`; if a new "
             f"claim was intended, drop the `=xxxxxx` tail. Either way one edit under human "
             f"gate, then `bramber materialize`.",
             f"`{key}` was authored as a mint carrying an endorsement witness. The merge "
             f"was (correctly) not attempted; this proposal exists so the probable intent "
             f"gets ruled on rather than lost.")

    # `keys.ambiguous` files NOTHING here — retired 2026-08-12 with the stderr notice it
    # duplicated. It was the worse of the two channels: a proposal demands a ruling and persists,
    # so on a 27-source corpus it filed 30 files whose content is forced by the protocol (every
    # scan numbers from 1, so sources share ordinals by construction). A queue that files the
    # arithmetically inevitable trains the operator to stop reading the queue — the exact failure
    # the "never re-file an examined situation" rule above exists to prevent, arriving through a
    # different door. The near-duplicate merge queue covers the real hazard, by MEANING rather
    # than by ordinal. → decisions/2026-08-12-the-bare-key-notice-is-retired.md

    # -- topic drift (singleton pre-filter) -------------------------------------------------
    singleton = set(_singleton_topics(root))
    for pair in _topic_pairs(root, singleton):
        a, b = pair["tags"]
        file("topic", f"topic-pair {a} {b}",
             f"Rule whether `{a}` and `{b}` are one topic. If so, name the canonical tag; "
             f"the repair is re-tagging the affected scans under human gate, then "
             f"`bramber materialize`. Views select on topics, so a synonym tag is a claim a "
             f"view silently misses.",
             f"Token overlap {pair['overlap']}, and at least one side is carried by exactly "
             f"one source — the signature a synonym split manufactures.")

    # -- alias suggestions ------------------------------------------------------------------
    for pair in _alias_pairs(root):
        a, b = pair["keys"]
        file("alias", f"entity-pair {a} {b}",
             f"Rule whether `{a}` and `{b}` are one entity. If so, add each spelling to the "
             f"other's `aliases:` in the scans that carry them (under human gate), then "
             f"`bramber materialize` — the glossary keeps both surface forms and the merge "
             f"becomes visible instead of accidental.",
             f"They share name token(s) {pair['shared_names']} and topic(s) "
             f"{pair['shared_topics']}. `_norm_key` under-merges by design; this pair is "
             f"where that acceptance gets examined.")

    return {"proposals_filed": filed, "skipped_existing": skipped,
            "queues": counts, "notes": notes}


def _singleton_topics(root) -> list:
    """Topics carried by exactly one source, computed from the scans (the same drift signal
    `materialize` reports, derived read-only here so a sweep never rewrites the store)."""
    by_topic: dict = {}
    for s in scan_mod.read_all(root):
        if s.discarded or not s.source:
            continue
        for name in scan_mod._SECTIONS:
            for item in getattr(s, scan_mod._SECTION_ATTR[name]):
                for t in (item.topics or []):
                    by_topic.setdefault(str(t), set()).add(s.source)
    return sorted(t for t, srcs in by_topic.items() if len(srcs) == 1)
