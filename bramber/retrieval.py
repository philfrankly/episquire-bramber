"""bramber retrieval — the agentic surface's logic: search, tensions, expansion.

Canonical spec: `specs/10-retrieval-over-the-claim-store.md` §6 (Phase 3), composing Phase 0
(`meta.contradictions_for`), Phase 1 (`bramber.index`) and Phase 2 (traversal, here) — as
ruled by `specs/11`. This module is the LOGIC; `bramber.retrieval_server` is the thin MCP
registration over it, so every tool is testable without an MCP client and the server module
can import its dependency eagerly the way `engine/server.py` does.

**Placement, per the ruling:** not the engine. The engine is domain-blind and stdlib-only and
`bramber.db` does not index units — the unit store lives on disk. These tools live at the
`compile.py` layer (domain-blind by correction): the search filter IS the selector's predicate
vocabulary — `search_units` builds a selector and runs `compile.select_units` unchanged, so
`match.<field>` here and `match.<field>` in a view.md cannot drift in semantics, and support
counts, reliability floors, variants and divergence flags come from the one merge that
produces the per-view bullet.

**Nominate, decide, assert — at serve time too.** The index contributes candidate idents and
scores; every payload, provenance entry and flag in a served row is read from the store at
serve time (G2). Traversal follows only relationships the record contains; the one inferred
adjacency (same source + shared topic) is served in its own clearly-labelled list, because a
unit found through an inferred hop is returned on its own recorded provenance — the hop
nominates, the provenance asserts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from bramber import compile as _compile
from bramber import meta as meta_mod
from bramber import scan as scan_mod

# The payload field that is each kind's stored identity, and the field whose wording
# `variants`/`divergent` should track. Declared once here; the index carries its own copy of
# the key half for the same table — both are projections of the scan's payload contract.
_KIND_FIELDS = {
    "claim": ("claim_key", "statement"),
    "contradiction": ("contradiction_key", "statement"),
    "entity": ("entity_key", "gloss"),
    "term": ("term_key", "gloss"),
}


def _units_files(data_root) -> list:
    units_dir = Path(data_root).resolve() / "_bramber" / "units"
    return sorted(units_dir.glob("*.json")) if units_dir.exists() else []


def _entries_for_kind(data_root, kind: str, match: Optional[dict]) -> dict:
    """One `select_units` pass for one kind, indexed by dedup key. The merge arithmetic —
    support, floor, variants, divergence, provenance dedup on extract_path — is compile's,
    reused unchanged, which is what makes serving it here safe rather than convenient."""
    key_field, subject = _KIND_FIELDS[kind]
    sel = {
        "kind": kind,
        "match": {k: set(v) for k, v in (match or {}).items()},
        "dedup_by": key_field,
        "order_by": key_field,
        "project": [subject],
        "section": "Retrieved units",
        "load_when": None,
        "description": None,
    }
    entries = _compile.select_units(_units_files(data_root), sel)
    return {e["dedup_key"]: e for e in entries}


def search_units(data_root, query: str, *, k: int = 10,
                 kinds: Optional[Iterable[str]] = None,
                 match: Optional[dict] = None, embedder=None) -> dict:
    """Hybrid search over the store: the index nominates, the store serves.

    `match` is the selector's own predicate vocabulary — `{field: [allowed, ...]}`, any-of
    over list-valued payload fields, exact over scalars — applied by `compile.select_units`
    itself, so a filter that would drift from view semantics cannot exist. Rows carry the
    representative unit plus the merge-derived facts (`support`, `reliability_floor`,
    `variants`, `divergent`) and the full provenance list; every citation resolves on disk
    because it came from the store, not the cache.
    """
    from bramber import index as index_mod  # lazy: [embed]-gated path
    wanted = list(kinds) if kinds else sorted(_KIND_FIELDS)
    # Over-nominate then filter: a match predicate may reject shortlisted keys, and serving
    # fewer than k because a filter fired is correct, while re-querying to fill the gap
    # would trade determinism for padding.
    noms = index_mod.search(data_root, query, k=max(k * 5, 25), kinds=wanted,
                            embedder=embedder)
    by_kind = {kind: _entries_for_kind(data_root, kind, match)
               for kind in {n["kind"] for n in noms}}

    rows, stale = [], []
    for n in noms:
        entry = by_kind.get(n["kind"], {}).get(n["key"])
        if entry is None:
            # Nominated but not served: either the index lags the store (stale) or a match
            # predicate rejected it (filtered) — both are the shortlist doing its job, and
            # neither may silently shrink the answer.
            stale.append(f"{n['kind']}:{n['key']}")
            continue
        rows.append({
            "kind": n["kind"], "key": n["key"], "score": n["score"],
            "unit": entry["unit"],
            "support": entry["support"],
            "reliability_floor": entry["reliability_floor"],
            "variants": entry["variants"],
            "divergent": entry["divergent"],
            "source_artifacts": entry["source_artifacts"],
        })
        if len(rows) >= k:
            break
    return {"query": query, "count": len(rows), "units": rows,
            "not_served": stale}


def contradictions_for(data_root, claim_key: str) -> dict:
    """Phase 0's primitive, served: every recorded tension citing this exact stored key, sides
    flagged (`unresolved` / `side_witness_mismatch`), never dropped or re-pointed.

    `unattributable` carries the tensions that cite something unresolvable — possibly this
    claim, and the record cannot say. An assistant reading `count` alone on such a corpus
    reports a contested claim as uncontested (screen finding S0-1)."""
    return meta_mod.contradictions_for(data_root, claim_key)


# ---------------------------------------------------------------------------
# expand — traversal over what the record already contains
# ---------------------------------------------------------------------------

def _graph(data_root) -> tuple:
    """Adjacency over RECORDED relationships only, plus the raw per-key facts needed to serve
    nodes fresh. Edges: unit—source (provenance), unit—topic (payload.topics),
    contradiction—claim (a written `side:`), term—entity/term (`relates_to`),
    entity—entity (an `aliases` entry naming the other's key). Nothing inferred enters."""
    adj: dict = {}
    facts: dict = {}

    def link(a: str, b: str, relation: str) -> None:
        adj.setdefault(a, set()).add((b, relation))
        adj.setdefault(b, set()).add((a, relation))

    records = meta_mod.unit_records(data_root)
    name_to_key = {}
    for rec in records:
        u = rec["unit"]
        p = u.get("payload") or {}
        for kind, (key_field, _) in _KIND_FIELDS.items():
            if u.get("kind") == kind and p.get(key_field):
                name_to_key.setdefault(scan_mod._norm_key(str(p.get(key_field))),
                                       f"{kind}:{p[key_field]}")

    for rec in records:
        u = rec["unit"]
        kind = u.get("kind")
        if kind not in _KIND_FIELDS:
            continue
        p = u.get("payload") or {}
        key = p.get(_KIND_FIELDS[kind][0])
        if not key:
            continue
        node = f"{kind}:{key}"
        facts.setdefault(node, {"kind": kind, "key": key, "sources": set(), "topics": set()})
        for a in (u.get("provenance") or {}).get("source_artifacts") or []:
            if a.get("extract_path"):
                facts[node]["sources"].add(a["extract_path"])
                link(node, f"source:{a['extract_path']}", "provenance")
        for t in p.get("topics") or []:
            facts[node]["topics"].add(str(t))
            link(node, f"topic:{t}", "topic")
        if kind == "contradiction":
            for side in p.get("sides") or []:
                ref = side.get("ref")
                if ref:
                    # As written, resolved by exact equality against nothing — the side names
                    # a stored key or it dangles visibly; `contradictions_for` is where
                    # verification is served.
                    link(node, f"claim:{ref}", "side")
        if kind == "term":
            for rel in p.get("relates_to") or []:
                target = name_to_key.get(scan_mod._norm_key(str(rel)))
                if target:
                    link(node, target, "relates_to")
        if kind == "entity":
            for alias in p.get("aliases") or []:
                target = name_to_key.get(scan_mod._norm_key(str(alias)))
                if target and target != node:
                    link(node, target, "alias")
    return adj, facts


def expand(data_root, kind: str, key: str, *, depth: int = 1) -> dict:
    """From one unit outward, over relationships the record contains, depth-bounded.

    Every returned node is served FRESH from the store with its own recorded provenance, and
    every edge is one the record asserts — a `side:` an agent wrote, a `relates_to` a source
    carried, a provenance row lineage already holds. Co-occurrence (same source + shared
    topic with the start unit) is permitted for NOMINATION only and comes back in its own
    `co_nominated` list: the hop is never presented as an edge, because a diagram-shaped
    assertion the record does not contain is the failure this system exists to prevent.
    """
    depth = max(1, min(int(depth), 4))
    adj, facts = _graph(data_root)
    start = f"{kind}:{key}"
    if start not in facts:
        return {"start": {"kind": kind, "key": key}, "found": False,
                "nodes": [], "edges": [], "co_nominated": []}

    seen = {start}
    frontier = [start]
    edges: set = set()
    for _ in range(depth):
        nxt = []
        for node in frontier:
            for other, relation in sorted(adj.get(node, ())):
                edges.add(tuple(sorted((node, other))) + (relation,))
                if other not in seen:
                    seen.add(other)
                    # Topic and source nodes are hops, not units — traversal passes through
                    # them (that is how claim—topic—claim adjacency works) but only unit
                    # nodes are expanded further and served.
                    nxt.append(other)
        frontier = nxt

    unit_nodes = sorted(n for n in seen if n in facts)
    entries_cache: dict = {}

    def serve(node: str) -> dict:
        k_, key_ = facts[node]["kind"], facts[node]["key"]
        if k_ not in entries_cache:
            entries_cache[k_] = _entries_for_kind(data_root, k_, None)
        e = entries_cache[k_].get(key_) or {}
        return {"kind": k_, "key": key_,
                "unit": e.get("unit"),
                "support": e.get("support"),
                "reliability_floor": e.get("reliability_floor"),
                "source_artifacts": e.get("source_artifacts") or []}

    co = []
    start_facts = facts[start]
    for node, f in sorted(facts.items()):
        if node in seen:
            continue
        if (f["sources"] & start_facts["sources"]) and (f["topics"] & start_facts["topics"]):
            co.append(serve(node))

    return {
        "start": {"kind": kind, "key": key},
        "found": True,
        "depth": depth,
        "nodes": [serve(n) for n in unit_nodes],
        "edges": [{"a": a, "b": b, "relation": rel} for a, b, rel in sorted(edges)],
        "co_nominated": co,
        "note": ("Edges are relationships the record asserts. `co_nominated` units were "
                 "reached by inferred adjacency (same source + shared topic) — the hop "
                 "nominates them; each unit's own recorded provenance is what asserts."),
    }
