"""`--trace` observability (bramber/trace.py).

The JSON is the record and the HTML is a rendering of it, so these tests assert on the
JSON — the structure is testable, the page's legibility is not. They run on hand-authored
claim units on disk (the shape `bramber.scan.units_for_source` materializes), so no
adapter and no optional dependency is involved.

Two things are worth guarding beyond "it records something":
  - **The seam.** Tracing must not be reachable from `bramber/engine/` — the structural half
    of the generality claim (CLAUDE.md) is that adding capability never edits the engine.
  - **Disabled is inert.** `NULL_TRACE` is a module singleton whose steps are handed to
    call sites that assign into `step.inputs`/`step.outputs`; if those writes landed on a
    shared object it would accumulate every run's data for the life of the process.

Run:  cd bramber && python -m pytest tests/test_trace.py
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bramber import trace as tracing
from bramber.compile import _reject_reason, compile_view, parse_selector, select_units

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "bramber" / "engine"


def _load_db():
    spec = importlib.util.spec_from_file_location("bramber_db_trace", ENGINE / "db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _steps(tr) -> dict:
    return {s["name"]: s for s in tr.as_dict()["steps"]}


# --- the seam ---------------------------------------------------------------

def test_engine_never_imports_trace():
    """Observability is cross-cutting — exactly the kind of concern that leaks into an
    engine. The engine stays domain-blind and stdlib-only; the recorder lives beside
    ingest/compile and the engine must not know it exists."""
    for py in ENGINE.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "bramber.trace" not in src and "import trace" not in src, \
            f"{py.name} reaches for the tracer; tracing belongs outside bramber/engine/"


# --- disabled is inert ------------------------------------------------------

def test_null_trace_records_nothing_and_writes_nothing(tmp_path: Path):
    tr = tracing.make(False, "compile", tmp_path)
    step = tr.step("x")
    step.row("selected", "a")
    step.note("n")
    assert step.rows == [] and step.notes == []
    assert tr.save(out_dir=tmp_path) is None
    assert not (tmp_path / "_bramber" / "traces").exists()


def test_null_steps_do_not_share_state_across_runs():
    """Call sites assign into `step.outputs` directly — a no-op *method* cannot intercept
    that. Each null step must therefore be its own object, or NULL_TRACE would grow
    without bound and leak one run's data into the next."""
    a = tracing.NULL_TRACE.step("s")
    a.outputs["leak"] = 1
    b = tracing.NULL_TRACE.step("s")
    assert b.outputs == {}
    assert a is not b


def test_make_returns_a_real_trace_when_enabled(tmp_path: Path):
    assert tracing.make(True, "compile", tmp_path).enabled is True
    assert tracing.make(False, "compile", tmp_path).enabled is False


# --- timing -----------------------------------------------------------------

def test_timing_accumulates_and_close_does_not_clobber_it(tmp_path: Path):
    """Interleaved steps (ingest runs all five adapter phases in one loop) must report the
    time *their own phase* consumed. A naive start/stop makes all five report the whole
    loop's wall clock — five copies of a number that describes none of them. `close()`
    must therefore defer to an accumulated figure rather than overwrite it."""
    tr = tracing.make(True, "ingest", tmp_path)
    step = tr.step("normalize")
    for _ in range(3):
        with step.timing():
            sum(range(20000))
    accumulated = step.duration_ms
    assert accumulated > 0
    step.close()
    assert step.duration_ms == accumulated


def test_close_times_a_step_that_never_used_timing(tmp_path: Path):
    tr = tracing.make(True, "compile", tmp_path)
    with tr.step("render") as st:
        sum(range(1000))
    assert st.duration_ms is not None and st.duration_ms >= 0


# --- the fixtures: claim-shaped units ---------------------------------------
#
# The shape `bramber.scan.units_for_source` produces: `kind: "claim"`, a graded payload with a
# list-valued `topics`, and `provenance.source_artifacts` as a **list** — the shape that makes
# corroboration expressible without a schema break. No view anywhere: units are view-agnostic
# by contract, and views only select.

def _claim(key, *, statement=None, kind="claim", evidence_strength="strong",
           recency="2026-05-01", topics=("q1",), tier="reported"):
    return {
        "kind": kind,
        "payload": {
            "claim_key": key,
            "statement": statement or f"{key}: the market consolidated around two vendors.",
            "evidence_strength": evidence_strength,
            "recency": recency,
            "topics": list(topics),
        },
        # extract_path/scan_path are stamped by `_units_file`, so a unit can never claim
        # provenance from a source whose envelope it does not live in.
        "provenance": {"source_artifacts": [{"reliability_tier": tier}]},
    }


