"""The feed shapes (`scan.feed_like` / `scan.feed_pack` / the full feed) — specs/11 S1b.

The properties under test, each a ruling:

  - **M2** — every shape serves the same candidate row: `reuse_as` + `statement` + `sources`
    + `support` + `evidence` + `topics`, key and witness as one copyable atom;
  - **G2** — tokens are read fresh from the store at serve time; the index contributes
    nominations only, so a repair that rewords a statement is served correctly by a feed
    whose vectors are still stale (the freshness gate — mutation-verified red);
  - **G5** — every shape carries the complete topic vocabulary, never a shortlist of it;
  - **G9** — every pack/like call leaves a shown-candidate run record, converting
    "the agent saw CLAIM-007 and minted anyway" from unknowable into evidence;
  - **M4** — an endorser's phrasing is a retrieval text for the merged key, so the recall
    replay (query with the endorser's words) renominates the minter's key;
  - **G7** — no `[embed]`, or no index: the full feed, a stderr notice, no error. The missing
    extra is forced by the `no_embed_extra` fixture, never read from the environment
    (`tests/conftest.py` says why).

Run:  cd bramber && python -m pytest tests/test_feed_shapes.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bramber import cli, index as index_mod, ingest, run as run_mod, scan

# 256, not the 32 the other test files use: the recall replay needs token-DISJOINT texts to
# be near-orthogonal, and at 32 dims hash collisions gave a disjoint pair cosine ~0.38 —
# enough to outrank a genuine one-token overlap and quietly re-blunt the F1 gate.
DIMS = 256


class FakeEmbedder:
    """Deterministic hashed bag-of-tokens vectors; overlapping word sets land near each
    other in cosine, which is all these tests need from an embedding."""

    def __call__(self, texts, *, kind="document"):
        out = []
        for t in texts:
            v = [0.0] * DIMS
            for tok in index_mod._tokens(t):
                h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
                v[h % DIMS] += 1.0
            out.append(v)
        return out


A_CLAIM = "The cutover date is fixed for the ninth of March."
# Fully token-disjoint from A_CLAIM (screen finding F1): the recall replay queries in B's
# words, and any shared content token would let the minter's own entry answer the query —
# the test would then pass with M4 gutted, which is a gate that cannot fail.
B_PHRASING = "Deployment go-live locked; zero slippage permitted."


def _source(tmp_path: Path, slug: str, sections: str, *, body: str = "body\n") -> None:
    extracts = tmp_path / "_bramber" / "extracts"
    scans = tmp_path / "_bramber" / "scans"
    extracts.mkdir(parents=True, exist_ok=True)
    scans.mkdir(parents=True, exist_ok=True)
    (extracts / f"{slug}.md").write_text(
        f"---\ntitle: t\nsource_type: article\n---\n{body}", encoding="utf-8")
    (scans / f"{slug}.md").write_text(
        f"---\nsource: _bramber/extracts/{slug}.md\nscan_date: 2026-08-07\n"
        f"discarded: false\n---\n{sections}", encoding="utf-8")


def _corpus(tmp_path: Path) -> None:
    """A mints and grades a claim, names an entity, coins a term; B corroborates the claim
    in entirely different words (a witnessed reuse — zero token overlap with A's phrasing,
    which is what makes the recall replay a real test of M4 rather than of the tokenizer)."""
    _source(tmp_path, "minutes_md__aaaaaaaa", f"""
## Claims

- **CLAIM-001** - {A_CLAIM}
  - evidence: strong
  - topics: schedule, deadline-integrity

## Entities

- **Acme Corp** - supplies the integration middleware.
  - role: vendor
  - topics: vendor-risk
""", body="## Schedule\n\nThe cutover date is fixed for the ninth of March.\n\n"
          "## Vendors\n\nAcme Corp supplies the integration middleware.\n")
    tok = scan.statement_token(A_CLAIM)
    _source(tmp_path, "review_md__bbbbbbbb", f"""
## Claims

- **CLAIM-aaaaaaaa-001={tok}** - {B_PHRASING}
  - evidence: moderate
  - topics: schedule, go-live

## Novel Concepts

- **cutover** - the window in which the old system stops and the new one starts.
  - topics: migration-sequencing
""")
    # A distractor sharing one token with B_PHRASING ("deployment"). Without M4 the replay
    # query can only reach A's key through hash-collision noise, and this claim's genuine
    # token overlap outranks that noise — which is what makes the recall replay a gate that
    # can fail (screen finding F1) instead of a rank-0 assertion over a one-claim corpus.
    _source(tmp_path, "budget_md__cccccccc", """
## Claims

- **CLAIM-900** - Deployment tooling budget approved.
  - evidence: weak
