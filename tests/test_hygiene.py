"""The hygiene queues (`bramber/hygiene.py`) — specs/10 §5.2 + specs/11 M5.

The one property everything here defends: **a sweep files proposals and applies nothing.**
Every planted defect — a near-duplicate mint, a synonym tag split, an alias pair, a broken
reuse — must land in `_bramber/evaluations/` as a `status: pending` file for the human gate,
and the store must come out of the sweep byte-identical. A pair once filed is never re-filed,
whatever its status: a rejected proposal is a record that the pair was examined.

Run:  cd bramber && python -m pytest tests/test_hygiene.py
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from bramber import cli, hygiene, index as index_mod, ingest, scan
from bramber.engine import db

DIMS = 32


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


def _corpus(tmp_path: Path) -> None:
    """Every planted defect the queues exist to catch, in one corpus:
    A and C mint near-identical claims under distinct keys (the missed reuse); C's topic tag
    is a singleton synonym of A's; A and C spell one vendor two ways with a shared topic;
    B endorses A's claim but forgets the witness (the safe-side degrade)."""
    _source(tmp_path, "minutes_md__aaaaaaaa", """
## Claims

- **CLAIM-001** - The cutover date is fixed for March.
  - evidence: strong
  - topics: deadline-integrity

## Entities

- **Acme Corp** - supplies the integration middleware.
  - role: vendor
  - topics: vendor-risk
""")
    _source(tmp_path, "review_md__bbbbbbbb", """
## Claims

- **CLAIM-aaaaaaaa-001** - The go-live is not moving.
  - evidence: moderate
  - topics: deadline-integrity
- **CLAIM-777=abcdef** - Something novel asserted here entirely.
  - evidence: weak
""")
    _source(tmp_path, "notes_md__cccccccc", """
## Claims

- **CLAIM-001** - The cutover date is now fixed for March.
  - evidence: moderate
  - topics: deadline-integrity-risk

## Entities

- **ACME Corporation** - the middleware vendor on the critical path.
  - role: vendor
  - topics: vendor-risk
""")
    ingest.materialize(tmp_path)
    index_mod.build(tmp_path, embedder=FakeEmbedder(), model="fake-1")


def _proposals(tmp_path: Path) -> dict:
    """subject -> (path, frontmatter) for every filed proposal."""
    out = {}
    ev = tmp_path / "_bramber" / "evaluations"
    for f in sorted(ev.glob("*.md")) if ev.exists() else []:
        fields, _, _ = db.split_frontmatter(f.read_text(encoding="utf-8"))
        out[fields.get("subject")] = (f, fields)
    return out


def test_a_planted_near_duplicate_files_a_merge_proposal(tmp_path: Path, capsys):
    _corpus(tmp_path)
    res = hygiene.sweep(tmp_path)
    assert res["queues"]["merge"] >= 1
    subject = "claim-pair CLAIM-aaaaaaaa-001 CLAIM-cccccccc-001"
    path, fields = _proposals(tmp_path)[subject]
    assert fields["status"] == "pending" and fields["scope"] == "store"
    body = path.read_text(encoding="utf-8")
    assert "one token edit" in body, "the repair doctrine: an approved merge is one token"
    assert "CLAIM-aaaaaaaa-001=" in body and "CLAIM-cccccccc-001=" in body, \
        "the proposal hands the operator the exact tokens to copy, one per survivor choice"


def test_the_merge_recommendation_hands_both_tokens_and_claims_no_order(tmp_path: Path):
    """Screen finding F1 (HIGH): the pair is string-sorted and namespaces are content
    hashes, so 'earlier'/'later' is not derivable — a mislabeled survivor token, applied as
    instructed, replaced a mint's key with its OWN token and the approved merge silently
    recorded nothing. The proposal now hands BOTH repair tokens with each mint's own scan
    named, and makes no ordering claim at all: whichever mint the operator keeps, the edit
    in front of them is correct."""
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    path, _ = _proposals(tmp_path)["claim-pair CLAIM-aaaaaaaa-001 CLAIM-cccccccc-001"]
    body = path.read_text(encoding="utf-8")
    tok_a = scan.statement_token("The cutover date is fixed for March.")
    tok_c = scan.statement_token("The cutover date is now fixed for March.")
    assert f"CLAIM-aaaaaaaa-001={tok_a}" in body, "keeping A must be a ready-made edit"
    assert f"CLAIM-cccccccc-001={tok_c}" in body, "keeping C must be a ready-made edit"
    assert "_bramber/scans/minutes_md__aaaaaaaa.md" in body
    assert "_bramber/scans/notes_md__cccccccc.md" in body
    low = body.lower()
    assert "earlier" not in low and "later" not in low, \
        "an ordering the code cannot derive must not be claimed to the operator"


