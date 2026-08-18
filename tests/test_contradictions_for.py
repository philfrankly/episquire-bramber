"""`meta.contradictions_for` — tension-aware serving (specs/10 §3, ruled by specs/11 G6).

The product rule under test: any surface that returns a claim can also return the tensions
citing it. The primitive is a join over the store — `contradiction_register`'s merge reused
unchanged — plus a serve-time verification pass that inherits P5 (loudness): a side is never
dropped and never re-pointed; it is served with flags a reader can act on.

The two flags are asserted separately and asserted disjoint, because they report different
facts: `unresolved` (the key names nothing minted) has no token to verify a witness against,
so it must not also read as a mismatch — that would state the adjacent thing.

Run:  cd bramber && python -m pytest tests/test_contradictions_for.py
"""

from __future__ import annotations

import json
from pathlib import Path

from bramber import cli, ingest, meta, scan

A_CLAIM = "The cutover date is fixed."
B_CLAIM = "The cutover date is under review."
CONTRA_STATEMENT = "The minutes record the date as fixed; the review records it as under review."


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


def _corpus(tmp_path: Path, *, b_side: str) -> None:
    """Two sources, one tension. A mints the CONTRA key and cites its own claim; B endorses
    A's key (witnessed reuse of the minter's statement token) and records the side it can
    see — which is the whole reason side-unioning exists."""
    tok_c = scan.statement_token(CONTRA_STATEMENT)
    _source(tmp_path, "minutes_md__aaaaaaaa", f"""
## Claims

- **CLAIM-001** - {A_CLAIM}
  - evidence: strong
  - topics: schedule

## Contradictions

- **CONTRA-001** - {CONTRA_STATEMENT}
  - side: CLAIM-aaaaaaaa-001 | _bramber/extracts/minutes_md__aaaaaaaa.md | recorded as fixed
  - topics: schedule
""")
    _source(tmp_path, "review_md__bbbbbbbb", f"""
## Claims

- **CLAIM-001** - {B_CLAIM}
  - evidence: moderate
  - topics: schedule

## Contradictions

- **CONTRA-aaaaaaaa-001={tok_c}** - The review keeps the date open; the minutes call it fixed.
  - side: {b_side}
""")
    ingest.materialize(tmp_path)


B_SIDE_PLAIN = "CLAIM-bbbbbbbb-001 | _bramber/extracts/review_md__bbbbbbbb.md | under review"


def test_a_two_source_tension_returns_both_sides(tmp_path: Path):
    """Reading `sides` off one representative would report a two-source tension with one side;
    the primitive must serve the union, whichever side's claim was asked about."""
    _corpus(tmp_path, b_side=B_SIDE_PLAIN)
    out = meta.contradictions_for(tmp_path, "CLAIM-aaaaaaaa-001")
    assert out["count"] == 1
    (entry,) = out["contradictions"]
    assert {s["ref"] for s in entry["sides"]} == {"CLAIM-aaaaaaaa-001", "CLAIM-bbbbbbbb-001"}
    assert entry["support"] == 2

    # Symmetric: the tension is one record, reachable from either side's claim.
    other = meta.contradictions_for(tmp_path, "CLAIM-bbbbbbbb-001")
    assert other["count"] == 1
    assert other["contradictions"][0]["contradiction_key"] == entry["contradiction_key"]


def test_a_key_nobody_cites_returns_empty_not_error(tmp_path: Path):
    _corpus(tmp_path, b_side=B_SIDE_PLAIN)
    out = meta.contradictions_for(tmp_path, "CLAIM-cccccccc-9")
    # Exact shape on purpose — the surface is a contract, and the S0-1 channel grew it. Kept
    # exact rather than relaxed to a subset: a later field appearing unnoticed is how a
    # consumer ends up reading half an answer.
    assert out == {"claim_key": "CLAIM-cccccccc-9", "count": 0, "contradictions": [],
                   "unattributable_count": 0, "unattributable": []}


