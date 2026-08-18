"""The retrieval surface (`bramber/retrieval.py`) — specs/10 §6 as ruled by specs/11 S3.

The centrepiece is the scripted assistant transcript the spec names as the verify recipe:
question → `search_units` → `contradictions_for` on a hit → `expand` outward — with **every
returned citation resolving on disk**. Around it, the two structural promises: the match
filter IS the selector's predicate vocabulary (reused, not reimplemented), and the engine
server is untouched.

Run:  cd bramber && python -m pytest tests/test_retrieval.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from bramber import index as index_mod, ingest, retrieval, scan

DIMS = 32
REPO = Path(__file__).resolve().parent.parent


class FakeEmbedder:
    def __call__(self, texts, *, kind="document"):
        out = []
        for t in texts:
            v = [0.0] * DIMS
            for tok in index_mod._tokens(t):
                h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
                v[h % DIMS] += 1.0
            out.append(v)
        return out


A_CLAIM = "The cutover date is fixed."
B_CLAIM = "The cutover date is under review."


def _source(tmp_path: Path, slug: str, sections: str) -> None:
    extracts = tmp_path / "_bramber" / "extracts"
    scans = tmp_path / "_bramber" / "scans"
    extracts.mkdir(parents=True, exist_ok=True)
    scans.mkdir(parents=True, exist_ok=True)
    (extracts / f"{slug}.md").write_text(
        "---\ntitle: t\nsource_type: article\n---\nbody\n", encoding="utf-8")
    (scans / f"{slug}.md").write_text(
        f"---\nsource: _bramber/extracts/{slug}.md\nscan_date: 2026-08-07\n"
        f"discarded: false\n---\n{sections}", encoding="utf-8")


def _corpus(tmp_path: Path) -> FakeEmbedder:
    tok_a = scan.statement_token(A_CLAIM)
    _source(tmp_path, "minutes_md__aaaaaaaa", f"""
## Claims

- **CLAIM-001** - {A_CLAIM}
  - evidence: strong
  - topics: schedule

## Entities

- **Acme Corp** - supplies the integration middleware.
  - role: vendor
  - aliases: ACME
  - topics: vendor-risk

## Novel Concepts

- **cutover** - the window in which the old system stops and the new one starts.
  - relates_to: Acme Corp
  - topics: schedule
""")
    _source(tmp_path, "review_md__bbbbbbbb", f"""
## Claims

- **CLAIM-001** - {B_CLAIM}
  - evidence: moderate
  - topics: schedule

## Contradictions

- **CONTRA-001** - The minutes call the date fixed; the review keeps it open.
  - side: CLAIM-aaaaaaaa-001={tok_a} | _bramber/extracts/minutes_md__aaaaaaaa.md | recorded as fixed
  - side: CLAIM-bbbbbbbb-001 | _bramber/extracts/review_md__bbbbbbbb.md | under review
  - topics: schedule