def test_a_synonym_singleton_tag_files_a_topic_proposal(tmp_path: Path):
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    assert "topic-pair deadline-integrity deadline-integrity-risk" in _proposals(tmp_path)


def test_an_alias_pair_files_a_suggestion(tmp_path: Path):
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    assert "entity-pair acme corp acme corporation" in _proposals(tmp_path)


def test_an_unwitnessed_reuse_files_a_ledger_repair(tmp_path: Path):
    """B named A's mint without quoting it; the resolver kept B's claim safe-side. The queue
    turns that stderr notice into a durable, gated repair proposal — with the SITUATION
    (key + sources) as the subject."""
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    subject = ("ledger unwitnessed CLAIM-aaaaaaaa-001 "
               "[_bramber/extracts/review_md__bbbbbbbb.md]")
    path, fields = _proposals(tmp_path)[subject]
    assert "reuse_as" in path.read_text(encoding="utf-8")
    assert fields["proposed_by"] == "bramber hygiene"


def test_a_new_source_repeating_an_examined_mistake_files_again(tmp_path: Path):
    """Screen finding F4: a key-only subject examined ONE situation and then suppressed
    every later source's identical mistake forever. The subject scopes to key + sources, so
    a new actor is a new situation and files."""
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    _source(tmp_path, "late_md__eeeeeeee", """
## Claims

- **CLAIM-aaaaaaaa-001** - The date still holds, says a latecomer.
  - evidence: weak
""")
    ingest.materialize(tmp_path)
    res = hygiene.sweep(tmp_path)
    joined = " ".join(res["proposals_filed"])
    assert res["queues"]["ledger"] >= 1 and "store-ledger" in joined, \
        "the latecomer's identical mistake is a new situation and must file"
    subjects = _proposals(tmp_path)
    assert any("late_md__eeeeeeee" in s and "unwitnessed CLAIM-aaaaaaaa-001" in s
               for s in subjects), subjects.keys()


def test_a_stray_witness_files_a_ledger_proposal(tmp_path: Path):
    """Screen finding F2: M5 names stray witnesses as a queue input; the sweep now files
    them instead of only promising to."""
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    path, _ = _proposals(tmp_path)["ledger stray-witness CLAIM-777"]
    body = path.read_text(encoding="utf-8")
    assert "endorses nothing" in body and "reuse_as" in body


