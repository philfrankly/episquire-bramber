"""Cross-cutting selection — the deterministic half of the meta-documents.

`compile.py` answers *what does this view project*. Every entry point in it reads one `view.md`
and applies one selector. This module answers the other question — *what does the corpus say as a
whole* — for the documents that are about the record rather than about a perspective on it: an
executive summary, a contradiction register, a glossary, a scope description.

**What this module used to be, and why it is smaller now.** Until 2026-08-07, extraction ran per
(source × view): each view read every source through its own Thesis and counted its own
`CLAIM-001` upward from its own feed. A key therefore meant nothing outside the view that minted
it, and a cross-view join that merged two views' `CLAIM-007` would report a support count no
source ever gave — a plausible document with invented provenance, in the exact field the product
is sold on. This module existed largely to police that boundary: a `key_scope` field on every
Unit, a pre-scan that refused any join touching an agent-assigned key, and a third verifier
property enforcing it.

The view-agnostic scan removed the boundary rather than the guard. There is now **one** unit
store, extracted once per source, and every key in it is unique across the corpus — a name the
sources carry is unique by construction (casefolded), and an agent-assigned key is unique because
it is minted inside the namespace of the source that minted it (`scan.resolve_keys`). Nothing can
collide, so nothing needs refusing, and the guard is gone with the hazard. See the addendum to
the 2026-08-06 ruling "minted and observed keys" and
the 2026-08-07 ruling "keys are minted in a source owned namespace".

**What survives is the part that was never about namespaces.** Selection keeps one representative
per dedup key and silently drops the rest, which is fatal for a glossary — it would show one
source's definition of a term and discard the others, and two incompatible definitions of one
word is precisely the finding. So `select_across` runs a second, additive pass and returns a
`variants` map alongside the merged entries. Divergence detection is then mechanical: same key,
more than one distinct projected value.

**It lives here and not in `compile.py`** because it reads the store as a whole rather than
through a selector, and not in `bramber/engine/` because it speaks `extract_path` and payload
field names, and the engine is domain-blind by construction (`tests/test_seam.py`). It sits at
`compile.py`'s layer — domain-blind by correction — imports `compile` and `engine.db`, and the
engine never imports it.

**The merge arithmetic is not reimplemented.** `select_across` builds a selector dict and calls
`compile.select_units` unchanged, so support counts, reliability floors and the `--trace` audit
surface come from the same code that produced the per-view bullet and cannot drift from it. One
property makes that reuse safe rather than merely convenient: `select_units` dedups merged
provenance on `extract_path`, so a source cited by two feeds still counts once.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

from bramber import compile as _compile
from bramber import scan as _scan
from bramber import trace as _trace
from bramber.adapter import reliability_floor
from bramber.engine import db

# Feed modes, declared once. Anything else is a caller bug, not a fallback.
#
#   sources         the spine: every source, and what each view made of it. Grouped by
#                   extract_path, which the engine assigns and no view chooses.
#   units           select over the whole store on a payload key, keeping variants so a glossary
#                   can show every definition rather than one representative.
#   topics          aggregate `payload.topics` across every unit kind that carries them.
#   contradictions  the register. Contradiction keys are namespaced like claim keys, so two
#                   sources recording one tension REUSE the key and it gains support normally.
#   per-view        run each view's own selection and return them side by side, keyed by view.
#                   How an executive summary reads what each view concluded on its own terms.
JOIN_MODES = ("sources", "units", "topics", "contradictions", "per-view")

# What a feed may draw. Each renders a structure the data already contains — no inferred edges.
RENDERERS = ("coverage", "divergence", "contradictions")

# Shaping keys a `units` feed must declare. Same no-defaults rule as the selector's, for the same
# reason: a default would join on whatever field happened to exist and render the result as
# though it had been asked for.
REQUIRED_UNIT_FEED_KEYS = ("kind", "dedup_by", "order_by", "project")


class UnsafeJoin(SystemExit):
    """Raised instead of returning a document that would be wrong in a way nobody could see.

    A `SystemExit` subclass so a CLI caller dies with the message and a library caller can still
    catch it by name. It no longer guards a key namespace — the view-agnostic scan removed that
    hazard — but it still refuses the two things that produce a plausible-and-wrong artifact: a
    feed whose shape was inferred rather than declared, and a merged entry that fails
    `verify_join`.
    """


# ---------------------------------------------------------------------------
# reading what is on disk
# ---------------------------------------------------------------------------

def views_on_disk(data_root) -> list[str]:
    """Every view slug with a `view.md`, sorted. The meta layer never invents a view."""
    db.configure(root=data_root)
    if not db.VIEWS_DIR.exists():
        return []
    return sorted(p.name for p in db.VIEWS_DIR.iterdir()
                  if p.is_dir() and (p / "view.md").exists())


def _is_meta_view(data_root, slug: str) -> bool:
    db.configure(root=data_root)
    spec = db.VIEWS_DIR / slug / "view.md"
    if not spec.exists():
        return False
    fields, _, _ = db.split_frontmatter(spec.read_text(encoding="utf-8"))
    return _compile.view_scope(fields) == "meta"


def _source_views(data_root, views: Optional[Iterable[str]]) -> list[str]:
    """The `scope: source` views in play. Meta views select nothing of their own — including,
    importantly, the calling document's own view, which would otherwise recurse into itself."""
    scope = list(views) if views is not None else views_on_disk(data_root)
    return [v for v in scope if not _is_meta_view(data_root, v)]