""")
    ingest.materialize(tmp_path)
    fe = FakeEmbedder()
    index_mod.build(tmp_path, embedder=fe, model="fake-1")
    return fe


def _assert_citations_resolve(tmp_path: Path, artifacts) -> None:
    assert artifacts, "a served unit with no provenance is not a served unit"
    for a in artifacts:
        assert (tmp_path / a["extract_path"]).exists(), a
        assert (tmp_path / a["scan_path"]).exists(), a


def test_the_assistant_transcript_end_to_end(tmp_path: Path):
    """The spec's verify recipe as one scripted session: ask, hit, check tensions, expand —
    and every citation along the way resolves to a real artifact on disk."""
    fe = _corpus(tmp_path)

    # 1. Question → search.
    out = retrieval.search_units(tmp_path, "is the cutover date fixed", k=5,
                                 kinds=["claim"], embedder=fe)
    assert out["count"] >= 2, "both sides of the tension are claims about this question"
    hit = out["units"][0]
    for row in out["units"]:
        _assert_citations_resolve(tmp_path, row["source_artifacts"])

    # 2. Any surface that returns a claim can also return the tensions citing it.
    tensions = retrieval.contradictions_for(tmp_path, hit["key"])
    assert tensions["count"] == 1
    (entry,) = tensions["contradictions"]
    refs = {s["ref"] for s in entry["sides"]}
    assert {"CLAIM-aaaaaaaa-001", "CLAIM-bbbbbbbb-001"} <= refs
    assert all(s["unresolved"] is False and s["side_witness_mismatch"] is False
               for s in entry["sides"])
    _assert_citations_resolve(tmp_path, entry["source_artifacts"])

    # 3. Expand from the hit: the contradiction arrives over its recorded `side:` edge.
    graph = retrieval.expand(tmp_path, "claim", hit["key"], depth=1)
    assert graph["found"]
    node_ids = {(n["kind"], n["key"]) for n in graph["nodes"]}
    assert ("contradiction", entry["contradiction_key"]) in node_ids
    assert any(r["relation"] == "side" for r in graph["edges"])
    for n in graph["nodes"]:
        _assert_citations_resolve(tmp_path, n["source_artifacts"])


def test_match_filters_are_the_selector_vocabulary(tmp_path: Path):
    """`match.evidence_strength: strong` here must mean exactly what it means in a view.md —
    same predicate, same code path (`compile.select_units`), so drift is structurally
    impossible rather than merely untested."""
    fe = _corpus(tmp_path)
    out = retrieval.search_units(tmp_path, "cutover date", kinds=["claim"],
                                 match={"evidence_strength": ["strong"]}, embedder=fe)
    served = {r["key"] for r in out["units"]}
    assert served == {"CLAIM-aaaaaaaa-001"}
    assert "claim:CLAIM-bbbbbbbb-001" in out["not_served"], \
        "a filtered nomination is named, never silently dropped"


def test_search_serves_the_merge_derived_facts(tmp_path: Path):
    fe = _corpus(tmp_path)
    out = retrieval.search_units(tmp_path, "integration middleware vendor",
                                 kinds=["entity"], embedder=fe)
    row = next(r for r in out["units"] if r["key"] == "acme corp")
    assert row["support"] == 1 and row["reliability_floor"] == "reported"
    assert row["variants"], "variants ride every served row — a glossary needs them"


def test_expand_follows_relates_to_and_labels_co_occurrence(tmp_path: Path):
    _corpus(tmp_path)
    graph = retrieval.expand(tmp_path, "term", "cutover", depth=1)
    node_ids = {(n["kind"], n["key"]) for n in graph["nodes"]}
    assert ("entity", "acme corp") in node_ids, "`relates_to` is a recorded edge"
    assert any(r["relation"] == "relates_to" for r in graph["edges"])
    # A's claim shares a source AND a topic with the term but no recorded edge reaches it at
    # depth 1 — it must arrive as a co-nomination, never as an edge.
    co = {(n["kind"], n["key"]) for n in graph["co_nominated"]}
    assert ("claim", "CLAIM-aaaaaaaa-001") in co
    assert not any("CLAIM-aaaaaaaa-001" in (r["a"], r["b"]) for r in graph["edges"]), \
        "an inferred hop presented as an edge asserts what the record does not"


def test_expand_from_an_unknown_key_returns_empty_not_error(tmp_path: Path):
    _corpus(tmp_path)
    out = retrieval.expand(tmp_path, "claim", "CLAIM-deadbeef-9")
    assert out == {"start": {"kind": "claim", "key": "CLAIM-deadbeef-9"}, "found": False,
                   "nodes": [], "edges": [], "co_nominated": []}


def test_the_engine_server_is_untouched():
    """S3's placement ruling: the retrieval surface is a SIBLING. The engine server must not
    know it exists — no import, no reference, no shared registration."""
    src = (REPO / "bramber" / "engine" / "server.py").read_text(encoding="utf-8")
    assert "retrieval" not in src