""")
    ingest.materialize(tmp_path)


def _indexed_corpus(tmp_path: Path) -> FakeEmbedder:
    _corpus(tmp_path)
    fe = FakeEmbedder()
    index_mod.build(tmp_path, embedder=fe, model="fake-1")
    return fe


# --- M2: one row shape everywhere ---------------------------------------------

def test_the_full_feed_row_carries_the_m2_fields(tmp_path: Path):
    _corpus(tmp_path)
    by_key = {e["key"]: e for e in scan.known_keys(tmp_path)}
    e = by_key["CLAIM-aaaaaaaa-001"]
    assert e["support"] == 2 == len(e["sources"])
    assert e["statement"] == A_CLAIM, "the feed displays the MINTER's phrasing"
    assert e["evidence"] == "strong", "and the minter's grade, not an endorser's"
    assert set(e["topics"]) == {"schedule", "deadline-integrity", "go-live"}, \
        "topics union across contributors — an endorser's tag is information"
    assert e["reuse_as"] == f"{e['key']}={e['witness']}"


def test_the_shortlist_serves_the_same_rows_as_the_full_feed(tmp_path: Path):
    fe = _indexed_corpus(tmp_path)
    out = scan.feed_like(tmp_path, "cutover date fixed march", embedder=fe)
    row = next(r for r in out["candidates"] if r["key"] == "CLAIM-aaaaaaaa-001")
    full = next(e for e in scan.known_keys(tmp_path) if e["key"] == "CLAIM-aaaaaaaa-001")
    assert {k: v for k, v in row.items() if k != "score"} == full, \
        "a shortlist row IS a full-feed row — same atoms, plus a score"


def test_existing_readers_of_the_claims_projection_are_untouched(tmp_path: Path):
    _corpus(tmp_path)
    for row in scan.known_claims(tmp_path):
        assert {"claim_key", "statement", "sources", "reuse_as"} <= set(row)


# --- G5: full topics on every shape -------------------------------------------

def test_every_shape_serves_the_complete_topic_vocabulary(tmp_path: Path):
    fe = _indexed_corpus(tmp_path)
    want = ["deadline-integrity", "go-live", "migration-sequencing", "schedule", "vendor-risk"]
    assert scan.topic_vocabulary(tmp_path) == want
    like = scan.feed_like(tmp_path, "anything at all", embedder=fe)
    assert like["topics"] == want, \
        "topics are never shortlisted — a shortlisted vocabulary manufactures synonym splits"
    pack = scan.feed_pack(tmp_path, "_bramber/extracts/minutes_md__aaaaaaaa.md", embedder=fe)
    assert pack["topics"] == want, "the pack shape carries the full vocabulary too (F6)"


# --- G2: tokens fresh, vectors stale-ok (the freshness gate) -------------------

def test_rows_are_read_fresh_from_the_store_while_the_index_is_stale(tmp_path: Path):
    """The repair path: a human rewords the minted statement (scan edit + materialize) and
    nobody rebuilds the index. The stale vectors still nominate; the served row must carry
    the NEW statement and the NEW reuse_as token — an agent copying from this feed endorses
    what the store holds now, not what the cache remembers."""
    fe = _indexed_corpus(tmp_path)
    reworded = "The cutover date is fixed for the tenth of March."
    scan_path = tmp_path / "_bramber" / "scans" / "minutes_md__aaaaaaaa.md"
    scan_path.write_text(scan_path.read_text(encoding="utf-8").replace(A_CLAIM, reworded),
                         encoding="utf-8")
    ingest.materialize(tmp_path)

    # The cache is genuinely stale — the precondition that makes this test mean something.
    cached = [e["text"] for e in index_mod.load(tmp_path)["entries"]
              if e["key"] == "CLAIM-aaaaaaaa-001"]
    assert A_CLAIM in cached and reworded not in cached

    out = scan.feed_like(tmp_path, "cutover date fixed march", embedder=fe)
    row = next(r for r in out["candidates"] if r["key"] == "CLAIM-aaaaaaaa-001")
    assert row["statement"] == reworded, "the statement is the store's, never the cache's"
    assert row["reuse_as"] == f"CLAIM-aaaaaaaa-001={scan.statement_token(reworded)}", \
        "the copyable token quotes the CURRENT minted statement"


def test_a_stale_nomination_is_named_never_served(tmp_path: Path, capsys):
    """The index remembers the MINTER of a key the corpus withdrew (the repair doctrine's
    withdrawal case). The stale cache still nominates the dead key; the feed must not serve
    it — and must not drop it silently either: `stale_nominations` names it, because a
    shrunk shortlist with no explanation reads as 'nothing similar exists'.

    (Screen finding F2: the first version of this test withdrew the ENDORSER, whose key
    survives through the minter, so the stale branch was never reached and nothing asserted
    `stale_nominations` at all — a gate that cannot fail.)"""
    fe = _indexed_corpus(tmp_path)
    (tmp_path / "_bramber" / "scans" / "minutes_md__aaaaaaaa.md").unlink()
    (tmp_path / "_bramber" / "extracts" / "minutes_md__aaaaaaaa.md").unlink()
    (tmp_path / "_bramber" / "units" / "minutes_md__aaaaaaaa.json").unlink()
    ingest.materialize(tmp_path)  # B's endorsement degrades loudly; A's mint is gone

    out = scan.feed_like(tmp_path, "cutover date fixed march", embedder=fe)
    assert "claim:CLAIM-aaaaaaaa-001" in out["stale_nominations"], \
        "the withdrawn key was nominated by the stale cache and must be NAMED"
    assert all(r["key"] != "CLAIM-aaaaaaaa-001" for r in out["candidates"]), \
        "a key the store no longer holds must never be served as a candidate"


# --- G9: the shown-candidate record -------------------------------------------

def test_a_pack_call_records_what_it_showed(tmp_path: Path):
    fe = _indexed_corpus(tmp_path)
    extract_rel = "_bramber/extracts/minutes_md__aaaaaaaa.md"
    out = scan.feed_pack(tmp_path, extract_rel, embedder=fe)
    assert out["candidates"], "a pack over an overlapping corpus must nominate something"

    outcomes = run_mod.latest_outcomes(tmp_path)
    for row in out["candidates"]:
        e = outcomes.get(f"{row['key']}|shown-candidate")
        assert e and e["detail"] == extract_rel, \
            f"served candidate {row['key']} left no shown-candidate record"


# --- M4 + recall: the replay and the paraphrase injection ----------------------

def test_recall_replay_an_endorsers_phrasing_renominates_the_minters_key(tmp_path: Path):
    """B corroborated A's claim in words sharing no content token with A's statement. M4
    makes B's phrasing a retrieval text for the merged key, so querying in B's words must
    surface A's key — corroborated claims get MORE retrievable with every endorsement."""
    fe = _indexed_corpus(tmp_path)
    assert not index_mod._tokens(A_CLAIM) & index_mod._tokens(B_PHRASING), \
        "fixture drift: the phrasings must stay token-disjoint or this tests nothing — a " \
        "shared token lets the minter's own entry answer the query without M4"
    out = scan.feed_like(tmp_path, B_PHRASING, embedder=fe)
    assert out["candidates"], "with M4, B's phrasing is an entry for the merged key"
    assert out["candidates"][0]["key"] == "CLAIM-aaaaaaaa-001"