SELECTOR_LINES = (
    "kind: claim\n"
    "match.evidence_strength: strong, moderate\n"
    "match.topics: q1, q2\n"
    "dedup_by: claim_key\n"
    "order_by: recency\n"
    "project: statement, evidence_strength, recency\n"
    "section: Current reading"
)
SEL = parse_selector(f"```selector\n{SELECTOR_LINES}\n```", "market-overview")


# --- _reject_reason: the audit payload --------------------------------------

@pytest.mark.parametrize("unit, sel, expected", [
    (_claim("CLAIM-001"), SEL, None),                                # passes every predicate
    (_claim("CLAIM-001", topics=("q1", "off-topic")), SEL, None),    # list any-of: one hit passes
    (_claim("CLAIM-001", kind="signal"), SEL, "kind"),
    (_claim("CLAIM-001", topics=("off-topic",)), SEL, "topics"),
    (_claim("CLAIM-001", topics=()), SEL, "topics"),                 # an empty list is not a pass
    (_claim("CLAIM-001", evidence_strength="speculative"), SEL, "evidence_strength"),
])
def test_reject_reason_names_the_predicate_that_excluded_the_unit(unit, sel, expected):
    reason = _reject_reason(unit, sel)
    if expected is None:
        assert reason is None
    else:
        # Every branch formats as `<predicate> is <value>, view selects <allowed>`, so the
        # predicate leads the sentence — asserting on the prefix cannot be satisfied by the
        # word merely appearing in the trailing "view selects …" clause.
        assert reason and reason.startswith(expected), reason


def test_reject_reason_reports_the_first_failing_predicate_only():
    """A unit failing several predicates reports the first in evaluation order — the reason
    is an explanation, not an exhaustive diagnosis."""
    both_wrong = _claim("CLAIM-001", kind="signal", evidence_strength="speculative")
    assert _reject_reason(both_wrong, SEL).startswith("kind")


# --- select: every considered unit gets a row -------------------------------

def _units_file(tmp_path: Path, slug: str, units: list[dict]) -> Path:
    """Write one source's units envelope, stamping each unit's provenance to *this* source.

    Stamping here rather than at the call sites is what keeps the corroboration fixtures
    honest: two units in one file necessarily share an extract_path (a repeat is a dedup),
    and units in different files necessarily do not (a repeat is corroboration).
    """
    for u in units:
        for art in (u.get("provenance") or {}).get("source_artifacts", []):
            art["extract_path"] = f"_bramber/extracts/{slug}.md"
            art["scan_path"] = f"_bramber/scans/{slug}.md"
    p = tmp_path / "_bramber" / "units" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"extract_path": f"_bramber/extracts/{slug}.md",
                             "qname": slug, "units": units}), encoding="utf-8")
    return p


def test_select_traces_every_unit_it_considered(tmp_path: Path):
    f1 = _units_file(tmp_path, "acme", [
        _claim("CLAIM-001"),                                          # selected
        _claim("CLAIM-002", kind="signal"),                           # rejected: kind
        _claim("CLAIM-003", topics=("off-topic",)),                   # rejected: topics
        _claim("CLAIM-004", evidence_strength="speculative"),         # rejected: evidence_strength
        _claim("CLAIM-001", statement="restated later in the same call"),   # deduped: same source
    ])
    f2 = _units_file(tmp_path, "widget", [_claim("CLAIM-001")])       # corroborated: 2nd source

    tr = tracing.make(True, "select", tmp_path)
    picked = select_units([f1, f2], SEL, trace=tr)

    step = _steps(tr)["select"]
    assert step["counts"] == {"selected": 1, "rejected": 3, "deduped": 1, "corroborated": 1}
    assert step["outputs"]["considered"] == 6      # nothing considered goes unrecorded
    assert step["outputs"]["selected"] == len(picked) == 1
    assert len(step["rows"]) == 6

    # Tracing does not change what is selected — the trace observes the run, it is not a
    # second implementation of the rule.
    assert [e["dedup_key"] for e in picked] == \
           [e["dedup_key"] for e in select_units([f1, f2], SEL)]

    # keyed by claim key, not ref: several units here share a statement prefix
    rejected = {r["data"]["payload"]["claim_key"]: r
                for r in step["rows"] if r["status"] == "rejected"}
    assert rejected["CLAIM-002"]["reason"].startswith("kind")
    assert rejected["CLAIM-003"]["reason"].startswith("topics")
    assert rejected["CLAIM-004"]["reason"].startswith("evidence_strength")
    # every recorded row carries the whole unit, so the auditor can inspect, not just read
    assert all(r["data"]["payload"]["claim_key"] for r in step["rows"])

    dedup = next(r for r in step["rows"] if r["status"] == "deduped")
    assert "already selected" in dedup["reason"]

    # Corroboration is the signal the engine used to delete: a second source asserting an
    # already-selected key must NOT read the same as one source repeating itself.
    corrob = next(r for r in step["rows"] if r["status"] == "corroborated")
    assert corrob["group"] == "widget" and "support is now 2" in corrob["reason"]
    assert picked[0]["support"] == 2
    assert step["outputs"]["corroborated (support > 1)"] == 1


