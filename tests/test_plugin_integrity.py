"""The agent layer's structural contract (the PRF port, specs/01 step 6).

The agent layer is prose — commands and docs the model follows — so most of its failure
modes are structural, and structural is testable: a command referencing `/bramber:evaluate`
when no `evaluate.md` exists, a doc citing a FORMAT-SPEC section that was never written,
PRF vocabulary that would misdirect an agent into writing `prfs/` paths, or the FORMAT-SPEC
extract header drifting from what `ingest.py` actually writes (the exact drift that made
every text source index with a NULL url).

These tests turned last session's archaeology — "the lift skipped step 6 and nothing
noticed for weeks" — into a red bar.

Run:  cd bramber && python -m pytest tests/test_plugin_integrity.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "bramber-plugin"
COMMANDS = PLUGIN / "commands"
FORMAT_SPEC = PLUGIN / "docs" / "FORMAT-SPEC.md"
ORCHESTRATOR = PLUGIN / "docs" / "ORCHESTRATOR.md"


def _plugin_md_files() -> list[Path]:
    return sorted(PLUGIN.rglob("*.md"))


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --- the lift's step 6 exists ------------------------------------------------

def test_the_agent_layer_docs_exist():
    """CLAUDE.md and specs/00 define the Agent layer as 'guided by view.md + FORMAT-SPEC'.
    For weeks that pointed at a file that didn't exist."""
    assert FORMAT_SPEC.exists(), "FORMAT-SPEC.md is the agent layer's schema source"
    assert ORCHESTRATOR.exists(), "ORCHESTRATOR.md is the agent layer's protocol contract"


def test_all_seven_lift_commands_exist():
    """specs/01 names the command roster; /bramber:evaluate especially is load-bearing (it is
    the only command allowed to edit human-gated framing — five files reference it)."""
    for name in ("init", "intake", "orchestrate", "process",
                 "evaluate", "consistency-pass", "new-view"):
        assert (COMMANDS / f"{name}.md").exists(), f"missing command: {name}.md"


# --- cross-references resolve ------------------------------------------------

def test_every_referenced_bramber_command_exists():
    missing = []
    for f in _plugin_md_files():
        for name in set(re.findall(r"/bramber:([a-z-]+)", _read(f))):
            if not (COMMANDS / f"{name}.md").exists():
                missing.append(f"{f.relative_to(REPO)} references /bramber:{name}")
    assert not missing, "dangling command references:\n" + "\n".join(missing)


def test_every_section_reference_resolves():
    """Commands and docs cite '<DOC> § <Section>' (FORMAT-SPEC or ORCHESTRATOR); each must be a
    real heading in one of the protocol docs, or an agent following the protocol dead-ends."""
    headings = [h.strip() for doc in (FORMAT_SPEC, ORCHESTRATOR)
                for h in re.findall(r"^##\s+(.+)$", _read(doc), re.M)]
    unresolved = []
    for f in _plugin_md_files():
        for ref in set(re.findall(r"§\s*([A-Za-z][A-Za-z ./-]*[A-Za-z.])", _read(f))):
            ok = any(ref.lower() in h.lower() or h.lower() in ref.lower()
                     for h in headings)
            if not ok:
                unresolved.append(f"{f.relative_to(REPO)} cites § {ref!r}")
    assert not unresolved, "unresolved protocol-doc section refs:\n" + "\n".join(unresolved)


def test_every_plugin_root_reference_resolves():
    """Commands cite `${CLAUDE_PLUGIN_ROOT}/...` paths to send an agent at a real file. Nothing
    validated them, so a file rename left the pointers dangling silently — green bar, dead-ended
    agent. This is the same guard class as the command and section-reference tests above; it was
    simply never written."""
    pat = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}[\\/]([A-Za-z0-9._\\/-]+)")
    dangling = []
    for f in _plugin_md_files() + sorted(PLUGIN.rglob("*.json")):
        text = _read(f)
        for m in pat.finditer(text):
            rel = m.group(1).replace("\\", "/").rstrip(".,;:")
            if not (PLUGIN / rel).exists():
                line = text[: m.start()].count("\n") + 1
                dangling.append(f"{f.relative_to(REPO).as_posix()}:{line} -> {rel}")
    assert not dangling, "plugin paths that do not resolve:\n" + "\n".join(sorted(set(dangling)))


