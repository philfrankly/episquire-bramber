"""The pre-run reconcile: `materialize` owns `_bramber/units/`, and owning it means retiring.

`materialize` iterates EXTRACTS, so before this gate existed the per-source loop could overwrite
an envelope but never remove one. A source whose body was edited got a new `content_sha`, hence a
new slug, hence a new envelope — and its old envelope stayed on disk, where five readers glob the
directory unconditionally. `compile._resolve` is one of them, so the stale units reached published
resources and their lineage.

Two orphan classes, deliberately opposite treatments, and both are tested here because getting
either backwards is the defect:

  - an orphaned **unit envelope** is derived data and one `materialize` rebuilds it -> DELETED;
  - an orphaned **scan** is the agent's interpretive read and nothing regenerates it -> REFUSED.

The refusal is also the safety interlock on the deletion. A destructive reconcile run against a
half-populated `extracts/` would discard a live store; in that state the scans are orphaned too,
so the refusal fires first and nothing is unlinked.

Run:  cd bramber && python -m pytest tests/test_store_reconcile.py

Findings: work/findings/2026-08-12-materialize-orphans-and-the-bare-key-notice.md §F1
"""

import collections
import json

import pytest

from pathlib import Path

from bramber import ingest
from bramber import scan


HEAD = "---\nsource: {src}\nscan_date: 2026-08-12\ndiscarded: false\n---\n"


def _extract(root: Path, slug: str, body: str = "body") -> None:
    d = root / "_bramber" / "extracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.md").write_text(
        f"---\ntitle: {slug}\nsource_type: article\n---\n{body}\n", encoding="utf-8")


def _scan(root: Path, slug: str, claims: str) -> None:
    d = root / "_bramber" / "scans"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.md").write_text(
        HEAD.format(src=f"_bramber/extracts/{slug}.md") + f"\n## Claims\n\n{claims}",
        encoding="utf-8")


def _envelopes(root: Path) -> list:
    return sorted(f.stem for f in (root / "_bramber" / "units").glob("*.json"))


def _support(root: Path) -> dict:
    """Support the way every reader computes it: glob the store, count distinct sources per key.

    Deliberately a re-implementation rather than a call into `compile.select_units` — the defect
    is that the DIRECTORY holds a file it should not, so the gate has to read the directory the
    same unconditional way the five real readers do.
    """
    by_key = collections.defaultdict(set)
    for f in sorted((root / "_bramber" / "units").glob("*.json")):
        env = json.loads(f.read_text(encoding="utf-8"))
        for u in (env.get("units") or []):
            if u["kind"] == "claim":
                by_key[u["payload"]["claim_key"]].add(env["extract_path"])
    return {k: len(v) for k, v in by_key.items()}


# --------------------------------------------------------------------------------------------
# the derived orphan: removed
# --------------------------------------------------------------------------------------------

def test_an_envelope_whose_extract_is_gone_is_removed(tmp_path: Path):
    """The plain case. Edit a source, re-ingest, re-point the scan: the old envelope must go.

    Reddens by deleting the `_reconcile_store` call in `ingest.materialize` — the store then
    holds two envelopes for one source and the phantom is indistinguishable from a real one.
    """
    _extract(tmp_path, "a_md__aaaaaaaa")
    _scan(tmp_path, "a_md__aaaaaaaa", "- **CLAIM-001** - the vendor ships in March.\n"
                                      "  - evidence: strong\n")
    ingest.materialize(tmp_path)
    assert _envelopes(tmp_path) == ["a_md__aaaaaaaa"]

    # the edit: new body -> new content_sha -> new slug. Old extract and scan retired together.
    (tmp_path / "_bramber" / "extracts" / "a_md__aaaaaaaa.md").unlink()
    (tmp_path / "_bramber" / "scans" / "a_md__aaaaaaaa.md").unlink()
    _extract(tmp_path, "a_md__cccccccc", body="edited body")
    _scan(tmp_path, "a_md__cccccccc", "- **CLAIM-001** - the vendor ships in April.\n"
                                      "  - evidence: strong\n")

    res = ingest.materialize(tmp_path)

    assert _envelopes(tmp_path) == ["a_md__cccccccc"], "the pre-edit envelope survived"
    assert res["orphans_removed"] == ["a_md__aaaaaaaa"]
    # one source, one claim — not two claims one of which the corpus no longer contains
    assert sum(_support(tmp_path).values()) == 1


