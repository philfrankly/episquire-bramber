"""bramber scan — the one reader of an agent-authored scan, and the text domain's Unit producer.

Canonical spec: `specs/09-view-agnostic-claim-scan.md` (supersedes the per-view digest of
`specs/07` §3).

**A scan is one source read once, for anything claim-shaped.** It is view-agnostic: the agent
enumerates the assertions the source makes — graded, dated, tagged — without knowing or caring
which view will project them. Views then select over the shared claim store and can be added,
edited, and re-run without touching the corpus. That is the product: extraction cost is
O(sources), and a view is a projection, not a re-read.

**A claim is bounded by form, not by topic.** It is an assertion the source makes that could be
true or false and that a reader could check against the source. The scan does not decide what
matters — the view's selector and the authoring step do, downstream, where re-running is cheap.

**Four sections produce units, and every key in all four is unique across the corpus.**
`## Claims`, `## Entities`, `## Novel Concepts` and `## Contradictions`. Two identity styles, and
they achieve uniqueness by *different mechanisms* — a distinction worth holding, because one is
free and the other is maintained:

  - *carried by the sources* — an entity or term name, casefolded and whitespace-collapsed
    (`_norm_key`). Unique **by construction**: nobody chose it, so two spellings are one key and
    no agreement was needed.
  - *agent-assigned* — `CLAIM-007`, `CONTRA-002`, stored inside the minting source's namespace as
    `CLAIM-<8 hex>-007` (`resolve_keys`, ruled 2026-08-07). Unique because **no two sources share
    a namespace**, so two agents that never communicate cannot produce one key. Reuse — copying
    the stored key the feed publishes — is the corroboration decision, and it is resolved against
    the set of keys actually minted rather than inferred from the key's text.

Both therefore merge freely and neither needs a scope guard. That was not true before 2026-08-07:
extraction ran per (source × view) and each view counted its own `CLAIM-001` upward from its own
feed, which made a key meaningless outside the view that minted it and forced a cross-view join to
refuse anything agent-assigned. See the addendum to
the 2026-08-06 ruling "minted and observed keys", and
the 2026-08-07 ruling "keys are minted in a source owned namespace" for the namespace.

**One reader, not two.** Anything that parses a scan imports this module — the writer-vs-reader
drift that produced the NULL-url bug is the same shape as spec-vs-parser drift, and one artifact
gets one reader.

Stdlib-only; the engine never imports this (same boundary as `trace.py` and `run.py`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bramber.adapter import Unit
from bramber.engine import db

# --- the claim block -------------------------------------------------------
#
# The scan stays human-readable markdown; only the claim bullet becomes parseable. The shape
# is named-and-nested rather than positional-and-delimited, because an agent writing markdown
# produces this naturally and an order-sensitive one-liner would be brittle exactly where the
# author is a language model:
#
#   ## Claims
#
#   - **CLAIM-007** — Revenue grew 22% year over year, driven by the agents product line.
#     - evidence: strong
#     - recency: 2026-05-01
#     - topics: revenue-trajectory, product-mix
#
# `claim_key` is the text domain's stable identity: minted once, upstream, by the agent, and
# deduplicated by the engine **without the engine understanding it**. The key namespace is the
# corpus, not any view: source N is shown every key minted by sources 1..N-1 (`bramber claims`)
# and either reuses one — which is how corroboration gets recorded as an explicit decision — or
# mints a new one.
# The optional `=xxxxxx` tail is the endorsement WITNESS: six hex of the endorsed statement,
# printed by `bramber claims` as one copyable token (`CLAIM-cf9d2533-007=3f9a1c`). `=` is outside
# the key charset, so the split is unambiguous and a legacy key cannot contain a false witness.
CLAIM_RE = re.compile(r"^-\s+\*\*(?P<key>[A-Za-z][A-Za-z0-9_-]*)"
                      r"(?:=(?P<witness>[0-9a-f]{6}))?\*\*\s*(?:—|--|-)\s*(?P<statement>\S.*)$")
FIELD_RE = re.compile(r"^\s+[-*]\s+(?P<name>[a-z_]+)\s*:\s*(?P<value>.*)$")

# The loose bullet, for sections whose identity is a free-text NAME the sources carry rather than
# a key the agent assigned: `- **Acme Corp** — supplies the skids.` CLAIM_RE's restricted charset
# is exactly what makes it safe to reuse the same line shape for a second namespace, so it is left
# byte-identical and this is a separate pattern rather than a loosening of it.
NAMED_RE = re.compile(r"^-\s+\*\*(?P<name>[^*\n]{1,120})\*\*\s*(?:—|--|-)\s*(?P<gloss>\S.*)$")

# A bullet at column 0 — the only line shape that can introduce a new item, since both item
# patterns anchor `^-` and `FIELD_RE` requires leading whitespace. Used to decide whether an
# unparseable line is a malformed *item* (which must drop the carry-over, or its sub-bullets get
# transplanted onto the previous item) or merely a line inside one (which must not, or the item
# loses every field after it).
_ITEM_BULLET_RE = re.compile(r"^[-*]\s")

# FORMAT-SPEC has always told the agent to write "None identified" in an empty section. That was
# prose nobody read; now it is a real finding — "this source was examined and had none" is
# different information from "this scan predates the machine-readable block", and the absence
# reasons in `parse_text` keep them apart.
SENTINELS = frozenset({"none identified", "none", "n/a", "none identified."})

# A loose-bullet `make` has two ways to refuse, and they mean OPPOSITE things to an operator: the
# sentinel is a scan correctly reporting nothing, a blank name is a bullet written wrong. They
# cannot share `None` — reading a malformed item as the sentinel asserts that the section is
# complete. One object keeps them apart at the single call site in `parse_text`.
_SENTINEL_BULLET = object()

EVIDENCE_STRENGTHS = ("speculative", "weak", "moderate", "strong")


def _looks_like_namespace(segment: Optional[str]) -> bool:
    """Does this segment have the *shape* of a source namespace — 8 hex characters?

    **Advisory only, and deliberately never load-bearing.** A predicate on shape is what the first
    implementation used to decide mint-vs-reuse, and every decimal digit being a hex digit meant an
    ordinary `CLAIM-20260107-1` read as a reuse and two sources merged on it. Classification is set
    membership now (`resolve_keys`); this is used solely to decide whether an unresolved key is
    worth *mentioning* to an operator, where a false positive costs a line of output and a false
    negative costs a silently mistyped corroboration.
    """
    return bool(segment) and len(segment) == 8 and all(
        c in "0123456789abcdef" for c in segment.lower())


def srcref_for(source_rel: Optional[str]) -> str:
    """The 8-hex reference to the source that a scan reads — its key namespace.

    Taken from the extract slug, which `ingest._slug` already anchors on the source's
    `identity_key` (`<ref>__<first 8 of identity key>`) and which the index holds
    `UNIQUE(identity_key)`. So the namespace is not invented here; it is the identity the engine
    already assigns, reused for a second purpose.

    A slug with no identity suffix — a hand-built fixture, or an extract written before the
    convention — is hashed instead, so the function is total and deterministic either way rather
    than having a shape it refuses.
    """
    stem = _slug_for(source_rel) or ""
    tail = stem.rsplit("__", 1)[-1] if "__" in stem else ""
    if len(tail) == 8 and all(c in "0123456789abcdef" for c in tail.lower()):
        return tail.lower()
    return hashlib.sha256(stem.encode("utf-8")).hexdigest()[:8]


# The last segment given to an authored key that has none — the only way to stamp a hyphen-free
# key into the three segments `_namespace_of` needs. Sentinel, not a counter: it is escalated by
# repetition (`0` -> `00` -> ...) only to dodge a collision, never to number anything.
_NO_SEGMENT = "0"


def _stamp(key: str, srcref: str) -> str:
    """`CLAIM-007` + `cf9d2533` -> `CLAIM-cf9d2533-007`. Pure string surgery, no classification.

    **Total: always emits three segments**, so `_namespace_of` can read every stamped key. A
    hyphen-free authored key has no final segment to insert before, so it is given `_NO_SEGMENT`
    (`FINDING` -> `FINDING-cf9d2533-0`) rather than having the namespace appended to produce a
    two-segment key its own reader cannot parse.
    → the 2026-08-11 ruling "stamp is made total the migration premise was false"

    Totality is not injectivity, and the difference is handled by the caller: `FINDING` and
    `FINDING-0` authored in ONE source both land here as `FINDING-<ns>-0`. `resolve_keys` detects
    that and escalates the sentinel, because two distinct claims sharing a stored key is a merge
    nobody judged — the unrecoverable direction. No encoding closes it: any symbol that could
    separate the two preimage classes would have to be outside `CLAIM_RE`'s charset, and a stored
    key an endorser cannot copy back as a bullet key is the very failure this change repairs.
    """
    prefix, _, n = (key or "").rpartition("-")
    return f"{prefix}-{srcref}-{n}" if prefix else f"{key}-{srcref}-{_NO_SEGMENT}"


def statement_token(statement: str) -> str:
    """Six hex of the casefolded, whitespace-collapsed statement — the endorsement witness.

    This is what makes a reuse a *quotation* rather than a bare pointer. A key alone cannot carry
    intent: a mistyped or LLM-blended key that happens to name another REAL minted key passes
    every existence check and lands the endorsement on the wrong claim — fabricated support, in
    the exact field the product is sold on, with every reporter silent because nothing is
    malformed. Binding six hex of the *content* to the key means a plausible wrong key almost
    surely carries the wrong witness (2⁻²⁴ if blind, and a blend error copies rows, not halves
    of rows), so the misdirection is caught by exact string comparison — no semantics involved.

    Normalized with `_norm_key` deliberately: the witness pins content, not formatting, so a
    trivially reflowed feed does not orphan every outstanding reuse.
    """
    return hashlib.sha256(_norm_key(statement).encode("utf-8")).hexdigest()[:6]


def _namespace_of(key: str) -> Optional[str]:
    """The namespace segment a key *claims*, or None. A claim, not a fact — see `resolve_keys`."""
    parts = (key or "").split("-")
    return parts[-2] if len(parts) >= 3 else None


def _round_trips(key: str) -> bool:
    """Does this STORED key survive publish → copy → resolve unchanged?

    An endorser copies the feed's `reuse_as` verbatim and `resolve_keys` re-reads it, asking
    `_namespace_of` which namespace the key claims. When that answer is `None` the key is
    classified as an ordinary bare mint and re-stamped, so the copy names a *new* key and the
    endorsement is lost with every reporting bucket empty.

    **This should now be true of every stamped key by construction** — `_stamp` is total, so the
    class this was written to catch (an authored key with no hyphen producing a two-segment stored
    key) can no longer be produced. The function is deliberately kept anyway, per the superseded
    record's own §6: the assertion is what makes the *next* unpictured key shape loud instead of
    silent, so it should outlive the case that motivated it. A `False` here is now a report that
    the construction guarantee has broken, not an input the corpus is expected to contain.

    Kept as a check rather than an `assert` because the honest response to a stored key that
    cannot round-trip is still to withhold its reuse token and say why — refusing to publish is
    recoverable, and crashing `materialize` over one malformed key is not.
    → the 2026-08-11 ruling "stamp is made total the migration premise was false"
      (supersedes §3/§6 of
      the 2026-08-10 ruling "a key that cannot round trip is never published as reusable")
    """
    ns = _namespace_of(key)
    if ns is None:
        return False
    parts = key.split("-")
    authored = "-".join(parts[:-2] + parts[-1:])    # the stored key with its namespace removed
    return _stamp(authored, ns) == key


def resolve_keys(scans, extract_rels) -> "KeyResolution":
    """Decide, for every agent-authored key in the corpus, whether it MINTS or REUSES.

    **Classification is set membership, not pattern matching — and that distinction is the whole
    correctness argument.** The first implementation asked whether a key *looked* already-qualified
    (`^[A-Za-z][A-Za-z0-9_]*-[0-9a-f]{8}-\\d+$`) and took a match as proof of reuse. Shape is not
    intent, and an adversarial screen found three separate ways to say so:

      - every decimal digit is a hex digit, so an ordinary date-stamped mint like `CLAIM-20260107-1`
        matched and was passed through verbatim — two sources then collided on it and merged to
        `support: 2`, which is verbatim the defect namespacing exists to close;
      - the namespace segment was *supplied by the caller* and never checked against anything, so
        `CLAIM-<a-real-namespace>-042` — a number that source never minted — fabricated support
        with no notice at all;
      - `CLAIM_RE` admits `-` in a key while the qualified pattern's prefix did not, so a
        hyphenated prefix (`RISK-OPS-001`) produced a stored key the pattern could no longer read.
        The feed published a key its own reader rejected: a verbatim copy failed to match, was
        re-stamped, and reuse silently stopped merging while the key grew 9 characters per round.

    So nothing is inferred from the text. There is exactly one authority for "does this key exist":
    the set of keys some source actually minted, which this function computes before resolving any
    reuse against it.

        namespace == the author's own      -> MINT, used as written (idempotent; no re-stamping,
                                              which is what stops key growth on a round trip)
        namespace is some OTHER source's   -> a REUSE CLAIM, resolved against the minted set
                                              AND against the endorsement witness
        anything else                      -> MINT, stamped with the author's namespace

    **A reuse must exist and must be witnessed.** Set membership proves the key names something
    minted; it cannot prove the author meant *that* mint — a one-digit slip or an LLM blending
    two feed rows lands on a DIFFERENT real key, passes every existence check, and fabricates
    support on a claim the endorsing source never discussed. So a reuse also carries a witness
    (`KEY=xxxxxx`, copied as one token from the feed's `reuse_as`) and it must equal the six-hex
    token of the *minter's* statement. Existence is checked by membership; intent is checked by
    quotation; neither is inferred from the key's shape.

    Every failed reuse — unminted key, missing witness, wrong witness — is reported *and* stamped
    into the author's own namespace, so two copies of one mistake cannot merge into support
    neither source gave, and the author's assertion survives as its own claim. Under-merging is
    the recoverable direction (`specs/07 §3.2`); fabricating attribution is not.

    No circularity: "is this a known namespace" comes from the extract list, never from the keys,
    and a witness is verified against the minter's statement, never against the endorser's (whose
    phrasing legitimately differs — that is the whole point of agent-judged sameness).
    """
    known_ns = {srcref_for(rel) for rel in extract_rels}
    authored: list[tuple] = []          # (scan, kind, authored_key, own_ns, class, final, witness, statement)
    minted: set[tuple] = set()          # {(kind, final_key)}
    token_of: dict[tuple, str] = {}     # {(kind, final_key): witness token of the MINTER's statement}
    allocated: dict[tuple, tuple] = {}  # {(kind, final_key): (namespace, authored_key) that took it}
    collisions: dict[str, list] = {}    # authored keys whose sentinel had to be escalated

    for s in scans:
        if s.discarded or not s.source:
            continue
        own = srcref_for(s.source)
        for name, spec in _SECTIONS.items():
            if not spec["mints_keys"]:
                continue
            # Hyphenated keys first. Their stored form is the natural image of `_stamp`, so a
            # hyphen-free key — whose sentinel segment is the only thing that can land on the
            # same string — yields to them rather than the reverse. Sorting by the key's SHAPE
            # rather than by position makes the outcome independent of the order the agent
            # happened to write the bullets in; the sort is stable, so a repeated key still
            # collapses first-wins in the order it was written.
            for item in sorted(getattr(s, _SECTION_ATTR[name]),
                               key=lambda it: "-" not in (it.key or "")):
                key = item.key or ""
                ns = _namespace_of(key)
                if ns == own:
                    final, kind_of = key, "mint"
                elif ns in known_ns:
                    final, kind_of = key, "reuse-claim"
                elif _looks_like_namespace(ns):
                    # Namespace-shaped but naming no source here. Treated as a MINT, because
                    # that is the safe reading — two sources doing this get different stored
                    # keys and cannot fabricate support. But it is very likely a mistyped or
                    # wrongly-copied reuse, so it is flagged below rather than passed in silence.
                    final, kind_of = _stamp(key, own), "mint-unresolved"
                else:
                    final, kind_of = _stamp(key, own), "mint"
                    if "-" not in key and allocated.get(
                            (spec["kind"], final), (own, key)) != (own, key):
                        # `_stamp` is total but not injective: `FINDING` and `FINDING-0` authored
                        # in ONE source both name `FINDING-<ns>-0`. Letting them share it would
                        # merge two distinct claims into one unit — a merge nobody judged, and one
                        # claim silently gone. Escalate the sentinel until free, and report it:
                        # the stored key is no longer the natural image of what was authored, and
                        # the scan that produced the near-collision is worth repairing.
                        while allocated.get((spec["kind"], final), (own, key)) != (own, key):
                            final += _NO_SEGMENT
                        collisions.setdefault(key, []).append(s.source)
                authored.append((s, spec["kind"], key, own, kind_of, final,
                                 item.witness, item.statement))
                if kind_of.startswith("mint"):
                    minted.add((spec["kind"], final))
                    # Who took this stored key, so the sentinel above can tell "the same claim
                    # again" (collapse, correct) from "a different authored key" (collision).
                    allocated.setdefault((spec["kind"], final), (own, key))
                    # First occurrence anchors the witness: within one source, first-wins is
                    # already the collapse rule, so the token agrees with the unit that survives.
                    token_of.setdefault((spec["kind"], final), statement_token(item.statement))

    # witness -> the mints carrying it, for the "did you mean" suggestion on a failed reuse. A
    # token shared by two mints (two sources minting the identical normalized statement without
    # either reusing) yields no suggestion — suggesting one of them would be a guess.
    by_token: dict[str, list] = {}
    for tgt, tok in token_of.items():
        by_token.setdefault(tok, []).append(tgt)

    def _suggest(witness: Optional[str]) -> Optional[str]:
        hits = by_token.get(witness or "", [])
        return hits[0][1] if len(hits) == 1 else None

    resolution: dict[tuple, str] = {}
    unresolvable: dict[str, list] = {}
    unwitnessed: dict[str, list] = {}
    witness_mismatch: dict[str, list] = {}
    suggestions: dict[str, str] = {}
    stray_witness: set[str] = set()
    lost_endorsement: dict[str, list] = {}
    minters: dict[tuple, list] = {}
    deferred: list[tuple] = []          # [( (kind, final), statement )] applied after the loop
    for s, kind, key, own, kind_of, final, witness, statement in authored:
        if kind_of == "reuse-claim":
            target = (kind, final)
            if target not in minted:
                # A real namespace, a number that source never minted — the number mistyped.
                final = _stamp(key, own)
                unresolvable.setdefault(key, []).append(s.source)
                if _suggest(witness):
                    suggestions[key] = _suggest(witness)
            elif witness is None:
                # Resolves, but the endorsement quotes nothing. Accepting it would reopen the
                # wrong-minted-key hole for exactly the keys where it matters, so the merge is
                # refused and the author keeps their own claim. Loud, safe, repairable.
                final = _stamp(key, own)
                unwitnessed.setdefault(key, []).append(s.source)
            elif witness != token_of[target]:
                # The key and the witness disagree — copied from different feed rows, or the
                # key slipped onto a neighbouring mint. This is THE misdirection case: without
                # the witness it would merge silently onto the wrong claim.
                final = _stamp(key, own)
                witness_mismatch.setdefault(key, []).append(s.source)
                if _suggest(witness):
                    suggestions[key] = _suggest(witness)
            # else: a verified endorsement — existence by membership, intent by quotation.
        elif kind_of == "mint-unresolved":
            # Namespace-shaped but naming no source here — the hex mistyped rather than the
            # number. Already stamped safely; reported through the same channel because to an
            # operator it is the same mistake and wants the same fix.
            unresolvable.setdefault(key, []).append(s.source)
            if _suggest(witness):
                suggestions[key] = _suggest(witness)
        elif kind_of == "mint":
            minters.setdefault((kind, key), []).append(s.source)
            if witness is not None and (kind, key) in minted and key != final:
                # The author copied a REAL stored key — it is in the minted set — and the
                # classifier still read it as a mint, because the key carries no readable
                # namespace and so was re-stamped into the author's own. An endorsement was
                # attempted on an existing claim and lost. Detected by SET MEMBERSHIP, never by
                # shape: `(kind, key)` is what some source actually minted.
                #
                # Disjoint from `stray_witness` on purpose — that bucket means "a witness rode a
                # genuinely new key" and this one means "a real endorsement was dropped". They
                # want different words, and `known_keys` now refuses to publish the token that
                # produces this, so a corpus should only ever reach here through a scan authored
                # before that guard existed.
                lost_endorsement.setdefault(key, []).append(s.source)
            elif witness is not None:
                # A witness on a mint endorses nothing (no merge hangs on it) but signals the
                # author misread the convention. Surfaced in the return, never on stderr.
                stray_witness.add(key)
        if kind_of == "reuse-claim":
            # Register the outcome either way, but AFTER this loop, never during it. A verified
            # reuse re-adds an existing entry (setdefault keeps the minter's token — the
            # endorser's phrasing must never become the witness). A degraded reuse became a mint
            # of the author's own claim, and a claim that exists must be endorsable however it
            # came to exist — so the feed gets a reuse_as for it too.
            deferred.append(((kind, final), statement))
        resolution[(s.path, kind, key)] = final

    # Registering in place made the sets this loop READS depend on how far it had already got, and
    # `authored` is built in `scan_files`' filename order. So whether an endorsement of a degraded
    # reuse resolved came down to which scan happened to sort first — support 2 one way, support 1
    # the other, on byte-identical content with one file renamed. Deferring makes every reuse in a
    # pass resolve against the same set, which is what "the same corpus resolves the same way"
    # requires. Within a pass this errs toward under-merge — the recoverable direction
    # (`specs/07 §3.2`) — and the key is still published here, so the next pass can endorse it.
    #  -> work/criteria/key-namespacing-and-merge-fixes.md AC-15
    for target, statement in deferred:
        minted.add(target)
        token_of.setdefault(target, statement_token(statement))

    # The migration hazard: one authored key MINTED by more than one source. Before namespacing a
    # repeated key meant corroboration and merged; it now means each source minted its own and
    # they do not. Detected from the classification rather than from the key's shape, so a key
    # that merely looks namespaced cannot slip past it — which is exactly how the shape-based
    # version stayed silent on `CLAIM-20260107-1`.
    ambiguous = {k: sorted(set(v)) for k, v in minters.items() if len(set(v)) > 1}

    return KeyResolution(
        resolution=resolution, minted=minted, ambiguous=ambiguous,
        unresolvable={k: sorted(set(v)) for k, v in unresolvable.items()},
        unwitnessed={k: sorted(set(v)) for k, v in unwitnessed.items()},
        witness_mismatch={k: sorted(set(v)) for k, v in witness_mismatch.items()},
        suggestions=suggestions, stray_witness=sorted(stray_witness), witness_of=token_of,
        lost_endorsement={k: sorted(set(v)) for k, v in lost_endorsement.items()},
        key_collisions={k: sorted(set(v)) for k, v in collisions.items()})


@dataclass
class KeyResolution:
    """The corpus-wide answer to "what key does this authored key become, and was it a reuse?".

    The reporting buckets are disjoint by construction, because each wants different words to an
    operator: `unresolvable` (the key names nothing minted), `unwitnessed` (it resolves but the
    endorsement quotes nothing), `witness_mismatch` (the key and the quotation name different
    claims — the misdirection case). `suggestions` maps a failed authored key to the minted key
    its witness DOES match, when exactly one does. `witness_of` is what the feed publishes as
    `reuse_as` — {(kind, final_key): six-hex token of the minter's statement}.

    `lost_endorsement` is the fifth bucket: the authored key IS a stored key of this corpus and
    the endorsement was still dropped, because that key carries no readable namespace and was
    re-stamped. Separate from `stray_witness` (a witness on a genuinely new key) because a lost
    corroboration and a misread convention are different facts, and unlike that bucket it reaches
    stderr — an endorsement the ledger silently declined to record is exactly what this product
    may not do quietly.

    `key_collisions` is the sixth: a hyphen-free authored key whose stamped form was already taken
    by a *different* authored key of the same source, so its sentinel segment was escalated. The
    claim is intact and distinct — that is the point of escalating rather than letting the two
    share a key — but the stored key is no longer the natural image of the authored one, which is
    a scan defect a human should repair.
    → the 2026-08-11 ruling "stamp is made total the migration premise was false"
    """
    resolution: dict
    minted: set
    ambiguous: dict
    unresolvable: dict
    unwitnessed: dict
    witness_mismatch: dict
    suggestions: dict
    stray_witness: list
    witness_of: dict
    lost_endorsement: dict = field(default_factory=dict)
    key_collisions: dict = field(default_factory=dict)

    def final(self, scan_path: str, kind: str, authored: str) -> str:
        """The stored key. Falls back to the authored text for a scan not in this resolution —
        callers that resolve a single scan in isolation (tests, `parse` used directly) get the
        local answer rather than an exception."""
        return self.resolution.get((scan_path, kind, authored), authored)


def _norm_key(name: str) -> str:
    """Casefold + collapse whitespace. The identity of a name the sources carry.

    Deliberately dumb, and that is the argument for it. `specs/07 §3.2` rejects
    semantic-similarity dedup on correctness rather than cost: a missed merge inflates a count,
    which is visible and correctable, while a false merge fabricates attribution. A surface-string
    key can only under-merge, and when it does, both spellings are printed on the page where a
    reader sees them. `aliases` exists so the agent can record the variants rather than silently
    normalising to one.
    """
    return " ".join((name or "").split()).casefold()

# Reliability tier by source class — a FIXED TABLE, never adapter-chosen and never derived from
# how convincing the text sounds (specs/08 §4.1 rule 1). The tier is a statement about
# provenance: a text source is an *account of* the world rather than the world itself, so text
# is `reported`. Refining this (a verbatim first-party transcript arguably being authoritative
# for what was said in the room) is a product judgment, deliberately left to a founder ruling
# rather than invented here — the mechanism is live either way, since `min()` over a
# single-valued set still bounds correctly.
DEFAULT_RELIABILITY_TIER = "reported"
RELIABILITY_BY_SOURCE_TYPE: dict[str, str] = {}


@dataclass
class Claim:
    key: str
    statement: str
    evidence_strength: Optional[str] = None
    recency: Optional[str] = None
    topics: list = field(default_factory=list)
    # The witness the author attached to the key, if any — six hex quoting the statement this
    # bullet endorses. Meaningful only on a cross-namespace reuse; `resolve_keys` verifies it.
    witness: Optional[str] = None


@dataclass
class Entity:
    """A named thing the sources talk about. Its identity is the name — nobody chose "Acme Corp"."""
    entity_name: str
    gloss: str
    entity_key: str = ""
    role: Optional[str] = None
    stance: Optional[str] = None
    status: Optional[str] = None
    aliases: list = field(default_factory=list)
    topics: list = field(default_factory=list)

    def __post_init__(self):
        self.entity_key = self.entity_key or _norm_key(self.entity_name)


@dataclass
class Term:
    """Vocabulary rather than a proper noun. Kept apart from Entity because FORMAT-SPEC already
    separates them, and a glossary presents the two differently even though it wants both."""
    term_name: str
    gloss: str
    term_key: str = ""
    status: Optional[str] = None
    relates_to: list = field(default_factory=list)
    topics: list = field(default_factory=list)

    def __post_init__(self):
        self.term_key = self.term_key or _norm_key(self.term_name)


@dataclass
class Contradiction:
    """A tension between claims. Its key is agent-assigned exactly like a claim's, resolved
    through the same source namespace, and merged by the same rule.

    Each side is `<KEY> | <extract_path> | <position>`, where `<KEY>` is the **stored** key as
    `bramber claims` prints it (`CLAIM-a3f21c04-007`). The `<view>/` prefix sides carried before
    the 2026-08-07 redesign is gone: it disambiguated across view-scoped namespaces, and there are
    no view-scoped namespaces. What replaced it is not "no namespace" but a *source* namespace, so
    a side written as a bare `CLAIM-007` names a claim in no namespace and resolves to nothing.
    """
    key: str
    statement: str
    sides: list = field(default_factory=list)
    resolution: Optional[str] = None
    resolution_status: Optional[str] = None
    topics: list = field(default_factory=list)
    witness: Optional[str] = None


@dataclass
class Scan:
    path: str
    source: Optional[str]
    discarded: bool
    claims: list
    entities: list = field(default_factory=list)
    terms: list = field(default_factory=list)
    contradictions: list = field(default_factory=list)
    # Per-kind: why this scan produced none. Three cases that must not be confused — the section
    # is absent · the section says "None identified" (a real finding) · the section has content in
    # a shape the parser does not recognise (the dangerous one, and the only one that names a line
    # count, because that is what tells a reader it is a migration and not an answer).
    kinds_absent: dict = field(default_factory=dict)
    # Per-kind degrade counts, `{kind: {"lost": n, "truncated": n}}`. Populated **independently of**
    # `kinds_absent`, because the interesting case is the one where the section DID produce units
    # and quietly degraded some, which the whole-section control cannot see. The two counts are
    # different facts: `lost` = a malformed item bullet produced no unit at all; `truncated` = an
    # item parsed, but a line inside it did not, so every field after that line is missing from an
    # otherwise real unit.
    kinds_unparsed: dict = field(default_factory=dict)


def _split_list(value: str) -> list:
    return [v.strip() for v in re.split(r"[,;]", value or "") if v.strip()]


def _parse_side(value: str) -> Optional[dict]:
    """`<KEY> | <extract_path> | <position>` -> a checkable side reference.

    `<KEY>` is the **stored** key — namespaced, as `bramber claims` prints it. A bare `CLAIM-007`
    parses fine here and names nothing in the store; nothing resolves sides today
    (`meta.contradiction_graph` draws them as written), so this is recorded rather than enforced,
    and `specs/10`'s `contradictions_for(claim_key)` is the caller that will care.
    `extract_path` remains the anchor that makes a side checkable without trusting the key at all,
    which is why it is carried rather than looked up.
    """
    parts = [p.strip() for p in (value or "").split("|")]
    ref = parts[0] if parts else ""
    # A `<view>/<KEY>` ref written against the withdrawn per-view shape still names a real claim
    # after the slash. Take it rather than reject it — dropping the side would under-report a
    # contradiction, and the key it points at is unambiguous now in a way it was not when written.
    if "/" in ref:
        ref = ref.partition("/")[2].strip()
    # An agent pasting the feed's `reuse_as` token here is doing the right thing with the wrong
    # syntax expectation; split the witness off rather than storing a ref no key will ever equal.
    # Carried unverified: nothing resolves sides today, and the consumer specs/10 specifies
    # (`contradictions_for(claim_key)`) is where verification belongs when it lands.
    witness = None
    if "=" in ref:
        ref, _, w = ref.partition("=")
        ref, witness = ref.strip(), (w.strip() or None)
    if not ref:
        return None
    return {
        "ref": ref,
        "unit_key": ref,
        "witness": witness,
        "extract_path": parts[1] if len(parts) > 1 and parts[1] else None,
        "position": parts[2] if len(parts) > 2 and parts[2] else None,
    }


def _claim_field(c: "Claim", name: str, value: str) -> None:
    if name in ("evidence", "evidence_strength"):
        c.evidence_strength = value.lower() or None
    elif name == "recency":
        c.recency = value or None
    elif name in ("topics", "topic"):
        c.topics = _split_list(value)


def _entity_field(e: "Entity", name: str, value: str) -> None:
    # `role`, not `kind` — `kind` is already the Unit's own field, and a payload key by that name
    # would be genuinely confusing to every reader of an envelope.
    if name in ("role", "stance", "status"):
        setattr(e, name, value or None)
    elif name == "aliases":
        e.aliases = _split_list(value)
    elif name in ("topics", "topic"):
        e.topics = _split_list(value)


def _term_field(t: "Term", name: str, value: str) -> None:
    if name == "status":
        t.status = value or None
    elif name in ("relates_to", "relates"):
        t.relates_to = _split_list(value)
    elif name in ("topics", "topic"):
        t.topics = _split_list(value)


def _contradiction_field(c: "Contradiction", name: str, value: str) -> None:
    if name == "side":
        # The one REPEATING field. A contradiction with one side is not a contradiction, so the
        # shape has to accumulate rather than overwrite; the pipe-triple follows the convention
        # `split_frontmatter` already uses for a version snapshot's repeating `source:`.
        side = _parse_side(value)
        if side:
            c.sides.append(side)
    elif name == "resolution":
        c.resolution = value or None
    elif name in ("status", "resolution_status"):
        c.resolution_status = value or None
    elif name in ("topics", "topic"):
        c.topics = _split_list(value)


def _make_named(cls, name_attr: str):
    """Build an Entity/Term from a loose bullet, skipping the 'None identified' sentinel.

    The sentinel guard is not optional. FORMAT-SPEC has always asked for that phrase in an empty
    section, and NAMED_RE would happily read `- **None identified.** — ...` as an entity called
    "None identified".
    """
    def make(m):
        raw = m.group("name").strip()
        if raw.rstrip(".").lower() in SENTINELS:
            return _SENTINEL_BULLET
        if not raw:
            # `NAMED_RE` admits any 1-120 non-asterisk characters, so `- ** ** - a gloss` arrives
            # here with a whitespace-only name. An empty name is an empty KEY, and the key is the
            # identity for these kinds — so every source carrying one mints the same key and the
            # selector merges on it, collapsing unrelated entities from unrelated sources into a
            # single unit. That is the merge-nobody-judged direction, and unlike an under-merge it
            # cannot be recovered downstream: the losing statement is simply gone. Refused as the
            # malformed item it is, and counted `lost` by the caller.
            return None
        return cls(**{name_attr: raw, "gloss": m.group("gloss").strip()})
    return make


# One entry per parsed section. Adding a section is a row here plus a dataclass.
#
# Claims and Contradictions use the STRICT bullet: their keys are agent-assigned from a restricted
# charset, so a legacy prose section yields nothing by the same mechanism that has always
# protected Claims. Entities and Novel Concepts use the loose one, which means a section written
# in the shape FORMAT-SPEC already asks for ("Name — role/stance") parses for free.
#
# `mints_keys` is the **one declaration** of which sections carry an agent-assigned key, and it is
# what `known_keys` iterates. Getting this wrong is not a cosmetic error: a kind that merges on a
# key the mint-or-reuse feed does not publish has no way for an agent to know the key is taken, so
# two sources independently assign it to unrelated things and the merge reports corroboration
# neither source gave. That is the failure the 2026-08-06 ruling "minted and observed keys" was
# written about, and it reappeared here as an asymmetry — claims were fed, contradictions were not
# — precisely because the two facts lived in two places. They live in one now.
#
# Entities and terms are `False` because their key IS their name: nothing is assigned, so there is
# nothing to reuse and no feed to consult. `_norm_key` makes two spellings the same key by
# construction.
_SECTIONS = {
    "claims": {
        "heading": "claims", "title": "Claims", "kind": "claim", "bullet": CLAIM_RE,
        "mints_keys": True, "key_prefix": "CLAIM",
        "make": lambda m: Claim(key=m.group("key").strip(),
                                statement=m.group("statement").strip(),
                                witness=m.group("witness")),
        "field": _claim_field,
    },
    "entities": {
        "heading": "entities", "title": "Entities", "kind": "entity", "bullet": NAMED_RE,
        "mints_keys": False, "key_prefix": None,
        "make": _make_named(Entity, "entity_name"), "field": _entity_field,
    },
    "terms": {
        "heading": "novel concepts", "title": "Novel Concepts", "kind": "term",
        "bullet": NAMED_RE, "mints_keys": False, "key_prefix": None,
        "make": _make_named(Term, "term_name"), "field": _term_field,
    },
    "contradictions": {
        "heading": "contradictions", "title": "Contradictions", "kind": "contradiction",
        "bullet": CLAIM_RE, "mints_keys": True, "key_prefix": "CONTRA",
        "make": lambda m: Contradiction(key=m.group("key").strip(),
                                        statement=m.group("statement").strip(),
                                        witness=m.group("witness")),
        "field": _contradiction_field,
    },
}

# The attribute on `Scan` holding each section's parsed items, so `known_keys` can walk sections
# generically rather than naming `s.claims` and falling behind the next time a section is added.
_SECTION_ATTR = {"claims": "claims", "entities": "entities", "terms": "terms",
                 "contradictions": "contradictions"}


def parse_text(text: str, *, path: str = "") -> Scan:
    """Parse a scan's frontmatter and its four machine-readable sections.

    `## Claims`, `## Entities`, `## Novel Concepts` and `## Contradictions` are read for units.
    `## Notes` stays prose **permanently**: it is per-scan editorial argument about this source,
    singular and non-repeating, with no dedup key and nothing to corroborate. Materializing it
    would produce one unit per scan that merges with nothing.

    A scan whose sections are prose parses to zero units for those kinds and **a stated reason per
    kind** (`Scan.kinds_absent`) — never a bare silence. Bare silence reads as "this corpus has no
    entities", which is a conclusion nobody drew. That is the same distinction
    `units_absent_reason` exists to make, one level down.
    """
    # `source:` does NOT arrive in `fields`. The shared frontmatter parser special-cases that key
    # into its own list, because in a *version snapshot* `source:` repeats and each value is an
    # `extract | scan | contribution` pipe-triple. A scan uses the same key for a single path,
    # so one parser serves two conventions and the scan's value is only reachable through the
    # list.
    fields, srcs, _ = db.split_frontmatter(text)
    source = srcs[0].strip() if srcs else fields.get("source")

    out: dict[str, list] = {k: [] for k in _SECTIONS}
    seen: dict[str, dict] = {}           # per section: content lines, sentinel hit
    section: Optional[str] = None
    current = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            # Any new H2 closes the previous section — a bullet never spans one.
            head = stripped[3:].strip().lower()
            section = next((k for k, s in _SECTIONS.items() if head.startswith(s["heading"])), None)
            current = None
            if section:
                seen.setdefault(section, {"lines": 0, "sentinel": False,
                                          "lost": 0, "truncated": 0})
            continue
        if section is None:
            continue

        spec = _SECTIONS[section]
        if stripped:
            seen[section]["lines"] += 1
            if stripped.strip("-*_[] ").rstrip(".").lower() in SENTINELS:
                seen[section]["sentinel"] = True
                current = None
                continue

        m = spec["bullet"].match(line)
        if m:
            current = spec["make"](m)
            if current is _SENTINEL_BULLET:
                # The bullet is the "None identified" sentinel wearing bullet syntax. That is a
                # real finding — this scan uses the machine-readable shape and reports nothing —
                # and must not be misread as a legacy prose section, which is the opposite
                # conclusion.
                current = None
                seen[section]["sentinel"] = True
                continue
            if current is None:
                # A named bullet the section's `make` refused: it matched the item pattern, so it
                # is a malformed ITEM rather than prose or a sentinel, and is counted where every
                # other malformed item is counted. Distinct from the branch above on purpose —
                # `sentinel` would assert this section is complete when it is not.
                seen[section]["lost"] += 1
                continue
            out[section].append(current)
            continue

        f = FIELD_RE.match(line)
        if f and current is not None:
            spec["field"](current, f.group("name"), f.group("value").strip())
            continue

        # Neither a bullet nor a field of a live item. **What happens next turns on one question:
        # could this line have been meant as a new ITEM?** Only a line that could must drop the
        # carry-over, and the answer is structural rather than a guess.
        #
        # An item bullet is `- **Name** — gloss` at column 0 (both CLAIM_RE and NAMED_RE anchor
        # `^-`). A field bullet is indented (`FIELD_RE` requires leading whitespace). So a bullet
        # at column 0 that failed the item pattern is a *malformed item* — and it is the dangerous
        # one, because its own sub-bullets follow it and would be applied to the PREVIOUS item.
        # That is not a drop but a **transplant**: the previous claim silently acquires the next
        # one's evidence grade, recency and topics, and every downstream surface — selection, the
        # topic register, even `--trace`'s rejection reason — then reports the corrupted value as
        # though the source had given it.
        #
        # Anything else — a wrapped field value, a nested list under `aliases:`, an editorial line
        # between bullets — **cannot** introduce an item, so it can misattribute nothing and the
        # carry-over must survive. Resetting on those too was a real regression: a `resolution:`
        # value long enough to wrap (FORMAT-SPEC's own example is 68 characters, and a wrapped
        # value is ordinary output from a language model) killed the item's remaining `status` and
        # `topics`. The item still materialized, under-tagged, which is a wrong unit rather than an
        # absent one.
        #
        # The two are counted apart because they are different facts and want different words to
        # an operator: `lost` means an item produced no unit; `truncated` means an item produced a
        # unit missing whatever followed. One counter reporting both would make the notice false
        # for whichever case it did not name.
        if stripped:
            if _ITEM_BULLET_RE.match(line):
                seen[section]["lost"] += 1
                current = None
            elif current is not None:
                seen[section]["truncated"] += 1
            # else: prose in a section with no live item — already counted in `lines`, which is
            # what drives the "predates the machine-readable block" reason. There is no item to
            # lose and none to truncate.

    # Per-kind degrade counts, recorded **whether or not that kind produced units**. `kinds_absent`
    # answers "why did this section give nothing", which is a whole-section question; a section
    # that parses two bullets of three is not absent and was invisible to it. The stated rule is
    # per-item — *a section left in prose is never silent* — so the control has to exist at the
    # per-item granularity or the rule is only true in the all-or-nothing case.
    #
    # `lost` and `truncated` stay apart all the way to the operator: an item that produced no unit
    # and an item that produced an incomplete one need different words, and a single counter makes
    # whichever notice is printed false for the other.
    kinds_unparsed = {}
    for name, spec in _SECTIONS.items():
        s = seen.get(name)
        if not s or not (s["lost"] or s["truncated"]):
            continue
        kinds_unparsed[spec["kind"]] = {"lost": s["lost"], "truncated": s["truncated"]}

    kinds_absent = {}
    for name, spec in _SECTIONS.items():
        kind = spec["kind"]
        if out[name]:
            continue
        s = seen.get(name)
        if s is None:
            kinds_absent[kind] = f"no `## {spec['title']}` section in this scan"
        elif s["sentinel"]:
            kinds_absent[kind] = f"the `## {spec['title']}` section states 'None identified'"
        elif s["lost"] or s["truncated"]:
            kinds_absent[kind] = (
                f"the `## {spec['title']}` section carries {s['lost']} malformed item bullet(s) "
                f"and no parsed one")
        elif s["lines"]:
            # The dangerous case, and the reason it names a count: a scan written before this
            # section was machine-readable looks identical to one that legitimately found nothing,
            # and reading a migration as an answer is how a corpus quietly under-reports.
            kinds_absent[kind] = (
                f"the `## {spec['title']}` section carries {s['lines']} line(s), none matching the "
                f"parsed shape — this scan predates the machine-readable block")
        else:
            kinds_absent[kind] = f"the `## {spec['title']}` section is empty"

    return Scan(
        path=path,
        source=source,
        discarded=str(fields.get("discarded", "")).strip().lower() == "true",
        claims=out["claims"],
        entities=out["entities"],
        terms=out["terms"],
        contradictions=out["contradictions"],
        kinds_absent=kinds_absent,
        kinds_unparsed=kinds_unparsed,
    )


def parse(path) -> Scan:
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8"), path=p.as_posix())


def scan_files(root) -> list:
    """Every scan on disk, sorted for determinism. One file per source, in `_bramber/scans/`."""
    scans_dir = Path(root) / "_bramber" / "scans"
    if not scans_dir.exists():
        return []
    return sorted(scans_dir.glob("*.md"))


def read_all(root) -> list:
    """Every scan under a root, with `path` recorded root-relative — the same convention as
    `extract_path`, so provenance and lineage never carry a machine-specific prefix."""
    root = Path(root).resolve()
    out = []
    for f in scan_files(root):
        rel = f.resolve().relative_to(root).as_posix()
        out.append(parse_text(f.read_text(encoding="utf-8"), path=rel))
    return out


def check_srcref_uniqueness(extract_rels) -> None:
    """Refuse a corpus in which two sources share a key namespace.

    The namespace is 8 hex of a `content_sha`, so distinct sources collide with probability
    ~N²/2³³ — about 1 in 10,000 at a thousand sources. Small is not the same as impossible, and
    the whole argument for namespacing over locking is that the guarantee is structural rather
    than probable. So it is checked rather than assumed: a shared prefix would silently restore
    the exact defect this design removes, for the two sources that happened to collide.

    Raises rather than warns. The remedy is to widen the prefix, which is a one-line change to
    `ingest._slug`, and a corpus that trips this must not quietly merge in the meantime.
    """
    by_ref: dict[str, list] = {}
    for rel in extract_rels:
        by_ref.setdefault(srcref_for(rel), []).append(rel)
    clashes = {ref: rels for ref, rels in by_ref.items() if len(rels) > 1}
    if clashes:
        detail = "\n  ".join(f"{ref}: {', '.join(sorted(rels))}" for ref, rels in sorted(clashes.items()))
        raise SystemExit(
            f"[bramber] scan: {len(clashes)} key namespace(s) are shared by more than one "
            f"source:\n  {detail}\n\nA namespace is 8 hex of the source's content_sha and is what "
            f"makes a minted key collision-free without coordination. Two sources sharing one can "
            f"mint the same key for unrelated claims, and selection would merge them into a "
            f"support count no source gave. Widen the identity prefix in `ingest._slug`.")


def known_keys(root) -> list:
    """Every agent-assigned key in this corpus, with the sources asserting it.

    **Every key-minting section, not just Claims** — the sections are read from `_SECTIONS`
    (`mints_keys`), so a kind cannot merge on a key this feed does not publish. That asymmetry
    existed briefly and was the whole hazard: `CONTRA-NNN` merged corpus-wide while this function
    iterated claims alone, so an agent scanning source 2 could not know `CONTRA-001` was taken,
    assigned it to an unrelated tension, and the register merged the two into one entry reporting
    `support: 2` — corroboration neither source gave, with one statement discarded.

    This is what an agent is shown before scanning source N (`bramber claims`), so it can
    **reuse** a key rather than mint a near-duplicate. Corroboration therefore becomes an
    explicit, auditable decision — "source 4 asserts CLAIM-007, first minted by source 1" —
    instead of a similarity threshold being crossed.

    Semantic-similarity dedup is rejected here on correctness, not cost (specs/07 §3.2): negation
    is invisible to embeddings ("the deadline is confirmed" vs "…is *not* confirmed" are near
    identical), and the two error types are not symmetric. A missed merge inflates a count, which
    is visible and correctable. A false merge **fabricates attribution** — asserting that source
    B supports a claim B never made — which in an engine whose product is cited provenance is the
    failure that destroys the artifact.
    """
    scans = [s for s in read_all(root) if not s.discarded and s.source]
    # The SAME resolution `units_for_source` uses. The feed publishes the key an agent copies to
    # corroborate, so if the feed and the store resolved differently the copied key would name
    # nothing and reuse would silently stop merging — the publish→copy round trip has to close.
    keys = resolve_keys(scans, [s.source for s in scans])
    by_key: dict[tuple, dict] = {}
    for s in scans:
        for name, spec in _SECTIONS.items():
            if not spec["mints_keys"]:
                continue
            for item in getattr(s, _SECTION_ATTR[name]):
                key = keys.final(s.path, spec["kind"], item.key)
                tok = keys.witness_of.get((spec["kind"], key))
                entry = by_key.setdefault((spec["kind"], key), {
                    "kind": spec["kind"], "key": key, "statement": item.statement,
                    "sources": [],
                    # The single copyable endorsement token. An agent corroborating this claim
                    # writes exactly this as the bullet key — key and witness travel as one atom,
                    # which is what makes a blend of two feed rows detectable.
                    "witness": tok,
                    # THE GUARD, now a falsifier rather than a product behaviour: since `_stamp`
                    # became total, every stored key round-trips by construction and this branch
                    # should be unreachable. It is kept because the invariant is *checked at the
                    # point of publication* rather than assumed everywhere, which is what makes
                    # the next unpictured key shape loud instead of silent — handing an agent a
                    # token its own resolver will re-stamp costs a corroboration and reports
                    # nothing. Under-recording is recoverable; a silently dropped endorsement is
                    # the failure this ledger exists to prevent.
                    # → decisions/2026-08-11-stamp-is-made-total-the-migration-premise-was-false.md
                    "reuse_as": (f"{key}={tok}" if tok else key) if _round_trips(key) else None,
                    "no_reuse_reason": None if _round_trips(key) else (
                        "this key's stored form carries no readable namespace (the authored key "
                        "had no hyphen), so a copy of it would be read as a new mint and the "
                        "endorsement lost. Repair the minting scan's key under "
                        "`/bramber:evaluate`, then re-materialize."),
                    # The M2 row fields (specs/11): every feed shape — full, --like, pack —
                    # serves the same candidate row, so the shortlist regimes and the full feed
                    # stay semantically identical at the assert layer.
                    "evidence": None,
                    "topics": [],
                })
                # Display the MINTER's phrasing, whichever scan happened to sort first: the
                # statement whose token matches the witness is the one the witness quotes, and
                # showing an endorser's phrasing beside the minter's token would invite an agent
                # to think the token hashes the text in front of them. The evidence grade rides
                # with the phrasing for the same reason — it is the minter's assessment of the
                # minter's statement, not a vote endorsers may adjust.
                if tok and statement_token(item.statement) == tok:
                    entry["statement"] = item.statement
                    entry["evidence"] = getattr(item, "evidence_strength", None)
                # Topics union across every contributor: an endorser tagging the claim into a
                # topic the minter missed is information a reuse decision wants, and topics
                # carry no witness mechanism to protect (specs/11 G5).
                for t in (item.topics or []):
                    if t not in entry["topics"]:
                        entry["topics"].append(t)
                if s.source and s.source not in entry["sources"]:
                    entry["sources"].append(s.source)
    rows = [by_key[k] for k in sorted(by_key)]
    for e in rows:
        # Distinct sources asserting the key — the same count `compile.select_units` derives
        # from merged provenance, stated here so a feed reader never re-derives it.
        e["support"] = len(e["sources"])
    return rows


def known_claims(root) -> list:
    """The claim slice of `known_keys`, in its original shape.

    Kept because `claim_key` is the field name the plugin's prose and the eval harness read. It is
    a projection of the one feed, never a second walk of the scans — the two falling out of step
    is exactly how the contradiction hazard arose.
    """
    return [{"claim_key": e["key"], "statement": e["statement"], "sources": e["sources"],
             "reuse_as": e["reuse_as"], "no_reuse_reason": e.get("no_reuse_reason")}
            for e in known_keys(root) if e["kind"] == "claim"]


def topic_vocabulary(root) -> list:
    """Every topic tag any scan in this corpus carries, sorted. Served with EVERY feed shape.

    Ruled in `specs/11` G5: topic reuse-before-mint has no witness mechanism and the
    vocabulary is small, so shortlisting it would manufacture exactly the synonym splits the
    discipline exists to avoid. A shape that serves ten candidate claims still serves the
    complete tag vocabulary — only claim/contradiction candidates are ever shortlisted.

    Read from the scans, not the unit envelopes, for the same freshness reason the key feed
    is: the feed and the store must agree the moment a scan lands, not one materialize later.
    """
    tags: set = set()
    for s in read_all(root):
        if s.discarded or not s.source:
            continue
        for name in _SECTIONS:
            for item in getattr(s, _SECTION_ATTR[name]):
                tags.update(t for t in (item.topics or []) if t)
    return sorted(tags)


def candidate_rows(root, nominations: list) -> tuple:
    """Fresh feed rows for a shortlist of nominated `(kind, key)` idents.

    **This function is why the index is safe to serve from** (`specs/11` G2 and M2): the
    index nominates idents and nothing else; every statement, witness and `reuse_as` in a
    served row is read from the store at serve time through the one feed (`known_keys`).
    Vectors may be a materialize stale; what an agent copies may not — a cached token that
    disagreed with the store would break the publish→copy→resolve round trip (P6) in the
    exact direction the witness exists to close.

    A nomination the store no longer knows (the index lagging a repair or a withdrawal) is
    returned in the second list, named — dropped from the candidates but never silently:
    a shrunk shortlist with no explanation reads as "nothing similar exists", which is a
    conclusion the stale cache cannot support.
    """
    by_ident = {(e["kind"], e["key"]): e for e in known_keys(root)}
    rows, stale = [], []
    for n in nominations:
        entry = by_ident.get((n["kind"], n["key"]))
        if entry is None:
            stale.append(f"{n['kind']}:{n['key']}")
            continue
        rows.append({**entry, "score": n.get("score")})
    return rows, stale


def _record_shown(root, cmd: str, subject: str, rows: list) -> None:
    """The shown-candidate record (`specs/11` G9): one run-record per feed call, naming what
    was asked and every key served. Scans are immutable agent artifacts, so the audit trail
    goes to `_bramber/runs/` (specs/05 machinery) — which converts "the agent saw CLAIM-007
    and minted anyway" from unknowable into evidence (M3). Advisory like every run record:
    deleting it loses the audit note, never a fact."""
    from bramber import run as run_mod  # lazy: run imports scan at module level
    run_mod.record(root, cmd, [
        {"item": subject, "phase": "feed", "outcome": "served",
         "detail": f"{len(rows)} candidate(s)"},
        *({"item": r["key"], "phase": "shown-candidate", "outcome": "served",
           "detail": subject} for r in rows),
    ])


def feed_like(root, statement: str, *, k: int = 10, embedder=None) -> dict:
    """Shape A (`specs/10` §4.2): the ~k nearest candidates for one draft statement.

    The escape hatch and the corroboration workhorse — the query is claim-shaped and so is
    the index, a form-match other retrieval stacks have to manufacture. Rows come fresh from
    the store (`candidate_rows`); the index contributes nominations only.
    """
    from bramber import index as index_mod  # lazy: the stdlib path never pays for this
    noms = index_mod.search(root, statement, k=k, kinds=("claim", "contradiction"),
                            embedder=embedder)
    rows, stale = candidate_rows(root, noms)
    _record_shown(root, "claims-like", f"--like {statement!r}", rows)
    return {"shape": "like", "query": statement, "count": len(rows), "candidates": rows,
            "stale_nominations": stale, "topics": topic_vocabulary(root)}


def feed_pack(root, extract_rel: str, *, limit: int = 200, embedder=None) -> dict:
    """Shape B (`specs/10` §4.2): the pre-scan candidate pack for one extract.

    Coarse on purpose — every key similar to ANY of the extract's sections, one pre-filtered
    feed with no mid-scan round trips. Safe to serve coarse because the rows are the same M2
    atoms as every other shape: the agent still reads each statement and copies `reuse_as`
    whole, and materialize still verifies membership and witness. A bad nomination costs
    recall, never truth.
    """
    from bramber import index as index_mod
    noms = index_mod.nominate_for_extract(root, extract_rel, limit=limit, embedder=embedder)
    rows, stale = candidate_rows(root, noms)
    _record_shown(root, "claims-pack", extract_rel, rows)
    return {"shape": "pack", "extract": extract_rel, "count": len(rows), "candidates": rows,
            "stale_nominations": stale, "topics": topic_vocabulary(root)}


def _slug_for(source_rel: Optional[str]) -> Optional[str]:
    """`_bramber/extracts/<slug>.md` -> `<slug>`. The units file is keyed the same way."""
    if not source_rel:
        return None
    return Path(source_rel).stem or None


def units_for_source(scans: list, source_type_by_slug: Optional[dict] = None,
                     keys: Optional["KeyResolution"] = None) -> list:
    """The Units one source contributes, from that source's scan(s).

    **This is where dedup's first half happens** (specs/07 §3.3, unchanged by the redesign):
    repeated claims collapse *within* a source, so an insistent stakeholder restating a position
    five times contributes one unit rather than five. That is the length-bias fix, and it is the
    whole reason the product exists.

    The second half — do NOT collapse across sources; count them instead — deliberately does not
    happen here. It happens at selection, where units from every source meet
    (`compile.select_units`), because that is the only place the count is knowable.
    """
    source_type_by_slug = source_type_by_slug or {}
    # `keys` is corpus-wide and must be, because whether a key is a reuse depends on what OTHER
    # sources minted. `materialize` computes it once over every scan and passes it down. Resolving
    # from only the scans in hand — the fallback — is the honest local answer for a caller that has
    # only those, and is what makes this function usable directly in a test.
    if keys is None:
        keys = resolve_keys(scans, [s.source for s in scans if s.source])
    by_key: dict[tuple, Unit] = {}
    for s in scans:
        if s.discarded or not s.source:
            continue
        slug = _slug_for(s.source)
        tier = RELIABILITY_BY_SOURCE_TYPE.get(
            source_type_by_slug.get(slug, ""), DEFAULT_RELIABILITY_TIER)
        # A list from day one, even at length 1 — the shape is what lets a unit gain
        # corroborating sources later without a schema break (specs/08 §4.2).
        prov = {"source_artifacts": [{
            "extract_path": s.source, "scan_path": s.path, "reliability_tier": tier}]}

        def add(kind: str, key: str, payload: dict) -> None:
            ident = (kind, key)
            if ident in by_key:
                return                        # within-source collapse: first statement wins
            by_key[ident] = Unit(kind=kind, payload=payload, provenance=dict(prov))

        for c in s.claims:
            # Resolved at materialization, not at authoring: the agent writes `CLAIM-001` and the
            # namespace is stamped from the source it was reading. A key it copied from
            # `bramber claims` resolves against the minted set and passes through untouched, which
            # is what keeps reuse — and therefore corroboration — working.
            key = keys.final(s.path, "claim", c.key)
            add("claim", key, {
                "claim_key": key, "statement": c.statement,
                "evidence_strength": c.evidence_strength, "recency": c.recency,
                "topics": c.topics})

        for e in s.entities:
            add("entity", e.entity_key, {
                "entity_key": e.entity_key, "entity_name": e.entity_name, "gloss": e.gloss,
                "role": e.role, "stance": e.stance, "status": e.status, "aliases": e.aliases,
                "topics": e.topics})

        for t in s.terms:
            add("term", t.term_key, {
                "term_key": t.term_key, "term_name": t.term_name, "gloss": t.gloss,
                "status": t.status, "relates_to": t.relates_to, "topics": t.topics})

        # Contradiction keys are namespaced by the same rule and for the same reason: they merge
        # corpus-wide, so an unqualified `CONTRA-001` minted independently by two sources would
        # fuse two unrelated tensions into one register entry. Qualified into a local name rather
        # than written back onto the dataclass — `Scan` holds what the agent AUTHORED, and
        # `materialize` needs that to tell a mint from a reuse.
        for x in s.contradictions:
            ckey = keys.final(s.path, "contradiction", x.key)
            # The sides carry their own extract paths and are NOT folded into `source_artifacts`:
            # a compared-with source supplies the contrast, it does not assert the contradiction,
            # and folding it in would inflate `support` — the open tension in
            # decisions/2026-08-05, answered by keeping a separate provenance list on the payload.
            add("contradiction", ckey, {
                "contradiction_key": ckey, "statement": x.statement, "sides": x.sides,
                "resolution": x.resolution, "resolution_status": x.resolution_status,
                "topics": x.topics})

    return [by_key[k] for k in sorted(by_key, key=lambda t: tuple(str(p) for p in t))]
