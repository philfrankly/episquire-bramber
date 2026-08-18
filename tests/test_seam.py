"""The adapter↔engine seam, guarded structurally rather than by review.

The repo's central design claim is that the engine is domain-blind. Until 2026-07-21 that was
**evidence, not structure**: it had been verified once, by hand, by running
`git diff --stat bramber/engine bramber/compile.py` after the text lift. Nothing re-ran it, and
nothing prevented a regression.

Founder ruling 2026-07-21, "generality claim restated", split the claim
in two, because the old single gate conflated two things of very different strength:

- `bramber/engine/` is domain-blind **by construction** — it may never import an adapter and may
  never speak a domain's vocabulary. That is a hard rule, and these tests are what make it one.
- `bramber/compile.py` is the selection/projection layer above the engine. It is *not* domain-free
  today and is being generalized (`specs/07 §4`). It is deliberately **not** covered here.

Home for `specs/06`'s T1/T2 seam items as they land.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from bramber.engine import header

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "bramber" / "engine"


def _engine_py() -> list[Path]:
    return sorted(ENGINE.glob("*.py"))


# --- the import boundary -----------------------------------------------------

def test_engine_never_imports_an_adapter():
    """Invariant 1 of spec 00: the engine never imports an Adapter. Adapters run at ingest time
    and materialize to disk; `bramber sync` reconstructs the index from the generalized header with
    a stdlib parse. That is what keeps sync fast and the engine oblivious.

    This was true but unguarded — the sibling guards in test_trace.py and test_run.py cover the
    tracer and the run recorder, and nothing covered the adapters, which are the seam the whole
    design rests on."""
    offenders = []
    for py in _engine_py():
        src = py.read_text(encoding="utf-8")
        for needle in ("bramber.adapters", "from bramber import adapters", "import adapters",
                       "bramber.adapter", "TextAdapter", "CodeAdapter"):
            if needle in src:
                offenders.append(f"{py.name} references {needle!r}")
    assert not offenders, (
        "the engine reached for an adapter — the seam is in the wrong place:\n"
        + "\n".join(offenders))


# --- the vocabulary boundary -------------------------------------------------

# Terms that belong to a specific domain. The engine traffics only in Source / Extract / Unit /
# View / Digest / Resource / ResourceVersion, which are domain-blind by design.
DOMAIN_TOKENS = frozenset({
    # code domain
    "engram", "engram_id", "qualified_name", "sub_key", "learningpath", "symbol_kind",
    # text domain
    "claim_key", "evidence_strength", "digest_claim", "statement", "recency", "topics",
    # kind values are domain vocabulary too — `claim` is the one exception, grandfathered as the
    # word the engine's own docstrings use to explain the seam.
    "entity", "term", "contradiction",
    "entity_key", "entity_name", "term_key", "term_name", "gloss", "role", "stance", "status",
    "aliases", "relates_to", "contradiction_key", "sides", "resolution", "resolution_status",
    # `## Signals` is not materialized. Its tokens are reserved here so they cannot leak in
    # later — the same precedent the unbuilt git domain sets two lines down.
    "signal", "signal_key",
    # git domain (specs/08, unbuilt — listed so it cannot leak in later)
    "commit_sha", "file_touched", "commit_message",
})


def test_engine_holds_no_domain_vocabulary():
    """The import guard above stops the engine *depending* on a domain. This stops it *knowing*
    about one, which is the subtler failure: a function that quietly assumes `qualified_name`
    exists has smuggled a domain in without importing anything.

    Checked over identifiers only — comments and docstrings may name a domain to explain the
    boundary (`schema.sql` does exactly that), and explaining is not depending."""
    offenders = []
    for py in _engine_py():
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.arg):
                name = node.arg
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
            if name and name.lower() in DOMAIN_TOKENS:
                offenders.append(f"{py.name}:{getattr(node, 'lineno', '?')} names {name!r}")
    assert not offenders, (
        "domain vocabulary leaked into the engine — it must traffic only in Source/Extract/"
        "Unit/View/Digest/Resource/ResourceVersion:\n" + "\n".join(sorted(set(offenders))))


def test_every_payload_field_is_declared_domain_vocabulary():
    """The guard that keeps DOMAIN_TOKENS from silently falling behind.

    The list above is only as good as someone remembering to extend it, and the failure of
    forgetting is invisible: a new payload field leaks into the engine and every test still
    passes. So invert the burden — **add a payload field and this test goes red until you declare
    it** — exactly as `test_writer_must_supply_every_declared_header_field` does for the extract
    header.

    Derived by *calling* the producer rather than parsing it, so building the payload a different
    way cannot escape the check. That matters: an AST-shaped guard would go quiet the moment
    someone constructed the dict in a loop.
    """
    from bramber.scan import (Claim, Contradiction, Entity, Scan, Term, _SECTIONS,
                              units_for_source)

    s = Scan(path="_bramber/scans/src.md", source="_bramber/extracts/src.md", discarded=False,
             claims=[Claim(key="CLAIM-001", statement="s", evidence_strength="strong",
                           recency="2026-05-01", topics=["t"])],
             entities=[Entity(entity_name="Acme Corp", gloss="g", role="r", stance="s",
                              status="new", aliases=["a"], topics=["t"])],
             terms=[Term(term_name="cutover", gloss="g", status="new", relates_to=["x"],
                         topics=["t"])],
             contradictions=[Contradiction(key="CONTRA-001", statement="s",
                                           sides=[{"ref": "CLAIM-001"}], resolution="r",
                                           resolution_status="proposed", topics=["t"])])

    # The fixture must exercise EVERY parsed kind, or this guard passes vacuously for the ones it
    # skips — which is exactly what it did when it was first written against claims alone.
    produced_kinds = {u.kind for u in units_for_source([s])}
    declared_kinds = {spec["kind"] for spec in _SECTIONS.values()}
    assert produced_kinds == declared_kinds, (
        f"fixture does not cover every parsed kind: "
        f"missing {sorted(declared_kinds - produced_kinds)}")

    produced = set()
    for unit in units_for_source([s]):
        produced |= set(unit.payload)
        assert unit.kind.lower() in DOMAIN_TOKENS | {"claim"}, (
            f"unit kind {unit.kind!r} is domain vocabulary and must be declared in DOMAIN_TOKENS")

    undeclared = {f for f in produced if f.lower() not in DOMAIN_TOKENS}
    assert not undeclared, (
        f"payload field(s) {sorted(undeclared)} are produced by the text adapter but not declared "
        f"in DOMAIN_TOKENS. Declare them, so the engine guard above actually forbids them.")


# --- T1.1 — the header is ONE declaration both sides derive from -------------
#
# specs/06 T1.1. The NULL-url bug was not a bad line of code; it was two hand-maintained lists
# of header keys that agreed until someone edited one. Testing a sample passing through the
# channel cannot catch that, so these test the channel itself.

INBOX_SOURCE = (
    "---\n"
    "source_url: https://example.com/a-source\n"
    "source_type: article\n"
    'title: "A Source"\n'
    "author: J. Analyst\n"
    "date_published: 2026-04-18\n"
    "---\n"
    "# A Source\n\nBody text.\n"
)


def _seed_inbox(root: Path, name: str = "a-source.md", text: str = INBOX_SOURCE) -> Path:
    inbox = root / "_bramber" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    p = inbox / name
    p.write_text(text, encoding="utf-8")
    return p


def _ingest(root: Path):
    from bramber.ingest import ingest, make_adapter
    return ingest(make_adapter("text", repo=str(root)), root)


def _load_db(tmp_path: Path, tag: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"bramber_db_seam_{tag}", ENGINE / "db.py")
    db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db)
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    return db


def test_engine_reader_hardcodes_no_header_keys():
    """`db._sync_sources` used to spell out every header key at its `upsert_source` call. It now
    derives them from `header.SOURCE_FIELDS`, and this keeps it that way: a future edit reaching
    for `fields.get("some_new_key")` re-creates the two-lists problem, and re-creates it
    *invisibly*, because a hardcoded read of a key the writer never writes is simply None.

    Scoped to reads of the parsed frontmatter — `.get(<literal>)` — and not to every string in
    the function, because two namespaces overlap here: header **keys** (`source_url`) and
    `upsert_source` **parameters** (`url`), which are the same word for 7 of 9 fields. The
    surviving `kw["identity_kind"]` fallbacks are param-space: rename the header key tomorrow
    and they stay correct. Only key-space reads can drift, so only key-space is guarded.
    """
    src = (ENGINE / "db.py").read_text(encoding="utf-8")
    tree = ast.parse(src, filename="db.py")
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_sync_sources")

    assert "header.read(" in ast.get_source_segment(src, fn), \
        "_sync_sources must consume the frontmatter through the shared declaration"

    leaked = sorted({
        node.args[0].value
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get" and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in header.SOURCE_FIELDS
    })
    assert not leaked, (
        "_sync_sources reads extract-header keys directly instead of deriving them from "
        f"bramber/engine/header.py: {leaked}")


def test_writer_must_supply_every_declared_header_field(tmp_path: Path, monkeypatch):
    """The inversion that makes the declaration binding: add a field to the declaration and
    ingest FAILS until it is taught to fill it, rather than writing an extract without it and
    letting the engine index a NULL forever.

    This is the mutation the old two-list design had no answer to. It is asserted, not assumed."""
    _seed_inbox(tmp_path)
    monkeypatch.setattr(
        header, "SOURCE_FIELDS", {**header.SOURCE_FIELDS, "reliability_tier": "reliability_tier"})

    with pytest.raises(ValueError) as exc:
        _ingest(tmp_path)
    assert "reliability_tier" in str(exc.value)
    assert not list((tmp_path / "_bramber" / "extracts").glob("*.md")), \
        "a header that does not satisfy the declaration must write no extract at all"


def test_required_header_field_never_writes_an_empty_value():
    """`source_url`/`author`/`date_published` are legitimately absent for some domains and are
    omitted. `source_type`/`title`/identity are not — and silently writing them blank is how a
    NULL reaches a column no later pass can repair, since disk is the source of truth."""
    full = {k: "x" for k in header.SOURCE_FIELDS}
    with pytest.raises(ValueError) as exc:
        header.render({**full, "source_type": "  "})
    assert "source_type" in str(exc.value)

    # …while an absent optional field is simply not rendered.
    lines = header.render({**full, "author": None})
    assert not any(ln.startswith("author:") for ln in lines)
    assert any(ln.startswith("source_type:") for ln in lines)


@pytest.mark.parametrize("field", sorted(header.SOURCE_FIELDS))
def test_every_declared_header_field_reaches_the_index(tmp_path: Path, field: str):
    """T1.2 — round-trip completeness, parameterised over the declaration itself, so a field
    added later is covered without anyone remembering to add an assertion. This is the
    assertion the NULL-url bug needed and did not have."""
    db = _load_db(tmp_path, "roundtrip")
    _seed_inbox(tmp_path)
    _ingest(tmp_path)
    db.sync_from_disk()

    column = header.SOURCE_FIELDS[field]
    conn = sqlite3.connect(str(tmp_path / "bramber.db"))
    try:
        value = conn.execute(f"SELECT {column} FROM sources").fetchone()[0]
    finally:
        conn.close()
    assert value not in (None, ""), (
        f"header field {field!r} did not reach sources.{column} — writer and reader disagree "
        f"about it, which is the NULL-url bug's exact shape")


# --- T2 — adapter properties (specs/06 §4) -----------------------------------

def test_identity_is_stable_for_identical_bytes(tmp_path: Path):
    """T2.1. Trivially true for `content_sha`; the point is that it stays true when identity
    becomes pluggable, which is the direction specs/00 §5 commits to."""
    from bramber.adapters.text import TextAdapter

    _seed_inbox(tmp_path, "one.md")
    _seed_inbox(tmp_path, "two.md")            # same bytes, different filename
    adapter = TextAdapter()
    srcs = sorted(adapter.discover_sources(tmp_path), key=lambda s: s.ref)
    keys = [adapter.identity(s).key for s in srcs]
    assert len(keys) == 2 and keys[0] == keys[1], \
        "content_sha identity must depend on bytes, not on the filename carrying them"


def test_reingesting_the_same_source_mints_no_duplicate(tmp_path: Path):
    """T2.2. Guards a hazard the sibling-instance migration already hit: identity is the body sha,
    so re-fetching a source re-runs ASR and any wobble in the transcript mints a *second*
    logical source. Identical bytes must not."""
    db = _load_db(tmp_path, "dup")
    _seed_inbox(tmp_path)
    _ingest(tmp_path)
    db.sync_from_disk()
    _ingest(tmp_path)                           # same bytes, second run
    db.sync_from_disk()

    conn = sqlite3.connect(str(tmp_path / "bramber.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    finally:
        conn.close()
    assert len(list((tmp_path / "_bramber" / "extracts").glob("*.md"))) == 1, \
        "the identity-anchored slug must land the same source on the same file"


def test_extraction_is_deterministic(tmp_path: Path):
    """T2.3. Same input -> same units, same order, same count. Vacuous for text today
    (`extract_units` returns none) and deliberately kept: it is the assertion that has to hold
    when specs/07 gives text real units, and writing it now means that cannot ship untested."""
    from bramber.adapters.text import TextAdapter

    _seed_inbox(tmp_path, "one.md")
    adapter = TextAdapter()
    src = next(iter(adapter.discover_sources(tmp_path)))
    assert adapter.extract_units(adapter.normalize(src)) \
        == adapter.extract_units(adapter.normalize(src))


def test_an_adapter_run_writes_nothing_engine_owned(tmp_path: Path):
    """T2.4 — invariant 1 of spec 00, the half nothing covered. `test_engine_never_imports_an_
    adapter` stops the engine reaching down; this stops the adapter reaching up. An ingest run
    materializes extracts and units and NOTHING else: no index, no resource version, no MCP
    surface. If this fails the seam is in the wrong place even with every other test green."""
    _seed_inbox(tmp_path)
    manifest = _ingest(tmp_path)
    assert manifest, "the run must have done something for this to mean anything"

    assert not (tmp_path / "bramber.db").exists(), "an adapter run must not create the index"
    assert not (tmp_path / "views").exists(), "an adapter run must not write a view or resource"
    touched = {p.relative_to(tmp_path).parts[:2] for p in tmp_path.rglob("*") if p.is_file()}
    assert touched <= {("_bramber", "inbox"), ("_bramber", "extracts"), ("_bramber", "units")}, \
        f"an ingest run touched something outside _bramber/{{inbox,extracts,units}}: {sorted(touched)}"