def test_select_rows_group_under_the_source_that_produced_them(tmp_path: Path):
    """The page reads source-first: a reader scanning sources sees every unit a source
    yielded and what became of each, without filtering for it."""
    f1 = _units_file(tmp_path, "acme", [
        _claim("CLAIM-001"),
        _claim("CLAIM-002", kind="signal"),
    ])
    f2 = _units_file(tmp_path, "widget", [_claim("CLAIM-003")])

    tr = tracing.make(True, "select", tmp_path)
    select_units([f1, f2], SEL, trace=tr)
    step = _steps(tr)["select"]

    # every row is attributable to a source, and both fates of source "acme" sit together
    assert all(r["group"] for r in step["rows"])
    a_rows = [r for r in step["rows"] if r["group"] == "acme"]
    assert {r["status"] for r in a_rows} == {"selected", "rejected"}
    # the unit's kind rides along as a chip, so a reader sees *what sort of thing* was dropped
    assert {r["tag"] for r in a_rows} == {"claim", "signal"}
    # group metadata backs the header: where the source lives, how much it produced
    assert step["groups"]["acme"] == {"extract": "_bramber/extracts/acme.md",
                                      "units_file": "_bramber/units/acme.json", "produced": 2}


def test_a_source_that_produced_no_units_is_still_shown(tmp_path: Path):
    """Silence is a finding. A source that yielded nothing must appear saying so —
    absence that is invisible reads as absence that never happened."""
    f = _units_file(tmp_path, "barren", [])
    tr = tracing.make(True, "select", tmp_path)
    select_units([f], SEL, trace=tr)
    row = _steps(tr)["select"]["rows"][0]
    assert row["status"] == "empty" and row["group"] == "barren"
    assert "no units" in row["reason"]


def test_selector_is_recorded_as_the_rule_the_run_obeyed(tmp_path: Path):
    """The selector comes from a human-gated view.md. Recording the parsed form is what
    makes the trace an audit rather than a log: it shows the rule, not just the outcome."""
    f = _units_file(tmp_path, "acme", [_claim("CLAIM-001")])
    tr = tracing.make(True, "select", tmp_path)
    select_units([f], SEL, trace=tr)
    sel = _steps(tr)["select"]["inputs"]["selector (from view.md)"]
    assert sel["kind"] == "claim"
    assert sel["dedup_by"] == "claim_key" and sel["project"][0] == "statement"

    # `match` is a dict OF sets, so normalizing it needs recursion, not one level. Without that
    # the nested sets survived into the record and serialized as a Python repr in set-iteration
    # order — non-deterministic between runs, in the single field whose purpose is showing the
    # rule the run obeyed. Asserting the SORTED LIST is what pins the fix: a set would compare
    # equal here regardless of order, so only the list shape actually proves determinism.
    assert sel["match"]["evidence_strength"] == ["moderate", "strong"]
    assert isinstance(sel["match"]["evidence_strength"], list)

    # …and the trace is therefore serializable with no `default=` fallback smoothing it over.
    # A fallback would have made the buggy record *look* fine, which is how it survived.
    json.dumps(tr.as_dict())
    assert tr.save(out_dir=tmp_path / "out").exists()


# --- compile end-to-end -----------------------------------------------------

def _extract_file(tmp_path: Path, slug: str, key: str):
    p = tmp_path / "_bramber" / "extracts" / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nidentity_kind: content_sha\nidentity_key: {key}\n"
                 f'identity_json: {{"sha": "{key}"}}\nsource_type: article\ntitle: "{slug}"\n'
                 f"source_url: https://example.test/{slug}\nauthor: A. Reporter\n"
                 f"date_published: 2026-05-01\ndate_ingested: 2026-05-02\n---\n# {slug}\n",
                 encoding="utf-8")