def test_every_repo_relative_file_reference_resolves():
    """Docs cite repo-relative paths (`specs/07-...md`, `bramber/compile.py`). A rename done by
    text substitution rewrites those pointers *inside* the citation, producing a reference that
    reads perfectly and resolves to nothing — exactly how the consilience -> bramber pass turned
    the 2026-07-20 ruling "rename prism to consilience" into a file that never existed.

    Two kinds of file are excluded as a *source* of references, for the same reason: they are
    historical records, and a historical record may legitimately cite a file that has since been
    renamed or deleted. Rewriting one to keep a guard quiet would be falsifying the record.

      - everything under `decisions/` (the fresh-repo record cites a report deleted at HEAD,
        which is the entire point of it);
      - any document carrying a `SUPERSEDED` banner in its opening lines — detected by reading
        the banner, never by a hardcoded filename list, because such a list is one more place to
        forget to update and would go stale exactly when it mattered.

    `docs/state/` is IN scope, and that is the point of it existing: CLAUDE.md pushed its
    per-area detail down a tier, so most of the repo's pointers now live there. A disclosed
    pointer nobody checks is worth less than the prose it replaced.

    The rest of `docs/` is NOT a source. `docs/PIPELINE-WALKTHROUGH.md` shows artifact paths
    under a throwaway root (`bramber/extracts/<stem>.md`) which are illustrative and must not
    resolve; checking them would produce a guard people learn to suppress.
    """
    roots = ("decisions", "specs", "tests", "bramber", "bramber-plugin", "reports", "tools",
             "docs", "evals")
    pat = re.compile(
        r"(?<![\w./-])(" + "|".join(roots) + r")/[A-Za-z0-9._/-]+\.(?:md|py|json|sql|toml|mjs|html)")
    sources = [REPO / "CLAUDE.md", REPO / "README.md"]
    sources += sorted((REPO / "specs").glob("*.md"))
    sources += sorted((REPO / "docs" / "state").glob("*.md"))
    sources += sorted(REPO.glob("NOTE-*.md"))
    dangling = []
    for f in sources:
        if not f.exists():
            continue
        text = _read(f)
        if "SUPERSEDED" in "\n".join(text.splitlines()[:20]):
            continue
        for m in pat.finditer(text):
            rel = m.group(0)
            if not (REPO / rel).exists():
                line = text[: m.start()].count("\n") + 1
                dangling.append(f"{f.relative_to(REPO).as_posix()}:{line} -> {rel}")
    assert not dangling, (
        "repo-relative file references that do not resolve:\n" + "\n".join(sorted(set(dangling))))


