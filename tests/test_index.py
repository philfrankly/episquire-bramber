"""The candidate index (`bramber/index.py`) — nomination, never assertion.

Three properties carry the weight:

  - **the index is envelope-derived and incremental** (specs/11 G1): built from
    `_bramber/units/*.json`, invalidated per-envelope by content sha, so a one-source edit
    re-embeds one source's texts and a deleted source takes its entries with it;
  - **search returns nominations only** (G2): `{kind, key, score}` rows with no statement, no
    witness, no `reuse_as` — the shape itself refuses the serve-from-cache mistake;
  - **the degrade is exact** (G7): with no `[embed]` extra installed, the stdlib import graph
    is untouched and only the commands whose entire job is the vectors refuse, with the
    install hint. The absence is forced by the `no_embed_extra` fixture rather than read from
    the environment (see `tests/conftest.py` for why), so the degrade path here is the real
    one whether or not `fastembed` is installed — only the `find_spec` probe under
    `embed_available()` is answered for it.

Every test injects a deterministic fake embedder (hashed bag-of-tokens, unit-normalized), so
nothing touches a network and similar word sets genuinely land near each other in cosine.

Run:  cd bramber && python -m pytest tests/test_index.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bramber import index as index_mod

DIMS = 32

# Captured at import, before any fixture can patch the attribute. The leak guard below needs a
# reference the `no_embed_extra` fixture cannot reach: reading `importlib.util.find_spec` inside
# that test would resolve through a leaked patch and compare it against itself — which is how the
# guard passed under a deliberately-leaking fixture the first time it was written.
_REAL_FIND_SPEC = importlib.util.find_spec


class FakeEmbedder:
    """Deterministic vectors from token counts; records every text it was asked to embed."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, texts, *, kind="document"):
        self.calls.append((kind, list(texts)))
        out = []
        for t in texts:
            v = [0.0] * DIMS
            for tok in index_mod._tokens(t):
                h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
                v[h % DIMS] += 1.0
            out.append(v)  # build unit-normalizes; the fake stays raw on purpose
        return out

    @property
    def embedded_texts(self):
        return [t for _, texts in self.calls for t in texts]


def _prov(slug):
    return {"source_artifacts": [{"extract_path": f"_bramber/extracts/{slug}.md",
                                  "scan_path": f"_bramber/scans/{slug}.md",
                                  "reliability_tier": "reported"}]}


def _envelope(tmp_path: Path, slug: str, units) -> Path:
    p = tmp_path / "_bramber" / "units" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "extract_path": f"_bramber/extracts/{slug}.md", "qname": slug,
        "units_produced_by": "test fixture", "units": units,
    }), encoding="utf-8")
    return p


def _claim(key, statement, *, slug, topics=()):
    return {"kind": "claim",
            "payload": {"claim_key": key, "statement": statement,
                        "evidence_strength": "strong", "recency": None,
                        "topics": list(topics)},
            "provenance": _prov(slug)}


def _entity(name, gloss, *, slug, aliases=()):
    return {"kind": "entity",
            "payload": {"entity_key": name.casefold(), "entity_name": name, "gloss": gloss,
                        "role": None, "stance": None, "status": None,
                        "aliases": list(aliases), "topics": []},
            "provenance": _prov(slug)}


def _corpus(tmp_path: Path):
    _envelope(tmp_path, "minutes__aaaaaaaa", [
        _claim("CLAIM-aaaaaaaa-001", "Revenue grew 22 percent year over year.",
               slug="minutes__aaaaaaaa", topics=["revenue-trajectory"]),
        _entity("Acme Corp", "supplies the integration middleware",
                slug="minutes__aaaaaaaa", aliases=["ACME"]),
    ])
    _envelope(tmp_path, "review__bbbbbbbb", [
        _claim("CLAIM-bbbbbbbb-001", "The vendor cannot staff the project before November.",
               slug="review__bbbbbbbb", topics=["vendor-risk"]),
    ])


# --- build: envelope-derived, incremental ------------------------------------

def test_build_derives_entries_from_the_envelopes(tmp_path: Path):
    _corpus(tmp_path)
    res = index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    assert res["envelopes"] == 2
    idx = index_mod.load(tmp_path)
    idents = {(e["kind"], e["key"]) for e in idx["entries"]}
    assert ("claim", "CLAIM-aaaaaaaa-001") in idents
    assert ("claim", "CLAIM-bbbbbbbb-001") in idents
    assert ("entity", "acme corp") in idents
    assert all(e.get("vector") for e in idx["entries"]), "every entry is embedded at build"