def _view_file(tmp_path: Path, slug: str, name: str, selector_lines: str):
    p = tmp_path / "views" / slug / "view.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {name}\nslug: {slug}\nview_version: 1\nmaintainer: human\n---\n"
                 f"# {name}\n\n## Projects\nprose.\n\n```selector\n{selector_lines}\n```\n",
                 encoding="utf-8")


SUBJECT = "Two vendors now hold most of the seat share."


def _fixture(tmp_path: Path):
    _extract_file(tmp_path, "acme", "k_acme")
    _units_file(tmp_path, "acme", [
        _claim("CLAIM-001", statement=SUBJECT),
        _claim("CLAIM-002", evidence_strength="speculative"),   # rejected: evidence_strength
    ])
    _view_file(tmp_path, "market-overview", "Market Overview", SELECTOR_LINES)


def test_compile_trace_covers_every_step_and_writes_a_page(tmp_path: Path):
    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    _fixture(tmp_path)

    tr = tracing.make(True, "compile", tmp_path, {"view": "market-overview"})
    res = compile_view(tmp_path, "market-overview", trace=tr)
    assert res["created"]

    steps = _steps(tr)
    assert list(steps) == ["sync", "read view", "select", "render", "write version"]
    assert steps["read view"]["outputs"]["view name"] == "Market Overview"
    assert steps["select"]["counts"] == {"selected": 1, "rejected": 1}
    assert steps["render"]["outputs"]["content_sha"]
    assert "Current reading" in steps["render"]["outputs"]["RESOURCE.md"]
    assert steps["write version"]["rows"][0]["status"] == "created"
    assert all(s["duration_ms"] is not None for s in steps.values())

    page = tr.save()
    assert page.exists() and page.parent == tmp_path / "_bramber" / "traces"
    assert page.with_suffix(".json").exists()
    html = page.read_text(encoding="utf-8")
    assert SUBJECT in html
    # the page is self-contained: no fetch of the trace at view time
    assert "const TRACE = {" in html


def test_trace_records_a_no_op_recompile_as_unchanged(tmp_path: Path):
    """The auditor's other question: not "what changed" but "why did nothing change?"."""
    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")
    _fixture(tmp_path)
    compile_view(tmp_path, "market-overview")

    tr = tracing.make(True, "compile", tmp_path)
    assert compile_view(tmp_path, "market-overview", trace=tr)["created"] is False
    row = _steps(tr)["write version"]["rows"][0]
    assert row["status"] == "unchanged" and "content sha" in row["reason"]


def test_two_traces_in_the_same_second_do_not_overwrite_each_other(tmp_path: Path):
    """`compile --view a && compile --view b` takes well under a second, and the filename is
    second-resolution. An audit artifact that silently clobbers another audit artifact is the
    one failure this tool cannot have — so the second write takes a suffix."""
    pages = []
    for view in ("market-overview", "pricing-pressure", "roles"):
        tr = tracing.make(True, "compile", tmp_path, {"view": view})
        tr.step("select").outputs["view"] = view
        pages.append(tr.save())

    assert len({p.name for p in pages}) == 3, "each run must get its own page"
    assert all(p.exists() and p.with_suffix(".json").exists() for p in pages)
    # every run's data survived — none was overwritten by a later one
    written = [json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))["args"]["view"]
               for p in pages]
    assert written == ["market-overview", "pricing-pressure", "roles"]


def test_render_html_escapes_a_script_close_in_recorded_content(tmp_path: Path):
    """Trace values are arbitrary source text. A `</script>` inside one would close the
    inlined data tag early and break the page — the one real hazard of embedding JSON."""
    tr = tracing.make(True, "ingest", tmp_path)
    with tr.step("normalize") as st:
        st.outputs["body"] = "text with </script><script>evil()</script> inside"
    html = tracing.render_html(tr.as_dict())
    assert "</script><script>evil()" not in html
    assert "<\\/script>" in html


def test_clip_trims_large_values_and_says_so():
    assert tracing.clip("a" * 50, 100) == "a" * 50
    clipped = tracing.clip("a" * 500, 100)
    assert clipped.startswith("a" * 100) and "400 more chars" in clipped
    assert tracing.clip(None) == ""