def test_the_removal_is_reported_on_stderr(tmp_path: Path, capsys):
    """A corpus-wide deletion that nothing announces is its own defect."""
    _extract(tmp_path, "live__aaaaaaaa")
    _scan(tmp_path, "live__aaaaaaaa", "- **CLAIM-001** - a claim.\n  - evidence: strong\n")
    (tmp_path / "_bramber" / "units").mkdir(parents=True, exist_ok=True)
    (tmp_path / "_bramber" / "units" / "ghost__bbbbbbbb.json").write_text(
        json.dumps({"extract_path": "_bramber/extracts/ghost__bbbbbbbb.md", "units": []}),
        encoding="utf-8")

    ingest.materialize(tmp_path)

    err = capsys.readouterr().err
    assert "1 orphaned unit envelope(s) removed" in err


# --------------------------------------------------------------------------------------------
# the attribution defect this exists to stop
# --------------------------------------------------------------------------------------------

def test_an_orphan_plus_an_endorsement_does_not_fabricate_support(tmp_path: Path):
    """The unrecoverable direction, reachable through the orphan even under namespacing.

    A key's namespace comes from its minter's extract path, so an edited source's NEW units carry
    a new key and cannot merge with the orphan's. Support inflation needs a third party: source B
    endorsed A's original key, so that key is still asserted by B — and the orphaned A envelope
    joins it as a second contributor whose source is not on disk. The register then reports two
    sources for a claim one live source makes.

    Reddens by deleting the `_reconcile_store` call: the endorsed key comes back at support 2.
    """
    stmt = "the vendor cannot staff before November."
    _extract(tmp_path, "a_md__aaaaaaaa")
    _scan(tmp_path, "a_md__aaaaaaaa", f"- **CLAIM-001** - {stmt}\n  - evidence: strong\n")

    key_a = scan._stamp("CLAIM-001", scan.srcref_for("_bramber/extracts/a_md__aaaaaaaa.md"))
    witness = scan.statement_token(stmt)
    _extract(tmp_path, "b_md__bbbbbbbb")
    _scan(tmp_path, "b_md__bbbbbbbb",
          f"- **{key_a}={witness}** - {stmt}\n  - evidence: strong\n")

    ingest.materialize(tmp_path)
    assert _support(tmp_path)[key_a] == 2, "fixture is wrong: B's endorsement did not merge"

    # A is edited. Its scan is re-pointed at the new extract; B is untouched and still endorses
    # the pre-edit key, which no live source mints any more.
    (tmp_path / "_bramber" / "extracts" / "a_md__aaaaaaaa.md").unlink()
    (tmp_path / "_bramber" / "scans" / "a_md__aaaaaaaa.md").unlink()
    _extract(tmp_path, "a_md__cccccccc", body="edited body")
    _scan(tmp_path, "a_md__cccccccc", f"- **CLAIM-001** - {stmt}\n  - evidence: strong\n")

    ingest.materialize(tmp_path)

    support = _support(tmp_path)
    assert key_a not in support or support[key_a] == 1, (
        f"support fabricated: {key_a} credits a source that is not on disk ({support})")
    assert all(v == 1 for v in support.values()), f"no claim here has two live sources: {support}"
    assert _envelopes(tmp_path) == ["a_md__cccccccc", "b_md__bbbbbbbb"]


# --------------------------------------------------------------------------------------------
# the authored orphan: refused, never deleted
# --------------------------------------------------------------------------------------------

def test_a_scan_whose_source_is_gone_stops_the_run(tmp_path: Path):
    """The ordinary edit-after-scan sequence, which is the damaging one.

    Re-ingesting an edited source leaves its scan pointing at an extract that no longer exists.
    Continuing would drop that source's claims from every view with no notice, and the scan
    describes text the corpus no longer holds, so it cannot be silently kept either. The agent's
    read is never thrown away to resolve that — a human re-points it or retires it.

    Reddens by lowering the refusal to a warning, or by ordering it after the deletion.
    """
    _extract(tmp_path, "a_md__aaaaaaaa")
    _scan(tmp_path, "a_md__aaaaaaaa", "- **CLAIM-001** - a claim.\n  - evidence: strong\n")
    ingest.materialize(tmp_path)

    # re-ingest of an edited body: new extract, scan still names the old one
    (tmp_path / "_bramber" / "extracts" / "a_md__aaaaaaaa.md").unlink()
    _extract(tmp_path, "a_md__cccccccc", body="edited body")

    with pytest.raises(SystemExit) as e:
        ingest.materialize(tmp_path)
    assert "no longer on disk" in str(e.value)
    assert "_bramber/scans/a_md__aaaaaaaa.md" in str(e.value)