def test_an_unchanged_envelope_is_not_reembedded(tmp_path: Path):
    """The incremental contract: cost is O(changed sources), zero source re-reads, zero
    re-embedding of what did not move — the cost law specs/10 §9 preserves."""
    _corpus(tmp_path)
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")

    second = FakeEmbedder()
    res = index_mod.build(tmp_path, embedder=second, model="fake-1")
    assert res["embedded"] == 0
    assert second.calls == [], "an unchanged corpus must cost zero embedding calls"


def test_only_the_changed_envelope_is_reembedded(tmp_path: Path):
    _corpus(tmp_path)
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")

    _envelope(tmp_path, "review__bbbbbbbb", [
        _claim("CLAIM-bbbbbbbb-001", "The vendor cannot staff the project before November.",
               slug="review__bbbbbbbb"),
        _claim("CLAIM-bbbbbbbb-002", "Headcount will grow by forty this quarter.",
               slug="review__bbbbbbbb"),
    ])
    inc = FakeEmbedder()
    res = index_mod.build(tmp_path, embedder=inc, model="fake-1")
    # The changed envelope re-derives, but the surviving text's vector is reused — only the
    # genuinely new claim pays for an embedding.
    assert inc.embedded_texts == ["Headcount will grow by forty this quarter."]
    assert res["embedded"] == 1


def test_a_removed_envelope_takes_its_entries_with_it(tmp_path: Path):
    _corpus(tmp_path)
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    (tmp_path / "_bramber" / "units" / "review__bbbbbbbb.json").unlink()

    res = index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    assert res["removed_envelopes"] == ["review__bbbbbbbb"]
    idents = {(e["kind"], e["key"]) for e in index_mod.load(tmp_path)["entries"]}
    assert ("claim", "CLAIM-bbbbbbbb-001") not in idents


def test_a_changed_embed_model_invalidates_everything(tmp_path: Path):
    """Two models' vector spaces do not compare; a cosine across them is a number that looks
    like evidence. A model change is a full re-embed, never a merge."""
    _corpus(tmp_path)
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    re_run = FakeEmbedder()
    res = index_mod.build(tmp_path, embedder=re_run, model="fake-2")
    assert res["embedded"] == res["entries"] > 0
    assert index_mod.load(tmp_path)["embed_model"] == "fake-2"


def test_losing_the_index_is_a_nonevent(tmp_path: Path):
    _corpus(tmp_path)
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    first = index_mod.load(tmp_path)
    (tmp_path / "_bramber" / "index" / "index.json").unlink()
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    assert index_mod.load(tmp_path)["envelopes"] == first["envelopes"]