def _units_files(data_root) -> list[Path]:
    db.configure(root=data_root)
    units_dir = db.ROOT / "_bramber" / "units"
    return sorted(units_dir.glob("*.json")) if units_dir.exists() else []


def unit_records(data_root) -> list[dict]:
    """Flatten every unit envelope into one row per unit, with its file and source attached.

    Deliberately raw: no predicates, no merging. The variants map and the topic register both
    need to see every unit *individually*, and `select_units` keeps only one representative per
    dedup key — so anything that must reason about the units merged away has to read them here.
    """
    out: list[dict] = []
    for uf in _units_files(data_root):
        data = json.loads(uf.read_text(encoding="utf-8"))
        for u in (data.get("units") or []):
            out.append({
                "units_path": f"_bramber/units/{uf.name}",
                "source": data.get("qname") or uf.stem,
                "extract_path": data.get("extract_path"),
                "unit": u,
            })
    return out


# ---------------------------------------------------------------------------
# ```feed blocks — a meta view declares its own inputs
# ---------------------------------------------------------------------------

def parse_feeds(view_body: str, view_slug: str) -> list[dict]:
    """Read every ```feed block from a `scope: meta` view.md.

    **This is why the block exists at all.** A meta document assembled from CLI flags has its
    definition in somebody's shell history: not versioned, not human-gated, not `view_version`
    stamped, and invisible to the next person. For a source view the selector lives in the
    `view.md` and enjoys all four of those protections. A meta view gets the same deal.

    Same flat `key: value` syntax as ```selector, and the same rule that shaping keys have no
    defaults. A view may declare several feeds — an executive summary reads claims *and* the
    source spine — so each carries a `name` and the results come back keyed by it.
    """
    feeds: list[dict] = []
    raw: dict[str, str] | None = None
    for ln in view_body.splitlines():
        s = ln.strip()
        if raw is None:
            if s.startswith("```") and s[3:].strip().lower() == "feed":
                raw = {}
            continue
        if s.startswith("```"):
            feeds.append(_finish_feed(raw, view_slug, len(feeds)))
            raw = None
            continue
        if not s or s.startswith("#") or ":" not in s:
            continue
        key, _, val = s.partition(":")
        raw[key.strip()] = val.strip()
    if raw is not None:
        raise UnsafeJoin(f"[bramber] meta: view {view_slug!r} has an unclosed ```feed block")
    return feeds


def _finish_feed(raw: dict, view_slug: str, index: int) -> dict:
    join = (raw.get("join") or "").strip().lower()
    if join not in JOIN_MODES:
        raise UnsafeJoin(
            f"[bramber] meta: view {view_slug!r} feed #{index + 1} declares join={join!r}; "
            f"expected one of {JOIN_MODES}. `join` has no default — which feed a document runs "
            f"decides what it is a document *of*, so it is never inferred.")

    render = (raw.get("render") or "").strip().lower() or None
    if render and render not in RENDERERS:
        raise UnsafeJoin(
            f"[bramber] meta: view {view_slug!r} feed #{index + 1} declares render={render!r}; "
            f"expected one of {RENDERERS}. Renderers draw structures the data already contains; "
            f"there is deliberately no general-purpose one, because a diagram whose edges are "
            f"inferred asserts more than the record supports.")

    feed = {
        "name": raw.get("name") or f"{join}-{index + 1}",
        "join": join,
        "render": render,
        "views": [v.strip() for v in (raw.get("views") or "").split(",") if v.strip()] or None,
        "match": {k[len("match."):]: [x.strip() for x in v.split(",") if x.strip()]
                  for k, v in raw.items() if k.startswith("match.") and v.strip()},
    }
    if join == "units":
        missing = [k for k in REQUIRED_UNIT_FEED_KEYS if not raw.get(k)]
        if missing:
            raise UnsafeJoin(
                f"[bramber] meta: view {view_slug!r} feed {feed['name']!r} is missing "
                f"{', '.join(missing)}. These have no defaults on purpose — a default would join "
                f"on whatever field happened to exist and render the result as though it had been "
                f"asked for.")
        feed.update({
            "kind": raw["kind"],
            "dedup_by": raw["dedup_by"],
            "order_by": raw["order_by"],
            "project": [f.strip() for f in raw["project"].split(",") if f.strip()],
        })
    return feed