def test_the_refusal_deletes_nothing(tmp_path: Path):
    """The interlock. A stranded scan means the corpus is mid-edit, which is exactly when a
    destructive reconcile would do the most damage — so the refusal must precede the unlink,
    not follow it.

    Reddens by moving the orphan deletion above the stranded-scan check in `_reconcile_store`.
    """
    _extract(tmp_path, "a_md__aaaaaaaa")
    _scan(tmp_path, "a_md__aaaaaaaa", "- **CLAIM-001** - a claim.\n  - evidence: strong\n")
    ingest.materialize(tmp_path)
    before = _envelopes(tmp_path)
    assert before == ["a_md__aaaaaaaa"]

    (tmp_path / "_bramber" / "extracts" / "a_md__aaaaaaaa.md").unlink()

    with pytest.raises(SystemExit):
        ingest.materialize(tmp_path)
    assert _envelopes(tmp_path) == before, "the store was reconciled against a corpus mid-edit"


def test_a_half_copied_extracts_directory_is_refused_not_reconciled(tmp_path: Path):
    """The failure mode that made option 1 risky, and the reason the order is what it is.

    An interrupted copy leaves `extracts/` short while `scans/` and `units/` are intact. A
    reconcile that trusted `extracts/` as the authority would discard the store. The scans are
    orphaned in exactly that state, so the expensive artifact guards the cheap one and no
    heuristic has to judge whether a small `extracts/` was intended.
    """
    for slug in ("a_md__aaaaaaaa", "b_md__bbbbbbbb", "c_md__cccccccc"):
        _extract(tmp_path, slug)
        _scan(tmp_path, slug, "- **CLAIM-001** - a claim.\n  - evidence: strong\n")
    ingest.materialize(tmp_path)
    assert len(_envelopes(tmp_path)) == 3

    # the interrupted copy
    (tmp_path / "_bramber" / "extracts" / "b_md__bbbbbbbb.md").unlink()
    (tmp_path / "_bramber" / "extracts" / "c_md__cccccccc.md").unlink()

    with pytest.raises(SystemExit):
        ingest.materialize(tmp_path)
    assert len(_envelopes(tmp_path)) == 3, "a partial extracts/ discarded a live store"


# --------------------------------------------------------------------------------------------
# the ledger channel the orphan scan also reaches
# --------------------------------------------------------------------------------------------

def test_the_refusal_precedes_the_key_ledger(tmp_path: Path, monkeypatch):
    """`read_all` feeds every scan into `resolve_keys`, including one whose source is gone, so a
    stranded scan's keys would otherwise enter the minted set this run builds its store and its
    notices from. The reconcile is ordered ahead of that call, and this asserts the ORDER rather
    than the outcome — the other refusal tests pass whichever side of `resolve_keys` it sits on,
    because both orders end in the same raise.

    Reddens by moving the `_reconcile_store` call below `resolve_keys` in `materialize`.

    Scope, deliberately narrow: this does NOT mean a stranded key is unreachable corpus-wide.
    `scan.known_keys` reads the scans directly, so `bramber claims` still publishes one until the
    scan is repaired — a separate reader with the same blind spot, and its own issue.
    """
    _extract(tmp_path, "a_md__aaaaaaaa")
    _scan(tmp_path, "a_md__aaaaaaaa", "- **CLAIM-001** - a claim.\n  - evidence: strong\n")
    ingest.materialize(tmp_path)
    (tmp_path / "_bramber" / "extracts" / "a_md__aaaaaaaa.md").unlink()

    reached = []
    real = scan.resolve_keys
    monkeypatch.setattr(scan, "resolve_keys",
                        lambda *a, **k: (reached.append(1), real(*a, **k))[1])

    with pytest.raises(SystemExit):
        ingest.materialize(tmp_path)

    assert reached == [], "the stranded scan reached the key ledger before the run was refused"
    assert _envelopes(tmp_path) == ["a_md__aaaaaaaa"]