def test_build_writes_only_under_the_index_dir(tmp_path: Path):
    """The index asserts nothing — including on disk. A build touches its own cache and
    nothing else: no unit envelope, no db, no store surface."""
    _corpus(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    new = after - set(before)
    assert all(index_mod.index_dir(tmp_path) in p.parents for p in new), \
        f"build created files outside _bramber/index/: {sorted(new)}"
    assert all(p.read_bytes() == body for p, body in before.items()), \
        "build modified a file it does not own"


# --- search: nomination only --------------------------------------------------

def test_search_returns_nominations_and_nothing_else(tmp_path: Path):
    """G2 pinned as a shape: rows carry kind, key, score — no statement, no witness, no
    reuse_as. What an agent copies is read fresh from the store, never from this cache."""
    _corpus(tmp_path)
    fe = FakeEmbedder()
    index_mod.build(tmp_path, embedder=fe, model="fake-1")
    rows = index_mod.search(tmp_path, "revenue grew", embedder=fe)
    assert rows, "the query shares tokens with an indexed claim; something must nominate"
    assert all(set(r) == {"kind", "key", "score"} for r in rows), \
        f"a nomination row leaked payload fields: {rows[0]}"


def test_search_surfaces_a_paraphrased_statement(tmp_path: Path):
    _corpus(tmp_path)
    fe = FakeEmbedder()
    index_mod.build(tmp_path, embedder=fe, model="fake-1")
    rows = index_mod.search(tmp_path, "revenue was up 22 percent over the year",
                            embedder=fe, kinds=["claim"])
    assert rows[0]["key"] == "CLAIM-aaaaaaaa-001"


def test_search_keyword_half_catches_an_exact_alias(tmp_path: Path):
    """The stdlib half's whole job: exact terms an embedding fuzzes over. `ACME` appears only
    in the aliases list, and it must still nominate the entity."""
    _corpus(tmp_path)
    fe = FakeEmbedder()
    index_mod.build(tmp_path, embedder=fe, model="fake-1")
    rows = index_mod.search(tmp_path, "ACME", embedder=fe, kinds=["entity"])
    assert rows and rows[0]["key"] == "acme corp"


def test_search_is_deterministic(tmp_path: Path):
    _corpus(tmp_path)
    fe = FakeEmbedder()
    index_mod.build(tmp_path, embedder=fe, model="fake-1")
    a = index_mod.search(tmp_path, "vendor staffing", embedder=fe)
    b = index_mod.search(tmp_path, "vendor staffing", embedder=fe)
    assert a == b


def test_search_without_an_index_refuses_loudly(tmp_path: Path):
    with pytest.raises(SystemExit, match="no usable index on disk"):
        index_mod.search(tmp_path, "anything", embedder=FakeEmbedder())


def test_a_corrupt_index_is_refused_with_the_same_honesty(tmp_path: Path):
    """Screen finding F5: a corrupt cache used to be announced as absent, which sends an
    operator hunting for a directory that exists. The message now covers both facts."""
    _corpus(tmp_path)
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    (index_mod.index_dir(tmp_path) / "index.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing, unreadable"):
        index_mod.search(tmp_path, "anything", embedder=FakeEmbedder())


# --- nominate_for_extract (Shape B's pool) ------------------------------------

def test_nominate_for_extract_pools_candidates_across_sections(tmp_path: Path):
    _corpus(tmp_path)
    fe = FakeEmbedder()
    index_mod.build(tmp_path, embedder=fe, model="fake-1")
    extract = tmp_path / "_bramber" / "extracts" / "draft__cccccccc.md"
    extract.parent.mkdir(parents=True, exist_ok=True)
    extract.write_text(
        "---\ntitle: draft\nsource_type: article\n---\n"
        "## Finances\n\nRevenue grew 22 percent again.\n\n"
        "## Hiring\n\nThe vendor still cannot staff the project.\n", encoding="utf-8")
    rows = index_mod.nominate_for_extract(tmp_path, "_bramber/extracts/draft__cccccccc.md",
                                          embedder=fe)
    keys = {r["key"] for r in rows}
    assert {"CLAIM-aaaaaaaa-001", "CLAIM-bbbbbbbb-001"} <= keys, \
        "each section must pull its own neighbourhood into the pool"
    assert all(set(r) == {"kind", "key", "score"} for r in rows)


# --- the degrade (G7): no [embed] → stdlib path untouched ----------------------

def test_the_forced_absence_fixture_is_what_makes_the_degrade_tests_real(no_embed_extra):
    """The degrade tests below are honest only while something guarantees the extra reads as
    absent. That guarantee used to be the developer's environment — true until 2026-08-17,
    when `[embed]` was installed for a corpus run and two tests below began exercising the
    embed path while claiming to prove the degrade path. The guarantee is now the
    `no_embed_extra` fixture, and this is the tripwire on it.

    Kept as its own test rather than left as the fixture's internal assertion so the failure
    names the property directly instead of surfacing as an error in whichever degrade test
    happened to run first."""
    assert not index_mod.embed_available()


def test_the_forced_absence_does_not_leak_between_tests():
    """The fixture patches a module attribute on the real `importlib.util`, so its teardown is
    the only thing keeping that patch from following the rest of the suite. Deliberately takes
    no fixture: here `embed_available()` must report the true environment again.

    Compared against `_REAL_FIND_SPEC`, captured at import — not against a fresh
    `importlib.util.find_spec` lookup, which under a leaked patch would BE the patch and agree
    with itself. Mutation-verified 2026-08-17 against a fixture rewritten without teardown.

    One honest limit: a leak is only observable where the extra is actually installed. Without
    it both sides read False and the guard is vacuous — harmless, but it is not a substitute for
    running this on a machine that has `[embed]`."""
    assert index_mod.embed_available() == (
        _REAL_FIND_SPEC(index_mod.EMBED_PACKAGE) is not None)


def test_importing_the_cli_never_imports_the_embed_package():
    """The Stop hook's guarantee, extended: the cli import graph must not even *load* the
    index module, let alone the embed dependency. Checked in a subprocess so no other
    test's imports can contaminate the answer."""
    code = ("import sys; import bramber.cli; "
            "assert 'fastembed' not in sys.modules, 'embed dependency imported'; "
            "assert 'bramber.index' not in sys.modules, 'index imported eagerly'")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(Path(__file__).resolve().parent.parent))
    assert proc.returncode == 0, proc.stderr


def test_building_without_the_extra_refuses_with_the_install_hint(tmp_path: Path, no_embed_extra):
    _corpus(tmp_path)
    with pytest.raises(SystemExit, match=r"pip install bramber\[embed\]"):
        index_mod.build(tmp_path)  # no injected embedder, extra forced absent


def test_index_status_needs_no_embedder(tmp_path: Path):
    """--status is a stdlib question: what does the cache cover vs what is on disk."""
    _corpus(tmp_path)
    s = index_mod.status(tmp_path)
    assert s["present"] is False
    assert s["envelopes_on_disk"] == 2
    assert s["stale"] == ["minutes__aaaaaaaa", "review__bbbbbbbb"]

    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")
    s = index_mod.status(tmp_path)
    assert s["present"] is True and s["stale"] == []