def test_a_side_pasted_as_reuse_as_serves_verified_and_unflagged(tmp_path: Path):
    """An agent pasting the feed's `reuse_as` token into a `side:` is doing the right thing;
    the witness must verify against the minter's statement token and raise no flag."""
    tok_b = scan.statement_token(B_CLAIM)
    _corpus(tmp_path, b_side=f"CLAIM-bbbbbbbb-001={tok_b} | "
                             f"_bramber/extracts/review_md__bbbbbbbb.md | under review")
    out = meta.contradictions_for(tmp_path, "CLAIM-aaaaaaaa-001")
    (entry,) = out["contradictions"]
    side = next(s for s in entry["sides"] if s["ref"] == "CLAIM-bbbbbbbb-001")
    assert side["witness"] == tok_b
    assert side["unresolved"] is False
    assert side["side_witness_mismatch"] is False


def test_a_mismatched_witness_is_served_flagged_never_repointed(tmp_path: Path):
    """The key resolves but the witness quotes a different statement — copied from another feed
    row. The side is served exactly as recorded, with the mismatch named; re-pointing it at the
    key the witness matches would be inference, which serving never does."""
    tok_b = scan.statement_token(B_CLAIM)
    wrong = "000000" if tok_b != "000000" else "111111"
    _corpus(tmp_path, b_side=f"CLAIM-bbbbbbbb-001={wrong} | "
                             f"_bramber/extracts/review_md__bbbbbbbb.md | under review")
    out = meta.contradictions_for(tmp_path, "CLAIM-aaaaaaaa-001")
    (entry,) = out["contradictions"]
    side = next(s for s in entry["sides"] if s["ref"] == "CLAIM-bbbbbbbb-001")
    assert side["side_witness_mismatch"] is True
    assert side["unresolved"] is False, "a resolvable key with a bad witness is not 'unresolved'"
    assert side["witness"] == wrong, "the recorded witness is served, not corrected"


def test_an_unresolvable_side_is_served_flagged_not_dropped(tmp_path: Path):
    """A side naming a key nothing minted still appears — visibly, which is what makes it
    fixable. And it is NOT also a witness mismatch: there is no minted token to verify
    against, and a flag that states the adjacent thing trains readers to ignore flags."""
    _corpus(tmp_path, b_side="CLAIM-deadbeef-9=aaaaaa | "
                             "_bramber/extracts/review_md__bbbbbbbb.md | under review")
    out = meta.contradictions_for(tmp_path, "CLAIM-aaaaaaaa-001")
    (entry,) = out["contradictions"]
    side = next(s for s in entry["sides"] if s["ref"] == "CLAIM-deadbeef-9")
    assert side["unresolved"] is True
    assert side["side_witness_mismatch"] is False
    assert side["extract_path"] == "_bramber/extracts/review_md__bbbbbbbb.md", \
        "the anchor that makes the side checkable survives serving"