def test_no_legacy_vocabulary_misdirects_agents():
    """Four supersessions now: PRF -> prism (the lift), prism -> consilience, consilience ->
    foinse, foinse -> bramber (the rename that landed; consilience was never committed, so it
    lives only in decisions/ and in this guard).

    Historical mentions ('ported from PRF', 'renamed from prism', 'the sibling
    instance runs on its own port') are fine; these exact tokens are not — an agent following them writes to paths
    and names that do not exist in a bramber project. This guard is what makes a rename
    a mechanical pass rather than an archaeology exercise: it caught the PRF port, and it
    held both renames the same way."""
    forbidden = (
        # PRF -> prism
        "prfs/", "prf.db", "PRF_ROOT", "_orchestrator", "/prf:", "lens_version:",
        # prism -> consilience
        "prism.db", "PRISM_ROOT", "PRISM_DB", "/prism:", "_prism", "prism://", "prism-plugin",
        # consilience -> foinse
        "consilience.db", "CONSILIENCE_ROOT", "CONSILIENCE_DB", "/consilience:",
        "_consilience", "consilience://", "consilience-plugin",
        # foinse -> bramber
        "foinse.db", "FOINSE_ROOT", "FOINSE_DB", "/foinse:",
        "_foinse", "foinse://", "foinse-plugin",
        # the mandate withdrawal (specs/09): the mandate left the product entirely, so any
        # plugin prose steering an agent at it dead-ends. Guarded as the bare word — the
        # plugin ships fresh, so it has no legitimate historical mentions to spare.
        "mandate",
        # the per-(source x view) digest withdrawal (specs/09): digests/ directories and the
        # digest artifact are gone; the per-source artifact is the scan.
        "digests/", "digest_path", "/digests",
    )
    hits = []
    files = _plugin_md_files() + [REPO / "bramber" / "intake_server.py"]
    for f in files:
        text = _read(f)
        for tok in forbidden:
            for m in re.finditer(re.escape(tok), text):
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{f.relative_to(REPO)}:{line} contains {tok!r}")
    assert not hits, "legacy vocabulary leaked through a supersession:\n" + "\n".join(hits)


def test_no_model_names_in_the_plugin_only_tiers():
    """M05 rule (~/.claude/CLAUDE.md): reference stakes tiers (cheap/default/premium), never model
    names, so a model-generation change is a one-row edit in the rubric — not a sweep through
    bramber. The plugin names tiers; a leaked model name would silently pin bramber to a generation."""
    forbidden = ("haiku", "sonnet", "opus", "fable")
    hits = []
    for f in _plugin_md_files():
        text = _read(f)
        for tok in forbidden:
            for m in re.finditer(tok, text, re.IGNORECASE):
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{f.relative_to(REPO)}:{line} names model {tok!r} — use a tier")
    assert not hits, "model names leaked into the plugin (M05: tiers, not models):\n" + "\n".join(hits)


# --- writer/spec agreement ---------------------------------------------------

def test_format_spec_extract_header_matches_what_ingest_writes():
    """The provenance bug (fixed 2026-07-17) was the reader and writer disagreeing about header
    keys. This pins the third party — the spec — to them.

    It used to check a **hardcoded tuple** against FORMAT-SPEC and never read `ingest.py` or
    `db.py` at all, so it asserted that two documents agreed while the code was free to drift
    from both (specs/07 §5 named it as false comfort). Now that the key set is one declared
    artifact (`bramber/engine/header.py`, specs/06 T1.1), it derives from that instead — and
    compares **set-equality**, so the spec documenting a field nobody writes fails too. A
    one-directional check is how a removed field lingers in the docs for months."""
    from bramber.engine import header

    section = _read(FORMAT_SPEC).split("## Extract Header")[1].split("\n## ")[0]
    fence = section.split("```yaml")[1].split("```")[0]
    documented = set(re.findall(r"^([a-z_]+):", fence, re.M))
    declared = set(header.SOURCE_FIELDS)

    assert documented == declared, (
        "FORMAT-SPEC's Extract Header and bramber/engine/header.py disagree — "
        f"documented but not declared: {sorted(documented - declared)}; "
        f"declared but not documented: {sorted(declared - documented)}")


def test_format_spec_snapshot_template_matches_db_writer():
    """The Version Snapshot section claims 'the format is exact' — hold it to that against
    db._snapshot_text's actual key order."""
    section = _read(FORMAT_SPEC).split("## Version Snapshot")[1].split("\n## ")[0]
    for key in ("resource:", "version:", "created_at:", "content_sha:", "change_summary:", "source:"):
        assert key in section
    # the pipe-triple is the lineage carrier — the spec must show it
    assert section.count("source: <extract-path> | <scan-path>") >= 1


# --- scan lineage round-trip (the interpretive middle layer) ------------------