def test_a_stale_index_is_named_in_the_notes(tmp_path: Path):
    """Screen finding F6: a merge queue that silently ran over yesterday's vectors reports a
    summary indistinguishable from a clean sweep. Staleness is named, with the remedy."""
    _corpus(tmp_path)
    env = tmp_path / "_bramber" / "units" / "minutes_md__aaaaaaaa.json"
    env.write_text(env.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    res = hygiene.sweep(tmp_path)
    assert any("STALE index" in n and "minutes_md__aaaaaaaa" in n for n in res["notes"])


def test_nothing_is_ever_auto_applied(tmp_path: Path):
    """The whole point, stated as bytes: a sweep may write proposal files and NOTHING else —
    no scan, no unit envelope, no view, no index entry changes."""
    _corpus(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    hygiene.sweep(tmp_path)
    ev = tmp_path / "_bramber" / "evaluations"
    new = {p for p in tmp_path.rglob("*") if p.is_file()} - set(before)
    assert new and all(ev in p.parents for p in new), \
        f"a sweep wrote outside _bramber/evaluations/: {sorted(new)}"
    assert all(p.read_bytes() == body for p, body in before.items()), \
        "a sweep modified a file it does not own — hygiene proposes, never applies"


def test_a_second_sweep_refiles_nothing(tmp_path: Path):
    _corpus(tmp_path)
    first = hygiene.sweep(tmp_path)
    assert first["proposals_filed"]
    second = hygiene.sweep(tmp_path)
    assert second["proposals_filed"] == []
    assert second["skipped_existing"] == len(first["proposals_filed"])


def test_a_rejected_proposal_is_a_record_of_examination(tmp_path: Path):
    """Rejection must not reopen the queue: re-raising an examined pair every sweep trains
    the operator to stop reading proposals, which is how a queue dies."""
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    subject = "claim-pair CLAIM-aaaaaaaa-001 CLAIM-cccccccc-001"
    path, _ = _proposals(tmp_path)[subject]
    path.write_text(path.read_text(encoding="utf-8")
                    .replace("status: pending", "status: rejected"), encoding="utf-8")
    res = hygiene.sweep(tmp_path)
    assert not any(subject in (p or "") for p in res["proposals_filed"])
    files_for_subject = [f for f, fields in _proposals(tmp_path).items() if f == subject]
    assert len(files_for_subject) == 1


def test_sweep_without_an_index_still_runs_the_ledger_queues(tmp_path: Path):
    """The merge queue rides the index; the ledger, topic and alias queues ride the scans
    and the store. Losing the cache loses nominations, never the telemetry."""
    _corpus(tmp_path)
    shutil.rmtree(index_mod.index_dir(tmp_path))
    res = hygiene.sweep(tmp_path)
    assert res["queues"]["merge"] == 0
    assert any("merge queue skipped" in n for n in res["notes"])
    assert res["queues"]["ledger"] >= 1 and res["queues"]["topic"] >= 1


def test_the_cli_files_and_reports_and_names_the_gate(tmp_path: Path, capsys):
    _corpus(tmp_path)
    cli.main(["hygiene", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert "filed" in out and "_bramber/evaluations/" in out
    assert "Nothing was applied" in out and "/bramber:evaluate" in out


def test_each_survivor_choice_comes_with_its_exact_token(tmp_path: Path):
    """Whichever mint the operator keeps, the token in front of them must be the KEPT
    claim's `reuse_as` — a wrong token here is how an approved merge records nothing."""
    _corpus(tmp_path)
    hygiene.sweep(tmp_path)
    path, _ = _proposals(tmp_path)["claim-pair CLAIM-aaaaaaaa-001 CLAIM-cccccccc-001"]
    body = path.read_text(encoding="utf-8")
    tok_a = scan.statement_token("The cutover date is fixed for March.")
    assert f"keep `CLAIM-aaaaaaaa-001`" in body and f"CLAIM-aaaaaaaa-001={tok_a}" in body


def test_no_ambiguous_bare_proposal_is_filed(tmp_path: Path):
    """The retired bucket's twin channel, and the worse of the two: a proposal demands a ruling
    and persists, so a corpus where every scan numbers from 1 filed one file per forced ordinal
    collision — 30 of them on the first real corpus. That trains the operator to stop reading the
    queue, which is exactly what the never-re-file rule at the top of this module exists to
    prevent, arriving through a different door.

    The residual hazard is not lost with it: an author who MEANT corroboration and wrote bare is a
    semantic question, and the near-duplicate merge queue above is the instrument for it.
    Retired 2026-08-12 → the 2026-08-12 ruling "the bare key notice is retired".

    Reddens by restoring the `keys.ambiguous` loop in `hygiene.sweep`.
    """
    for slug, statement in (("alpha_md__aaaaaaaa", "The date is fixed."),
                            ("beta_md__bbbbbbbb", "The vendor cannot staff before November.")):
        _source(tmp_path, slug, f"""
## Claims

- **CLAIM-001** - {statement}
  - evidence: strong
  - topics: scheduling
""")
    ingest.materialize(tmp_path)
    res = hygiene.sweep(tmp_path)

    # both sources minted a bare CLAIM-001, so the retired bucket would fire here; every OTHER
    # ledger bucket is empty (two clean mints, no reuses), so a non-zero count can only be it.
    assert res["queues"]["ledger"] == 0, f"ledger queue filed {res['queues']['ledger']}"
    bodies = [Path(f).read_text(encoding="utf-8") for f in res["proposals_filed"]]
    assert not any("ambiguous-bare" in b for b in bodies),         "the retired bucket is filing proposals again"