def run_feeds(data_root, view_slug: str, *, trace=None) -> dict:
    """Run every feed a meta view declares, keyed by feed name.

    Refuses a view that is not `scope: meta` — running meta feeds for a source view would produce
    a document with no home, since compile owns that view's resource and would overwrite it.
    """
    db.configure(root=data_root)
    view_md = db.VIEWS_DIR / view_slug / "view.md"
    if not view_md.exists():
        raise UnsafeJoin(f"[bramber] meta: no view.md for view {view_slug!r} (looked at {view_md})")

    fields, _, body = db.split_frontmatter(view_md.read_text(encoding="utf-8"))
    if _compile.view_scope(fields) != "meta":
        raise UnsafeJoin(
            f"[bramber] meta: view {view_slug!r} is not `scope: meta` — its resource is compiled "
            f"from the store by `bramber compile`, and running meta feeds into it would produce "
            f"a document compile then overwrites.")

    feeds = parse_feeds(body, view_slug)
    if not feeds:
        raise UnsafeJoin(
            f"[bramber] meta: view {view_slug!r} declares no ```feed block, so there is nothing "
            f"deterministic to build the document from. Add one — its definition belongs in the "
            f"view.md where it is versioned and human-gated, not in a command line.")

    out = {"view_slug": view_slug,
           "view_name": fields.get("name") or fields.get("title") or view_slug,
           "view_version": fields.get("view_version"), "feeds": {}}
    for f in feeds:
        if f["join"] == "sources":
            result = source_spine(data_root, views=f["views"], trace=trace)
        elif f["join"] == "topics":
            result = topic_register(data_root, match=f["match"] or None)
        elif f["join"] == "contradictions":
            result = contradiction_register(data_root, trace=trace)
        elif f["join"] == "per-view":
            result = selections_by_view(data_root, views=f["views"], trace=trace)
        else:
            result = select_across(
                data_root, kind=f["kind"], dedup_by=f["dedup_by"], order_by=f["order_by"],
                project=f["project"], match=f["match"] or None, trace=trace)

        if f["render"] == "coverage":
            result["rendering"] = coverage_table(result)
        elif f["render"] == "divergence":
            result["rendering"] = mermaid_divergence(result)
        elif f["render"] == "contradictions":
            result["rendering"] = contradiction_graph(result)
        out["feeds"][f["name"]] = result
    return out


# ---------------------------------------------------------------------------
# feed 1: the source spine
# ---------------------------------------------------------------------------

def source_spine(data_root, *, views: Optional[Iterable[str]] = None, trace=None) -> dict:
    """Every source, and what each view made of it. Grouped by `extract_path`.

    **This is now derived from the selectors, not from a stamp.** Before the redesign a unit
    carried the view it had been extracted for, and the spine simply read that field. Units are
    view-agnostic now, so the only honest way to say what a view made of a source is to run that
    view's selector and see which sources the selected units cite. That is strictly better
    evidence: it reflects the rule the view actually applies today, and it moves when the view is
    edited, which an extraction-time stamp never did.

    It is what an executive summary, a scope description and a coverage report all run on, and it
    is the only honest way to answer "which sources did this programme actually read, and which
    views found nothing in them" — a question no per-view compile can answer about itself.

    Sources with no units at all still appear, with an empty `views` map. A source nothing
    selected is a finding, and dropping it would report a cleaner corpus than the one on disk.
    """
    scope = _source_views(data_root, views)

    spine: dict[str, dict] = {}
    for uf in _units_files(data_root):
        data = json.loads(uf.read_text(encoding="utf-8"))
        ep = data.get("extract_path")
        if not ep:
            continue
        spine[ep] = {
            "extract_path": ep,
            "source": data.get("qname") or uf.stem,
            "unit_count": len(data.get("units") or []),
            "views": {},
        }

    for slug in scope:
        sel = _compile.selection_for_view(data_root, slug, trace=trace)
        for entry in sel["units"]:
            kind = (entry.get("unit") or {}).get("kind") or "?"
            for a in entry.get("source_artifacts") or []:
                target = spine.get(a.get("extract_path"))
                if target is None:
                    continue
                per_view = target["views"].setdefault(slug, {"units": 0, "kinds": {}})
                per_view["units"] += 1
                per_view["kinds"][kind] = per_view["kinds"].get(kind, 0) + 1

    return {
        "count": len(spine),
        # Carried explicitly so a view that selected nothing ANYWHERE still gets a column in the
        # coverage table. Deriving the column set from the cells would silently drop exactly the
        # view whose emptiness is the most interesting cell on the page.
        "views": scope,
        "sources": [spine[k] for k in sorted(spine)],
    }


# ---------------------------------------------------------------------------
# feed 2: select over the whole store, keeping variants
# ---------------------------------------------------------------------------