def _load_db():
    spec = importlib.util.spec_from_file_location(
        "bramber_db_integrity", REPO / "bramber" / "engine" / "db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_text_scan_lineage_survives_write_snapshot_and_rebuild(tmp_path: Path):
    """The scan is the interpretive artifact between a source and every resource built on it.
    Its path rides the lineage pipe-triple: resource version -> snapshot -> (delete DB) ->
    rebuild, and the scan_path must survive the whole loop — that is what makes 'which reading
    produced this resource' answerable after a DB loss."""
    db = _load_db()
    db.configure(root=tmp_path, db=tmp_path / "bramber.db")

    # a text extract, a view, and a scan of that extract
    (tmp_path / "_bramber" / "extracts").mkdir(parents=True)
    (tmp_path / "_bramber" / "extracts" / "thariq.md").write_text(
        "---\nidentity_kind: content_sha\nidentity_key: k1\nsource_type: transcript\n"
        'title: "T"\ndate_ingested: 2026-07-17\n---\nbody\n', encoding="utf-8")
    (tmp_path / "views" / "market-overview").mkdir(parents=True)
    (tmp_path / "views" / "market-overview" / "view.md").write_text(
        "---\nname: Market Overview\nslug: market-overview\nview_version: 1\n"
        "maintainer: human\n---\n# Market Overview\n", encoding="utf-8")
    scan_rel = "_bramber/scans/thariq.md"
    scan_file = tmp_path / scan_rel
    scan_file.parent.mkdir(parents=True)
    scan_file.write_text(
        "---\nsource: _bramber/extracts/thariq.md\nscan_date: 2026-07-17\n"
        "discarded: false\n---\n## Claims\n- claim\n", encoding="utf-8")

    db.sync_from_disk()
    res = db.write_resource_version(
        "market-overview", "overview", title="Overview", content="# Overview\nbody\n",
        change_summary="first synthesis",
        sources=[{"extract": "_bramber/extracts/thariq.md", "scan": scan_rel,
                  "contribution": "capability-overhang claims"}])
    assert res["created"]

    def _scan_paths():
        conn = sqlite3.connect(str(tmp_path / "bramber.db"))
        try:
            return [r[0] for r in conn.execute("SELECT scan_path FROM version_sources")]
        finally:
            conn.close()

    assert _scan_paths() == [scan_rel]

    # the snapshot carries it as a pipe-triple…
    snap = (tmp_path / "views" / "market-overview" / "resources" / "overview"
            / "versions" / "1.md").read_text(encoding="utf-8")
    assert f"source: _bramber/extracts/thariq.md | {scan_rel} | capability-overhang claims" in snap

    # …so a full DB loss is a non-event
    (tmp_path / "bramber.db").unlink()
    db.sync_from_disk()
    assert _scan_paths() == [scan_rel], "scan lineage must survive a rebuild from disk"


# --- intake server hygiene ---------------------------------------------------

def test_intake_server_is_stdlib_only_and_import_clean(tmp_path: Path, monkeypatch):
    """The server is user-launched, but it lives in the package — importing it must not
    create directories (a test or tool that imports the module for inspection should not
    scaffold _bramber/ in the cwd), and it must stay stdlib so `bramber intake` never fails on
    a missing dependency."""
    monkeypatch.chdir(tmp_path)
    src = _read(REPO / "bramber" / "intake_server.py")
    imported = set(re.findall(r"^(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", src, re.M))
    non_stdlib = {m for m in imported if m not in sys.stdlib_module_names}
    assert not non_stdlib, f"intake_server imports non-stdlib modules: {non_stdlib}"

    spec = importlib.util.spec_from_file_location(
        "bramber_intake_probe", REPO / "bramber" / "intake_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not (tmp_path / "_bramber").exists(), "importing intake_server must have no side effects"
    assert mod.PORT == 47825  # sibling instances take adjacent ports; all run side by side


# --- genre view starters (templates/views/) ----------------------------------

VIEW_TEMPLATES = PLUGIN / "templates" / "views"
# The payload fields a selector may reference (new-view.md step 4 documents these).
PAYLOAD_FIELDS = {"claim_key", "statement", "evidence_strength", "recency", "topics"}
# Eval-corpus domain markers. The starters are product artifacts for ANY domain; leaking the
# one domain in front of us into them is the prose version of the seam leak test_seam.py guards.
#
# The eval customer's NAME was removed from this list on 2026-08-04. It never belonged: these are
# markers for a *domain*, and a company name is an instance of one. Carrying it here also coupled
# bramber to a name that lives only in corpus data — which is exactly what made renaming that
# customer a sweep through this repo instead of a change to one registry file. The domain markers
# below still catch the leak that matters: a starter carrying the customer's name would be
# describing KYC/AML/merchant work and trip one of these.
DOMAIN_MARKERS = ("kyc", "dnb", "wwft", "aml", "merchant", "fintech", "sanction")


def _view_templates() -> list[Path]:
    files = [p for p in sorted(VIEW_TEMPLATES.glob("*.md")) if p.name != "README.md"]
    assert len(files) >= 6, f"genre starter library incomplete: {[p.name for p in files]}"
    return files


def test_view_templates_carry_the_full_view_shape():
    for p in _view_templates():
        text = _read(p)
        for key in ("name:", "slug:", "view_version: 1", "maintainer: human"):
            assert key in text, f"{p.name}: frontmatter missing {key}"
        for section in ("## Thesis", "## Projects", "## Weighting", "## Discard"):
            assert section in text, f"{p.name}: missing {section}"


def test_view_template_selectors_parse_through_compiles_own_reader():
    # Not a string check: each starter's block goes through the same parse a real
    # `bramber compile` uses, so a starter cannot drift from what compile accepts.
    from bramber.compile import parse_selector
    for p in _view_templates():
        sel = parse_selector(_read(p), p.stem)  # raises SystemExit if block/keys missing
        fields = {sel["dedup_by"], sel["order_by"], *sel["project"], *sel["match"]}
        unknown = fields - PAYLOAD_FIELDS
        assert not unknown, f"{p.name}: selector references unknown payload fields {unknown}"
        assert sel["kind"] == "claim", f"{p.name}: text units are claims"


def test_view_templates_are_domain_neutral():
    for p in sorted(VIEW_TEMPLATES.glob("*.md")):
        lowered = _read(p).lower()
        hits = [m for m in DOMAIN_MARKERS if m in lowered]
        assert not hits, f"{p.name}: eval-corpus domain vocabulary leaked into a generic starter: {hits}"


def test_the_orchestration_reads_the_degrade_channel_it_is_handed():
    """Screen finding G1, third limb. `materialize` computes the degrade counters correctly and
    words each notice correctly — and until this gate, nothing in the plugin told the agent to
    read them or carry them into the report a human sees. A signal computed and reported to
    nobody is worse than no signal: it reads, from the code, as though the failure boundary is
    covered.

    Derived from the shipped file rather than transcribed, so deleting the notices table or the
    Report clause fails here."""
    text = _read(COMMANDS / "orchestrate.md")
    materialize_on = "**`materialize` writes notices to stderr"
    assert materialize_on in text, "the materialize step must tell the agent the notices exist"

    report = text.split("**4. Report.**", 1)
    assert len(report) == 2, "the Report step must still exist"
    clause = report[1].split("**", 1)[0] + report[1]
    assert "notice" in clause.lower(), \
        "the Report step must enumerate the notices, or the degrade never reaches a human"

    # Each degrade the engine can emit needs a row an agent can act on. Named by the WORDS the
    # notices use, because that is what an agent matches against stderr.
    for phrase in ("malformed item bullet", "could not place", "endorsement was dropped",
                   "unwitnessed", "sentinel segment escalated"):
        assert phrase in text, f"orchestrate.md does not cover the `{phrase}` degrade"