def test_the_cli_serves_the_primitive_as_json(tmp_path: Path, capsys):
    _corpus(tmp_path, b_side=B_SIDE_PLAIN)
    cli.main(["contradictions", "--for", "CLAIM-aaaaaaaa-001", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 1
    assert out["claim_key"] == "CLAIM-aaaaaaaa-001"
    assert len(out["contradictions"][0]["sides"]) == 2


# --- the filter obeys the loudness rule too (screen finding S0-1) ------------
# The flags applied to sides INSIDE a hit; the filter that decides what is a hit dropped a
# tension none of whose sides resolve. A claim contested on the record was served as
# uncontested — by the one primitive whose stated purpose is preventing exactly that.


def _bare_sided_corpus(tmp_path: Path) -> None:
    """The shape the shipped FORMAT-SPEC template taught until 2026-08-10: side refs written
    bare, so neither side resolves against the store."""
    _source(tmp_path, "minutes_md__aaaaaaaa", f"""
## Claims

- **CLAIM-001** - {A_CLAIM}
  - evidence: strong

## Contradictions

- **CONTRA-001** - {CONTRA_STATEMENT}
  - side: CLAIM-007 | _bramber/extracts/minutes_md__aaaaaaaa.md | recorded as fixed
  - side: CLAIM-004 | _bramber/extracts/review_md__bbbbbbbb.md | under review
""")
    _source(tmp_path, "review_md__bbbbbbbb", f"""
## Claims

- **CLAIM-001** - {B_CLAIM}
  - evidence: moderate
""")
    ingest.materialize(tmp_path)


def test_a_tension_whose_sides_all_fail_to_resolve_is_returned_not_dropped(tmp_path: Path):
    _bare_sided_corpus(tmp_path)
    out = meta.contradictions_for(tmp_path, "CLAIM-aaaaaaaa-001")

    assert out["count"] == 0, "no side cites this key, so it is correctly not a hit"
    assert out["unattributable_count"] == 1, \
        "but the record holds a tension nothing can rule out — silence here IS the defect"
    (entry,) = out["unattributable"]
    assert entry["contradiction_key"].startswith("CONTRA-")
    assert all(s["unresolved"] for s in entry["sides"]), "every side flagged, none dropped"
    assert [s["ref"] for s in entry["sides"]] == ["CLAIM-007", "CLAIM-004"], \
        "refs served verbatim — re-pointing them onto the query would infer"
    assert "why" in entry


def test_an_unattributable_tension_is_never_counted_as_a_hit(tmp_path: Path):
    """The two channels must stay separable, or the fix trades a silent drop for a false
    positive — a consumer reading `count` would report a tension that may not be about it."""
    _bare_sided_corpus(tmp_path)
    out = meta.contradictions_for(tmp_path, "CLAIM-aaaaaaaa-001")
    assert out["contradictions"] == []
    assert out["unattributable"] and out["unattributable"][0] not in out["contradictions"]


def test_a_tension_with_no_resolvable_side_at_all_is_still_returned(tmp_path: Path):
    """S0-7: the first fix keyed on `any(unresolved)`, which is False over an EMPTY side list —
    so a tension recorded with no `side:` lines fell through both channels and was reported
    nowhere. The two shapes are separate parametrized cases because they arrive by different
    routes: one omits the lines, the other writes a side whose ref is empty and is dropped at
    parse time."""
    for slug, sides in (("nosides_md__aaaaaaaa", ""),
                        ("emptyref_md__bbbbbbbb",
                         "  - side:  | _bramber/extracts/other.md | under review\n")):
        root = tmp_path / slug
        _source(root, slug, f"""
## Claims

- **CLAIM-001** - {A_CLAIM}
  - evidence: strong

## Contradictions

- **CONTRA-001** - {CONTRA_STATEMENT}
{sides}""")
        ingest.materialize(root)
        ns = slug.split("__")[1]
        out = meta.contradictions_for(root, f"CLAIM-{ns}-001")

        assert len(meta.contradiction_register(root)["contradictions"]) == 1, \
            f"{slug}: the register must still hold the tension, or this tests nothing"
        assert out["count"] == 0
        assert out["unattributable_count"] == 1, \
            f"{slug}: a tension in the record reported by neither channel is the S0-1 defect"
        assert "no side at all" in out["unattributable"][0]["why"], \
            "the two cases need different words — 'cites nothing' is not 'cites nothing resolvable'"


def test_a_clean_corpus_pays_nothing_for_the_new_channel(tmp_path: Path):
    """Every side resolves, so there is nothing the record cannot attribute. An always-populated
    channel would train a reader to ignore it, which is how the notice this replaces failed."""
    _corpus(tmp_path, b_side=B_SIDE_PLAIN)
    out = meta.contradictions_for(tmp_path, "CLAIM-aaaaaaaa-001")
    assert out["count"] == 1
    assert out["unattributable"] == [] and out["unattributable_count"] == 0


def test_the_shipped_template_writes_side_refs_that_resolve(tmp_path: Path):
    """The template is the authoring instruction, so a template teaching an unresolvable form
    is the reaching path for the defect above — not a documentation nit. Derived from the
    shipped file, so editing it back fails here."""
    spec = (Path(__file__).resolve().parents[1] / "bramber-plugin" / "docs" /
            "FORMAT-SPEC.md").read_text(encoding="utf-8")
    sides = [ln.strip() for ln in spec.splitlines() if ln.strip().startswith("- side:")]
    assert sides, "the worked template must keep a Contradictions example"
    for ln in sides:
        ref = ln.split("side:", 1)[1].split("|")[0].strip()
        assert scan._namespace_of(ref) is not None, \
            f"template teaches a side ref with no namespace: {ref!r}"
        ns = ref.split("-")[-2]
        assert ns in ln.split("|")[1], \
            f"the namespace must match the extract the side names, or the example is wrong: {ln}"