def test_paraphrase_injection_a_reworded_duplicate_surfaces(tmp_path: Path):
    fe = _indexed_corpus(tmp_path)
    out = scan.feed_like(tmp_path, "the date of the cutover is now fixed", embedder=fe)
    assert any(r["key"] == "CLAIM-aaaaaaaa-001" for r in out["candidates"]), \
        "a reworded near-duplicate must nominate the existing key, or every paraphrase mints"


# --- G7: the exact degrade -----------------------------------------------------

def test_like_without_the_embed_extra_serves_the_full_feed(tmp_path: Path, capsys, no_embed_extra):
    """Real path, not a mock: the `no_embed_extra` fixture answers the one `find_spec` probe
    under `embed_available()`, and `cli.main` then takes its real degrade branch. The command
    answers with the FULL feed — same JSON shape as the no-flag call — plus a stderr notice."""
    assert not index_mod.embed_available()
    _corpus(tmp_path)
    cli.main(["claims", "--like", "anything", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert {"count", "claims", "keys", "topics"} <= set(out), "the degrade IS the full feed"
    assert "full feed" in captured.err and "error" not in captured.err.lower()


def test_an_empty_like_still_degrades_with_the_notice(tmp_path: Path, capsys):
    """Screen finding F3: `--like ""` is a present (if empty) query, and truthiness checks
    treated it as absent — a full feed with no notice, in exactly the place notices exist."""
    _corpus(tmp_path)
    cli.main(["claims", "--like", "", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert {"count", "claims", "keys", "topics"} <= set(json.loads(captured.out))
    assert "full feed" in captured.err, "the degrade must announce itself for an empty query"


def test_like_and_pack_together_are_refused(tmp_path: Path):
    _corpus(tmp_path)
    with pytest.raises(SystemExit, match="at most one"):
        cli.main(["claims", "--like", "x", "--pack", "y", "--root", str(tmp_path)])


def test_the_full_feed_cli_serves_topics_and_enriched_keys(tmp_path: Path, capsys):
    _corpus(tmp_path)
    cli.main(["claims", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert out["topics"] == scan.topic_vocabulary(tmp_path)
    row = next(e for e in out["keys"] if e["key"] == "CLAIM-aaaaaaaa-001")
    assert {"reuse_as", "statement", "sources", "support", "evidence", "topics"} <= set(row)