def select_across(data_root, *, kind: str, dedup_by: str, order_by: str, project: list[str],
                  match: Optional[dict] = None, views: Optional[Iterable[str]] = None,
                  trace=None) -> dict:
    """Select units over the whole store on a payload key, merging into one entry per key.

    Returns the merged entries **plus a `variants` map**: what each source separately said about
    the same key. `select_units` keeps a single representative — first-seen wins, in filename
    order, which is the precedence defect `specs/07 §2` already names — and for a glossary that
    is fatal, because it would show one source's gloss and silently drop the rest.

    **`divergent` means "the sources phrase `project[0]` differently", not "the sources
    disagree".** The caller chooses what counts as divergence by choosing which field leads. For
    terms, leading with `gloss` is exactly right: two incompatible definitions of one word is the
    finding. For entities it is noisy — two sources describing the same vendor in different words
    trip it — so an entity register that cares about disagreement should lead with `role` or
    `stance` and treat `gloss` as description. The flag is a mechanical signal for a human or an
    agent to adjudicate; it is deliberately not a claim that a conflict exists.

    `views` is accepted and ignored for feed-shape symmetry: the store is not partitioned by view,
    so there is nothing for it to filter. Passing it is not an error, but it changes nothing.
    """
    trace = trace or _trace.NULL_TRACE
    db.configure(root=data_root)

    sel = {
        "kind": kind,
        "match": {k: set(v) for k, v in (match or {}).items()},
        "dedup_by": dedup_by,
        "order_by": order_by,
        "project": list(project),
        "section": "Projected units",
        "load_when": None,
        "description": None,
    }

    records = unit_records(data_root)

    with trace.step("meta select", "Select across every source in the shared store, keeping "
                                   "each source's own phrasing alongside the merged entry.") as st:
        st.inputs["join"] = f"units on {dedup_by!r}"
        st.inputs["units considered"] = len(records)
        # `variants` and `divergent` come from `select_units` itself now. They used to be
        # recomputed here in a second pass over the same units, which needed a consistency check
        # to catch the two disagreeing — one pass cannot disagree with itself, so both the second
        # pass and the check are gone. It also means every view gets divergence detection, not
        # only the meta layer that happened to ask for it.
        entries = _compile.select_units(_units_files(data_root), sel, trace=trace)
        for e in entries:
            e["sources"] = sorted({v["source"] for v in e["variants"]})

        st.outputs["entries"] = len(entries)
        st.outputs["spanning >1 source"] = sum(1 for e in entries if len(e["sources"]) > 1)
        st.outputs["divergent"] = sum(1 for e in entries if e["divergent"])

    verify_join(entries)
    return {
        "join": "units",
        "dedup_by": dedup_by,
        "count": len(entries),
        "divergent": sum(1 for e in entries if e["divergent"]),
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# feed 3: the topic register
# ---------------------------------------------------------------------------

def topic_register(data_root, *, match: Optional[dict] = None) -> dict:
    """Every topic tag in the corpus, and the units carrying it.

    Costs nothing new. `payload.topics` is on every unit kind the scan produces and **nothing
    downstream aggregates it** — a view can select on it and project it, and no register has ever
    been built. This is the cheapest exercise of the whole meta path: no new unit kind, no parser
    change, real output.

    **Topics are corpus-wide and merge, which is the opposite of what the per-view predecessor
    did.** Its `questions` tags were declared in each view's `## Projects` prose, which made them
    view-authored vocabulary that could not be merged across views without inventing an overlap.
    `topics` are free tags on a shared store with a stated reuse-before-mint discipline
    (`specs/09` §7), so the same tag IS the same tag. There is no registry enforcing that — the
    cost accepted with the redesign — so a synonym tag splits a topic silently, and that is the
    failure mode to watch here rather than a false merge.
    """
    wanted = {k: set(v) for k, v in (match or {}).items()}
    by_tag: dict[str, dict] = {}

    for rec in unit_records(data_root):
        u = rec["unit"]
        payload = u.get("payload") or {}
        if wanted and any(not _compile._field_matches(payload.get(f), allowed)
                          for f, allowed in wanted.items()):
            continue
        tags = payload.get("topics") or []
        if isinstance(tags, str):
            tags = [tags]
        arts = (u.get("provenance") or {}).get("source_artifacts") or []
        for tag in tags:
            tag = str(tag).strip()
            if not tag:
                continue
            entry = by_tag.setdefault(tag, {"topic": tag, "units": [], "_arts": []})
            entry["units"].append({
                "kind": u.get("kind"),
                "key": payload.get("claim_key") or payload.get("entity_key")
                       or payload.get("term_key") or payload.get("contradiction_key"),
                "statement": payload.get("statement") or payload.get("gloss"),
                "evidence_strength": payload.get("evidence_strength"),
                "recency": payload.get("recency"),
                "source": rec["source"],
            })
            entry["_arts"].extend(arts)

    topics = []
    for tag in sorted(by_tag):
        e = by_tag[tag]
        arts = e.pop("_arts")
        e["support"] = len({a.get("extract_path") for a in arts})
        e["reliability_floor"] = reliability_floor(a.get("reliability_tier") for a in arts)
        e["unit_count"] = len(e["units"])
        e["kinds"] = sorted({str(u["kind"]) for u in e["units"]})
        topics.append(e)

    return {
        "topic_count": len(topics),
        "topics": topics,
        "note": ("Topics are free tags on a shared store with no registry — reuse-before-mint is "
                 "discipline, not a mechanism. A synonym tag splits one topic into two silently; "
                 "that is the failure to watch, not a false merge."),
    }


# ---------------------------------------------------------------------------
# feed 4: the contradiction register
# ---------------------------------------------------------------------------

def contradiction_register(data_root, *, trace=None) -> dict:
    """Every contradiction, merged on its key and counted like any other unit.

    **This merges now, and it did not before.** `CONTRA-001` used to be counted upward by each
    view from its own feed, so two views' `CONTRA-001` shared nothing but the shape and the
    register could only group them, attributed, and leave "are these the same tension?" to the
    agent. Contradiction keys come from the same corpus-wide mint-or-reuse feed as claim keys
    now, so a second source recording a tension already keyed **reuses** that key — an explicit,
    auditable decision — and the merge is exactly as safe as it is for a claim.

    **The sides are unioned across contributors, not taken from the representative.** This is the
    whole reason merging needed care rather than just a dedup key. Each source records the side it
    can see: the minutes assert `CLAIM-001 | recorded as fixed`, the transcript asserts
    `CLAIM-003 | under review`, and they reuse one `CONTRA` key precisely because it is one
    tension. `select_units` keeps one representative unit, so reading `sides` off it reports a
    two-source contradiction with one side — support says two sources attest it and the page shows
    half of it, with the other half sitting on disk. `resolutions` carries every contributor's
    reconciliation for the same reason, and `resolution_divergent` flags the case where they
    disagree — the scalars are then None rather than one source's answer promoted to the corpus's.

    **The merge is only as safe as the feed that publishes the key.** `CONTRA-NNN` is
    agent-assigned, so two sources are talking about one tension only if the second knew the first
    had taken the key. `scan.known_keys` publishes every key-minting section for exactly that
    reason; a kind that merged here while being absent from that feed would let two unrelated
    tensions collapse into one entry reporting support neither source gave.

    A side's `extract_path` is the anchor that makes it checkable, and the compared-with source it
    names is deliberately NOT in `source_artifacts`: it supplies the contrast, it does not assert
    the tension, and folding it in would inflate support.
    """
    sel = {
        "kind": "contradiction",
        "match": {},
        "dedup_by": "contradiction_key",
        "order_by": "contradiction_key",
        "project": ["statement", "resolution", "resolution_status"],
        "section": "Contradictions",
        "load_when": None,
        "description": None,
    }
    entries = _compile.select_units(_units_files(data_root), sel, trace=trace)

    # The additive pass — every contributing unit, not just the representative.
    merged: dict[str, dict] = {}
    for rec in unit_records(data_root):
        u = rec["unit"]
        if u.get("kind") != "contradiction":
            continue
        payload = u.get("payload") or {}
        key = payload.get("contradiction_key")
        if key is None:
            continue
        acc = merged.setdefault(key, {"sides": [], "_seen": set(), "resolutions": [],
                                      "statements": [], "topics": []})
        if payload.get("statement"):
            acc["statements"].append({"source": rec["source"],
                                      "extract_path": rec["extract_path"],
                                      "statement": payload["statement"]})
        for side in payload.get("sides") or []:
            ident = (side.get("ref"), side.get("extract_path"), side.get("position"))
            if ident in acc["_seen"]:
                continue
            acc["_seen"].add(ident)
            acc["sides"].append(side)
        if payload.get("resolution") or payload.get("resolution_status"):
            acc["resolutions"].append({
                "source": rec["source"],
                "extract_path": rec["extract_path"],
                "resolution": payload.get("resolution"),
                "resolution_status": payload.get("resolution_status"),
            })
        for t in payload.get("topics") or []:
            if t not in acc["topics"]:
                acc["topics"].append(t)

    out = []
    for e in entries:
        payload = (e.get("unit") or {}).get("payload") or {}
        acc = merged.get(e["dedup_key"], {})
        resolutions = acc.get("resolutions") or []
        # Compare the two scalars **independently, treating None as absence rather than as a
        # value**. A tuple comparison made a contributor who simply omitted `status` look like one
        # who disagreed about it, so a register whose job is surfacing unreconciled tensions
        # reported a disagreement that did not exist and suppressed a reconciliation both sources
        # had given — with the `resolutions` list beside it carrying two identical strings, which
        # is what disproves the flag.
        divergent = any(len({r[f] for r in resolutions if r[f]}) > 1
                        for f in ("resolution", "resolution_status"))

        # **Every contributor's reconciliation is carried, and a disagreement is reported as one.**
        # Taking the first non-null let filename order decide whether a register said `resolved`
        # or `disputed`, and discarded the loser with no trace — in the one document whose entire
        # job is surfacing unreconciled tensions. When contributors disagree the scalars go None:
        # a reader who only reads them then sees "no reconciliation recorded", which is true and
        # safe, rather than one source's `resolved` presented as the corpus's answer. Picking a
        # winner silently is the one option this module's own reasoning rules out.
        # Per field, not per contributor: one source may carry the resolution and another the
        # status without disagreeing about either.
        agreed = {} if divergent else {
            f: next((r[f] for r in resolutions if r[f]), None)
            for f in ("resolution", "resolution_status")}

        # `statement` is the last field that was read off the representative, and therefore the
        # last one decided by filename order — the precedence defect `specs/07 §2` names and the
        # one this module neutralises everywhere else it merges. Two sources reusing a key are
        # asserting one tension, but they phrase it differently, and the losing framing was
        # vanishing from the output entirely. Same treatment as everything else here: carry them
        # all, flag when they differ, and leave adjudication to the reader.
        statements = acc.get("statements") or []
        statement_divergent = len({s["statement"] for s in statements}) > 1
        out.append({
            "contradiction_key": e["dedup_key"],
            "statement": payload.get("statement"),
            "statements": statements,
            "statement_divergent": statement_divergent,
            "sides": acc.get("sides") or payload.get("sides") or [],
            "resolution": agreed.get("resolution"),
            "resolution_status": agreed.get("resolution_status"),
            "resolutions": resolutions,
            "resolution_divergent": divergent,
            "topics": acc.get("topics") or payload.get("topics") or [],
            "support": e["support"],
            "reliability_floor": e["reliability_floor"],
            "source_artifacts": e["source_artifacts"],
        })

    return {
        "count": len(out),
        "contradictions": out,
        "note": ("Contradiction keys are namespaced and merge like claim keys: a second "
                 "source recording an already-keyed tension reuses the key and raises its "
                 "support. Two entries here are two tensions, not one recorded twice."),
    }


# ---------------------------------------------------------------------------
# the serving primitive: which recorded tensions cite this claim?
# ---------------------------------------------------------------------------

def contradictions_for(data_root, claim_key: str, *, trace=None) -> dict:
    """Every contradiction whose recorded sides cite this exact stored key.
    (`specs/10` §3, as ruled by `specs/11` G6.)

    The product rule this serves: **any surface that returns a claim can also return the
    tensions citing it.** A consumer that reads a claim and is not shown the contradiction
    contesting it has been handed one side of a recorded disagreement — the silent-averaging
    failure every conventional retrieval stack has.

    Resolution is **exact stored-key equality** — never similarity, never a re-point. The merge
    arithmetic is `contradiction_register`'s, reused unchanged, so support counts and
    side-unioning cannot drift from the register. Every served side then carries two flags,
    disjoint on purpose because they want different words to a reader:

        unresolved              the side's key names nothing this corpus minted
        side_witness_mismatch   the key resolves, the side carries a pasted witness, and that
                                witness does not quote the cited claim's minted statement —
                                the key and the witness were copied from different feed rows

    Disjoint, not overlapping: an unresolved side has no minted token to verify against, so
    also calling it a mismatch would state the adjacent thing rather than what happened. And
    nothing is ever dropped or re-pointed — a flag invites a reader; a drop hides a record; a
    re-point infers.

    The witness is verified against the **minter's** statement token (`known_keys` pins the
    statement to the minter's phrasing) — verifying against an endorser's wording would fail
    exactly the corroborations the ledger records. Tokens are read fresh from the store at
    serve time, never from any cache (`specs/11` G2).

    A key nobody cites returns `count: 0`, not an error — absence of tension is an answer.

    **`count: 0` is only an answer when the corpus could have given a different one.** The
    filter above matches on exact stored-key equality, so a tension all of whose sides fail to
    resolve — a scan that wrote bare `CLAIM-007` refs, which the shipped template itself taught
    until 2026-08-10 — matched nothing and was dropped, and a contested claim was served as
    uncontested by the one primitive whose stated purpose is to prevent that. `unattributable`
    is the channel that fixes it: every tension carrying at least one unresolved side, returned
    flagged rather than dropped, because such a side *may* be naming the queried claim and
    nothing in the record can decide. Re-pointing it onto the query would infer; dropping it
    hides. → screen finding S0-1.
    """
    register = contradiction_register(data_root, trace=trace)

    # The one feed: every minted key and its witness token, resolved by the same
    # `resolve_keys` that stamped the store — membership and quotation, nothing inferred.
    minted: set[str] = set()
    token_by_key: dict[str, set] = {}
    for e in _scan.known_keys(data_root):
        minted.add(e["key"])
        if e.get("witness"):
            token_by_key.setdefault(e["key"], set()).add(e["witness"])

    hits, unattributable = [], []
    for entry in register["contradictions"]:
        sides = entry.get("sides") or []
        served = []
        for s in sides:
            side = dict(s)
            side["unresolved"] = s.get("ref") not in minted
            side["side_witness_mismatch"] = bool(
                not side["unresolved"] and s.get("witness")
                and s["witness"] not in token_by_key.get(s["ref"], set()))
            served.append(side)
        if any(s.get("ref") == claim_key for s in sides):
            hits.append({**entry, "sides": served})
        elif not served or any(s["unresolved"] for s in served):
            # The loudness rule applied to the FILTER, not only to the sides inside a hit.
            # A side whose ref names nothing minted could be naming THIS claim — that is
            # precisely what "unresolved" means — so dropping the tension answers "no tension"
            # to a question the record cannot actually answer. It is not re-pointed onto the
            # query either; it is handed back, flagged, for a reader to rule on.
            #
            # `not served` is the same rule one level down, and is NOT redundant: a tension
            # recorded with no `side:` lines (or whose only side had an empty ref, dropped at
            # parse time) has an empty list, over which `any()` is False — so the first version
            # of this fix silently dropped exactly the tensions carrying the LEAST information.
            # An unsided tension cites nothing, which is not the same as citing nothing
            # relevant. → screen finding S0-7.
            unattributable.append({**entry, "sides": served,
                                   "why": ("records no side at all, so nothing connects it to "
                                           "this or any claim — it is in the record and "
                                           "attributable to nothing") if not served else
                                          ("carries a side that resolves to nothing this corpus "
                                           "minted, so it can neither be attributed to this "
                                           "claim nor ruled out as contesting it")})

    return {"claim_key": claim_key, "count": len(hits), "contradictions": hits,
            # Empty on a corpus whose sides all resolve, so this costs a clean corpus nothing.
            # Non-empty means the answer above is INCOMPLETE, not that these are hits.
            # → screen finding S0-1, work/screens/s0-tension-aware-serving-2026-08-10-default.md
            "unattributable_count": len(unattributable),
            "unattributable": unattributable}


# ---------------------------------------------------------------------------
# feed 5: each view's own selection, side by side
# ---------------------------------------------------------------------------

def selections_by_view(data_root, *, views: Optional[Iterable[str]] = None, trace=None) -> dict:
    """Each view's own selection, side by side, keyed by view. **Never summed.**

    This is how an executive summary reads what the views concluded: not "these views agree", but
    "here is what each view, on its own terms, selected". It calls `compile.selection_for_view` —
    the same function `bramber select` and the agent's Mode-2 path use — so the summary cannot
    disagree with the per-view documents about what each view selected.

    **`support_by_view` carries no total, and that is still deliberate.** One of its two original
    reasons is void: the keys are no longer unrelated across views, so a cross-view total is no
    longer meaningless on that ground. The other reason stands and is sufficient — a single
    document read by six views would be counted six times, so a summed "twelve sources agree"
    would be inflated by construction. There is no cross-view total here and there must not be
    one. To count support across the corpus, select over the store (`select_across`), which
    merges provenance on `extract_path` and therefore counts each source once.
    """
    scope = _source_views(data_root, views)

    out = {}
    for slug in scope:
        sel = _compile.selection_for_view(data_root, slug, trace=trace)
        out[slug] = {
            "view_name": sel["view_name"],
            "count": sel["count"],
            "corroborated": sel["corroborated"],
            "units": sel["units"],
        }
    return {
        "views": scope,
        "support_by_view": {slug: out[slug]["count"] for slug in scope},
        "selections": out,
        "note": ("Per view, never summed: one source read by several views would be counted once "
                 "per view. For a corpus-wide count, select over the shared store instead — it "
                 "merges provenance on extract_path and counts each source once."),
    }


# ---------------------------------------------------------------------------
# the verifier
# ---------------------------------------------------------------------------

def verify_join(entries: list[dict]) -> None:
    """Assert the properties that make a merged entry trustworthy. Raises, never warns.

    The properties are taken from the render-resources eval's `verify_join`, which guarded exactly this
    failure for the eval reading surface: a page that merges wrongly fails *silently and
    plausibly*, which is the only kind of failure worth a fatal check.

        P1  every source credited in a merged entry is one that actually contributed a unit for
            that key. A citation to a source with nothing to show is an attribution the merge
            invented.
        P2  the merged entry's representative value is one of the contributing sources' own
            values. If the compiled text matches none of them, the merge produced a statement no
            source made.

    **A third property was retired on 2026-08-07, not weakened.** P3 asserted that no entry merged
    units from two views unless every contributor carried an observed key. It defended the
    per-view key namespace, and there is no longer a per-view key namespace to defend — every key
    in the store is unique across the corpus. An assertion whose precondition cannot occur is not
    a safety net; it is a claim that stops being checked and starts being believed.

    **The properties are shared with `render_resources`; the implementation deliberately is not.**
    That function takes a page structure and *returns* complaints; this one takes merged entries
    and *raises*. They guard different artifacts and are allowed to diverge — what must not
    diverge is the set of properties, which is why they are enumerated here rather than left
    implicit.
    """
    problems: list[str] = []
    for e in entries:
        vs = e.get("variants") or []
        if not vs:
            continue
        key = e["dedup_key"]
        fields = (e.get("unit") or {}).get("payload") or {}

        # P1 — every credited extract must appear among the contributors.
        credited = {a.get("extract_path") for a in e.get("source_artifacts") or []}
        contributing = {v.get("extract_path") for v in vs}
        phantom = credited - contributing
        if phantom:
            problems.append(
                f"{key!r}: credits {sorted(phantom)} but no unit for that key came from "
                f"{'it' if len(phantom) == 1 else 'them'} — the merge invented an attribution")

        # P2 — the representative must be one of the contributors'.
        subject_values = {str(v["fields"].get(f)) for v in vs for f in v["fields"]}
        rep_values = {str(val) for val in fields.values()}
        if rep_values and subject_values and not (rep_values & subject_values):
            problems.append(
                f"{key!r}: the merged representative matches none of its {len(vs)} contributing "
                f"source(s) — the merge produced a value no source gave")

    if problems:
        raise UnsafeJoin("[bramber] meta: join verification failed:\n  " + "\n  ".join(problems))


# ---------------------------------------------------------------------------
# renderings — deterministic, and only of structures the data actually contains
# ---------------------------------------------------------------------------
#
# A diagram asserts structure, and the arrows are the assertion. Drawing a process flow out of
# claims means inferring every arrow, producing an artifact that looks more authoritative than
# prose while carrying no lineage for the thing it actually claims — the failure this system
# exists to prevent, arriving in the form hardest to audit.
#
# So these render only what is already on disk. Every node is a source, a view, a term or a
# contradiction that exists; every edge is a unit or a cited side. Nothing here infers.
#
# They are emitted deterministically rather than described to an agent because transcribing a
# table into a diagram is exactly the task a model does *almost* right, and an almost-right
# diagram is indistinguishable from a right one at a glance.


def _mm_id(prefix: str, value: str) -> str:
    """A Mermaid-safe node id. Mermaid chokes on spaces and punctuation in ids."""
    safe = re.sub(r"[^0-9A-Za-z]+", "_", str(value or "")).strip("_") or "x"
    return f"{prefix}_{safe}"[:60]


def _mm_label(text: str, limit: int = 48) -> str:
    """Quote a label for Mermaid, truncating so one long gloss cannot blow up the layout."""
    s = " ".join(str(text or "").split())
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return '"' + s.replace('"', "'") + '"'


def coverage_table(spine: dict) -> str:
    """Sources × views, as markdown. **Not Mermaid, deliberately.**

    A bipartite graph of twenty sources against six views is up to a hundred and twenty edges —
    technically drawable and unreadable. A table is exact, sorts, and survives being pasted
    anywhere. Mermaid earns its place on the sparse structures below, not this one.

    The `—` cells are the point: a view that read a source and selected nothing from it is a real
    finding, and it is the one thing no per-view document can report about itself.
    """
    sources = spine.get("sources") or []
    # Prefer the declared view list. Deriving columns from the cells drops any view with no cells
    # at all — the view whose emptiness is the single most interesting thing on the page.
    views = list(spine.get("views") or
                 sorted({v for s in sources for v in s["views"] if v is not None}))
    if not sources:
        return "_No sources indexed._"
    if not views:
        return "_No source-scope views on disk._"

    head = "| source | " + " | ".join(views) + " | total |"
    rule = "|---|" + "---|" * (len(views) + 1)
    rows = []
    for s in sources:
        cells = [str(s["views"].get(v, {}).get("units", 0) or "—") for v in views]
        rows.append(f"| `{s['source']}` | " + " | ".join(cells) + f" | {s['unit_count']} |")
    totals = [str(sum(s["views"].get(v, {}).get("units", 0) for s in sources)) for v in views]
    rows.append("| **total** | " + " | ".join(f"**{t}**" for t in totals) +
                f" | **{sum(s['unit_count'] for s in sources)}** |")
    return "\n".join([head, rule, *rows])


def mermaid_divergence(feed: dict) -> str:
    """Keys that more than one source phrases differently, each edge labelled with what that
    source said. Sparse by construction — only divergent entries are drawn."""
    entries = [e for e in (feed.get("entries") or []) if e.get("divergent")]
    if not entries:
        return "%% no divergent entries — every key is phrased the same way by every source"

    lines = ["flowchart LR"]
    for e in entries:
        key = e["dedup_key"]
        kid = _mm_id("t", key)
        lines.append(f'    {kid}[{_mm_label(key)}]:::term')
        seen: set[tuple] = set()
        for v in e.get("variants") or []:
            source = v.get("source") or "(unattributed)"
            subject = next(iter(v.get("fields", {}).values()), "")
            if (source, str(subject)) in seen:
                continue
            seen.add((source, str(subject)))
            sid = _mm_id("s", f"{key}_{source}")
            lines.append(f'    {sid}[{_mm_label(source)}]:::source')
            lines.append(f"    {kid} -- {_mm_label(subject)} --> {sid}")
    lines.append("    classDef term stroke-width:2px")
    lines.append("    classDef source stroke-dasharray:3 3")
    return "\n".join(lines)


def contradiction_graph(register: dict) -> str:
    """Each contradiction and the claims it links, drawn from the merged register.

    Nothing is inferred: every node is a contradiction or a cited side that exists on a unit, and
    every edge is a `side:` the agent wrote. Sides are drawn as-is rather than resolved against
    the claim store, so a side naming a key that was never minted still appears — visibly, which
    is what makes it fixable.
    """
    items = register.get("contradictions") or []
    if not items:
        return ("%% no contradiction units — either none were recorded, or the scans predate "
                "the machine-readable Contradictions block (see each envelope's kinds_absent)")

    lines = ["flowchart TD"]
    for c in items:
        cid = _mm_id("c", c["contradiction_key"])
        lines.append(f'    {cid}{{{_mm_label(c.get("statement"))}}}')
        for side in c.get("sides") or []:
            sid = _mm_id("s", side.get("ref"))
            lines.append(f'    {sid}[{_mm_label(side.get("ref"))}]')
            lines.append(f'    {cid} -- {_mm_label(side.get("position") or "side")} --> {sid}')
    return "\n".join(lines)
