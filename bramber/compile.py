"""bramber compile — project units through a view into a versioned RESOURCE.md.

Canonical spec: `specs/09-view-agnostic-claim-scan.md` §4 (supersedes `specs/07` §3-4's
per-view selection surface; the dedup model is unchanged).

The deterministic baseline of `/bramber:process`: it loads the shared unit store, applies a
view's selection rule, and writes a RESOURCE.md version with lineage back to every contributing
source. No adapter import (the units are already on disk); the domain-blind engine
(`bramber.engine.db`) does the persistence.

**A view is a projection over the shared store — cheap, deterministic, re-runnable.** Extraction
happened once per source (the scan); adding or editing a view touches no source and no scan.
Each `views/<slug>/view.md` carries a machine-readable ```selector block (the executable form of
its prose `## Projects` rule). `compile.py` is a small *predicate engine*: it applies the
predicates the view declares over the units' fields, where both the fields and the values come
from the view. Adding a view is therefore a new `view.md` — no Python change, no re-extraction.

**The predicate vocabulary is domain-neutral.** Arbitrary payload fields are matched through
`match.<field>` — any-of over list-valued fields, exact over scalars — and
`dedup_by`/`order_by`/`project` have **no defaults**, so a view that forgets one **fails
loudly** instead of compiling something empty.

**Dedup is two operations, not one** (specs/07 §3.3) — this is the file's whole reason for
existing:

  - *Within a source*: collapse repeated claims to one unit. That happens upstream, in
    `bramber.scan`, at materialization. It is the length-bias fix: an insistent stakeholder
    restating a position five times contributes one unit, not five.
  - *Across sources*: **do not collapse.** Merge the provenance and count the sources. That
    happens here, because selection is the only place units from every source meet.

"Five sources each said it once" versus "one source said it five times" was invisible at every
layer of this system, and it is the difference between signal and volume.
"""

from __future__ import annotations

import json
from pathlib import Path

from bramber import trace as _trace
from bramber.adapter import reliability_floor
from bramber.engine import db


# ---------------------------------------------------------------------------
# the selector — view.md's ```selector block, parsed into predicates
# ---------------------------------------------------------------------------

# A view's `scope:` frontmatter. Two kinds of view, and the difference is what they read.
#
#   source  the default and everything shipped so far — its sources are DOCUMENTS, scanned into
#           the shared unit store and selected from here.
#   meta    its sources are the UNITS themselves, read ACROSS the whole store rather than through
#           one view's selector. An executive summary, a contradiction register, a glossary. It
#           has no selector of its own, so compiling it would write an empty resource.
#
# Marking it costs one frontmatter key and **no engine change**. A meta document is otherwise an
# ordinary view with an ordinary resource: `views/<slug>/resources/<rslug>/`, written by
# `write_resource_version`, versioned and lineage-tracked and MCP-served like any other. The
# alternative — a nullable `resources.view_id` plus a scope column — would touch schema.sql,
# SCHEMA_VERSION, four db functions and the URI parser, to buy nothing this does not.
#
# `bramber/engine/` never reads this key. `db._sync_views` is untouched; the engine learns nothing.
VIEW_SCOPES = ("source", "meta")
DEFAULT_VIEW_SCOPE = "source"

REQUIRED_SELECTOR_KEYS = ("dedup_by", "order_by", "project")


def parse_selector(view_body: str, view_slug: str) -> dict:
    """Extract and normalize the ```selector block from a view.md body.

    The block is a flat `key: value` list, fenced as ```` ```selector ````.

    Selection predicates — a unit is selected iff *all* present predicates match:
      - `kind`            unit.kind equals this string
      - `match.<field>`   unit.payload.<field> matches these (comma-separated). A scalar field
                          matches on equality; a list-valued field (e.g. `topics`) matches if
                          ANY of its values is allowed.

    Shaping keys — **all three are required**, deliberately with no defaults:
      - `dedup_by`        payload field used as the dedup + lineage-contribution key
      - `order_by`        payload field to sort on
      - `project`         payload fields to render, in order; the first is the bullet's subject

    Optional presentation:
      - `section`         the RESOURCE.md section heading
      - `load_when`       the "Load this resource when:" gloss
      - `description`     the resource description

    The three required keys used to default to one domain's field names. A view over any other
    unit shape then silently produced blank bullets — a wrong document with a green build.
    Erroring is strictly better than rendering nothing.
    """
    raw: dict[str, str] = {}
    found = False
    inside = False
    for ln in view_body.splitlines():
        s = ln.strip()
        if not inside:
            if s.startswith("```") and s[3:].strip().lower() == "selector":
                inside, found = True, True
            continue
        if s.startswith("```"):
            break
        if not s or s.startswith("#") or ":" not in s:
            continue
        key, _, val = s.partition(":")
        raw[key.strip()] = val.strip()

    if not found:
        raise SystemExit(
            f"[bramber] compile: view {view_slug!r} has no ```selector block in its view.md. "
            f"Add one so the deterministic baseline knows what to project, or use the "
            f"agent-authored /bramber:process path."
        )

    missing = [k for k in REQUIRED_SELECTOR_KEYS if not raw.get(k)]
    if missing:
        raise SystemExit(
            f"[bramber] compile: view {view_slug!r} selector is missing required key(s): "
            f"{', '.join(missing)}. These have no defaults on purpose — a default would render "
            f"blank bullets for any unit shape that does not happen to carry that field."
        )

    def _list(key):
        v = raw.get(key)
        return [x.strip() for x in v.split(",") if x.strip()] if v else []

    # `match.<field>` — the generic payload predicate. One mechanism, no domain knowledge:
    # the field names and allowed values both come from the view.
    match = {k[len("match."):]: {x.strip() for x in v.split(",") if x.strip()}
             for k, v in raw.items() if k.startswith("match.") and v.strip()}

    return {
        "kind": raw.get("kind") or None,
        "match": match,
        "dedup_by": raw["dedup_by"].strip(),
        "order_by": raw["order_by"].strip(),
        "project": _list("project"),
        "section": raw.get("section") or "Projected units",
        "load_when": raw.get("load_when") or None,
        "description": raw.get("description") or None,
    }


def jsonable_selector(sel: dict) -> dict:
    """The selector in a form the trace can record — sets sorted into lists, **recursively**.

    Recursion is the whole point. `match` is a dict *of* sets, so a one-level normalizer
    (`sorted(v) if isinstance(v, set) else v`) reaches the top-level predicates and leaves the
    nested ones raw. They then serialize as a Python repr in set-iteration order: unreadable,
    non-deterministic between runs, and wrong in exactly the field whose job is to show the rule
    the run obeyed.

    That is the same defect shape as the NULL-url and NULL-lineage bugs — a generalization moved
    a value one level deeper than the code handling it, and nothing was looking at that level.
    """
    def norm(v):
        if isinstance(v, set):
            return sorted(v)
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        return v
    return {k: norm(v) for k, v in sel.items()}


def _field_matches(value, allowed: set) -> bool:
    """Does a payload field satisfy a `match.<field>` predicate?

    A list-valued field matches if ANY of its values is allowed — `topics: [a, b]` passes
    `match.topics: a`. A scalar matches on string equality. The old scalar-only rule stringified
    a list wholesale (`str(['a']) != 'a'`), so a list-valued field could never match anything —
    silently, which is the blank-bullet failure one field-type deeper.
    """
    if isinstance(value, (list, tuple)):
        return any(str(v) in allowed for v in value)
    return str(value) in allowed


def _reject_reason(u: dict, sel: dict) -> str | None:
    """Which selector predicate excludes this unit, or None if it passes them all.

    The predicate chain as a *value* rather than as control flow: the caller gets the reason back
    instead of discarding it at a `continue`. That is what lets `--trace` answer "why is this
    claim not in my resource?" without a second implementation of the rule — the audit reason and
    the selection decision are the same computation, so they cannot drift.
    """
    payload = u.get("payload", {})
    if sel["kind"] and u.get("kind") != sel["kind"]:
        return f"kind is {u.get('kind')!r}, view selects {sel['kind']!r}"
    for fieldname, allowed in sel["match"].items():
        if not _field_matches(payload.get(fieldname), allowed):
            return (f"{fieldname} is {payload.get(fieldname)!r}, "
                    f"view selects {sorted(allowed)}")
    return None


def view_scope(fields: dict) -> str:
    """A view's scope from its frontmatter, defaulting to `source`.

    Unknown values fall back to the default rather than raising: an unrecognised scope on a
    document-reading view is a typo, and refusing to compile a working view over a misspelt
    frontmatter key would be a worse failure than ignoring it. The `meta` value is the only one
    that changes behaviour, and it has to be spelled right to do so.
    """
    value = str(fields.get("scope", "") or "").strip().lower()
    return value if value in VIEW_SCOPES else DEFAULT_VIEW_SCOPE


def _artifacts(u: dict) -> list:
    """A unit's provenance entries, always as a list of at least one (specs/08 §4.2)."""
    arts = (u.get("provenance") or {}).get("source_artifacts")
    return list(arts) if isinstance(arts, list) else []


def select_units(units_files: list[Path], sel: dict, *, trace=None) -> list[dict]:
    """Apply the selector's predicates over every unit, merge across sources, and order.

    This is the one selection pass; both the deterministic baseline (via `_project`) and the
    agent-authored path (`selection_for_view` / `bramber select`) consume it, so "what does this
    view project" lives in exactly one place.

    Each entry carries the representative `unit` (full payload), the merged `source_artifacts`,
    a `variants` list holding what **every** contributing source said (so a merged entry never
    silently discards the other sources' wording), a `divergent` flag when those wordings differ,
    and the two derived scalars that answer genuinely different questions and aggregate in
    opposite directions:

        support = number of distinct sources asserting it   (count — how well attested?)
        floor   = min(reliability_tier) over those sources  (weakest link — how much may I claim?)

    A claim backed by five sources of which one is weak is well-attested and weakly-floored at
    once; reporting only one of those numbers hides half the picture.

    With `trace` set, every unit *considered* gets a row — kept, merged, or rejected with the
    predicate that killed it. That is the whole audit surface of a view.
    """
    trace = trace or _trace.NULL_TRACE
    dedup_by, order_by = sel["dedup_by"], sel["order_by"]
    step = trace.step("select", "Apply the view's selector predicates to every unit in the "
                                "shared store, then merge duplicates ACROSS sources into one "
                                "unit with a support count — never collapsing them away.")
    step.inputs["selector (from view.md)"] = jsonable_selector(sel)
    step.inputs["units on disk"] = f"{len(units_files)} source file(s) in _bramber/units/"

    considered = 0
    selected: dict[str, dict] = {}
    for uf in units_files:
        data = json.loads(uf.read_text(encoding="utf-8"))
        units_path = f"_bramber/units/{uf.name}"

        # One group per source: every unit it produced is listed under it, kept or not, so a
        # reader sees the whole fate of a source without filtering for it.
        source = data.get("qname") or uf.stem
        # `units` is `null` + a stated `units_absent_reason` when nothing was produced, or `[]`
        # in envelopes written before that distinction existed. `or []` normalizes both; the
        # loop below iterates it, so a bare `.get("units", [])` would raise on the current shape.
        units = data.get("units") or []
        step.group(source, extract=data.get("extract_path"), units_file=units_path,
                   produced=len(units))
        if not units:
            step.row("empty", source, group=source,
                     reason=data.get("units_absent_reason")
                            or "no units from this source — it is still registered as "
                               "considered, but projects nothing into any view")

        for u in units:
            considered += 1
            payload = u.get("payload", {})
            ref = payload.get(dedup_by) or source
            tag = u.get("kind") or ""

            reason = _reject_reason(u, sel)
            if reason:
                step.row("rejected", ref, tag=tag, group=source, reason=reason, data=u)
                continue

            dedup_key = payload.get(dedup_by)
            if dedup_key is None:
                step.row("rejected", ref, tag=tag, group=source,
                         reason=f"no dedup key: unit has no {dedup_by!r}", data=u)
                continue

            arts = _artifacts(u)
            # What THIS source said, kept alongside the merged entry. The merge below keeps one
            # representative unit and merges only the provenance, so without this the compiled
            # entry shows whichever wording sorted first by filename and every other source's
            # phrasing is gone from the output — while its citation is still counted. The count
            # stays right and the words silently do not, which is the harder error to notice.
            #
            # Recorded in the same pass as the merge, deliberately. `meta.select_across` used to
            # compute this in a second pass over the same units and needed a consistency check to
            # catch the two disagreeing; one pass cannot disagree with itself.
            variant = {
                "source": source,
                "extract_path": data.get("extract_path"),
                "fields": {f: payload.get(f) for f in sel["project"]},
            }
            if dedup_key in selected:
                # ACROSS sources: merge, do not drop. This is the corroboration signal the
                # engine used to delete — first-wins dedup linked a unit to exactly one source
                # by construction, even when it legitimately appeared in five.
                entry = selected[dedup_key]
                entry["variants"].append(variant)
                known = {a.get("extract_path") for a in entry["source_artifacts"]}
                added = [a for a in arts if a.get("extract_path") not in known]
                entry["source_artifacts"].extend(added)
                step.row("corroborated" if added else "deduped", ref, tag=tag, group=source,
                         reason=(f"{dedup_by}={dedup_key!r} was already selected; this source "
                                 f"also asserts it — support is now "
                                 f"{len(entry['source_artifacts'])}")
                                if added else
                                (f"{dedup_by}={dedup_key!r} already selected from this same "
                                 f"source — it projects once"),
                         data=u)
                continue

            selected[dedup_key] = {
                "dedup_key": dedup_key,
                "order_value": payload.get(order_by, ""),
                "unit": u,
                "source_artifacts": list(arts),
                "units_path": units_path,
                "variants": [variant],
            }
            step.row("selected", ref, tag=tag, group=source,
                     detail=str(payload.get(sel["project"][0], "")) or "projects into this view",
                     data=u)

    ordered = [selected[k] for k in
               sorted(selected, key=lambda k: (str(selected[k]["order_value"]), str(k)))]
    subject = sel["project"][0] if sel["project"] else None
    for e in ordered:
        e["support"] = len({a.get("extract_path") for a in e["source_artifacts"]})
        e["reliability_floor"] = reliability_floor(
            a.get("reliability_tier") for a in e["source_artifacts"])
        # **`divergent` means DIFFERENT SOURCES phrase `project[0]` differently, not that they
        # disagree.** The caller chooses what counts by choosing which field leads: for a
        # glossary, leading with `gloss` makes two incompatible definitions of one word the
        # finding; for claims it flags that corroborating sources worded one assertion
        # differently, which is usually benign and occasionally the whole story. It is a
        # mechanical signal for a human or an agent to adjudicate, never a claim that a conflict
        # exists.
        #
        # More than one *source* is required, not merely more than one wording. One source
        # phrasing something two ways is within-source variation — the thing collapse already
        # handles — and reporting it as divergence produced the nonsense pairing `divergent: True`
        # with `support: 1`, which invites a reader to look for a disagreement between sources
        # when only one source is present.
        wordings = {str(v["fields"].get(subject)) for v in e["variants"]} if subject else set()
        contributors = {v.get("extract_path") for v in e["variants"]}
        e["divergent"] = len(wordings) > 1 and len(contributors) > 1

    step.outputs["considered"] = considered
    step.outputs["selected"] = len(ordered)
    step.outputs["divergent (sources word it differently)"] = sum(
        1 for e in ordered if e["divergent"])
    step.outputs["dropped"] = considered - sum(len(e["source_artifacts"]) for e in ordered)
    step.outputs["corroborated (support > 1)"] = sum(1 for e in ordered if e["support"] > 1)
    step.outputs["ordering"] = f"by {order_by}, deduped on {dedup_by}"
    step.close()
    return ordered


def _project(selected: list[dict]) -> list[dict]:
    """Trim full selected units into the flat fields the deterministic render + lineage use.

    Which payload fields survive is declared by the view (`project`), not hardcoded here — a
    hardcoded field list is the silent-blank-bullet failure `specs/07 §4` exists to remove.
    """
    out = []
    for s in selected:
        payload = s["unit"].get("payload", {})
        out.append({
            "dedup_key": s["dedup_key"],
            "fields": {f: payload.get(f) for f in s["_project_fields"]},
            "support": s["support"],
            "reliability_floor": s["reliability_floor"],
            "source_artifacts": s["source_artifacts"],
            "units_path": s["units_path"],
        })
    return out


def _select(units_files: list[Path], sel: dict) -> list[dict]:
    """Back-compat projection accessor: the trimmed bullets the deterministic render uses."""
    selected = select_units(units_files, sel)
    for s in selected:
        s["_project_fields"] = sel["project"]
    return _project(selected)


def _resolve(data_root, view_slug, *, trace=None):
    """Pure read (no DB write): configure paths, read the view.md, parse its selector, and
    select the full units. Shared by `compile_view` and `selection_for_view`."""
    trace = trace or _trace.NULL_TRACE
    db.configure(root=data_root)
    view_md = db.VIEWS_DIR / view_slug / "view.md"
    if not view_md.exists():
        raise SystemExit(f"[bramber] no view.md for view {view_slug!r} (looked at {view_md})")

    with trace.step("read view", "Load the human-authored view.md and parse its selector "
                                 "block — the rule the rest of the run obeys.") as st:
        raw = view_md.read_text(encoding="utf-8")
        fields, _, body = db.split_frontmatter(raw)
        if view_scope(fields) == "meta":
            raise SystemExit(
                f"[bramber] compile: view {view_slug!r} is `scope: meta` — it reads the unit "
                f"store as a whole rather than through a selector of its own, so compiling it "
                f"would write an empty resource that looks like a real one. Build its feed with "
                f"`bramber meta-select`, then author the document from that.")
        view_name = fields.get("name") or fields.get("title") or view_slug
        sel = parse_selector(body, view_slug)
        st.inputs["view.md"] = str(view_md)
        st.inputs["frontmatter"] = fields
        st.outputs["view name"] = view_name
        st.outputs["parsed selector"] = jsonable_selector(sel)
        st.note("Predicates are ANDed; an absent predicate is not applied.")

    units_dir = db.ROOT / "_bramber" / "units"
    files = sorted(units_dir.glob("*.json")) if units_dir.exists() else []
    selected = select_units(files, sel, trace=trace)
    for s in selected:
        s["_project_fields"] = sel["project"]
    return view_name, sel, selected


def selection_for_view(data_root, view_slug, *, trace=None) -> dict:
    """The agent-authored path's input (`bramber select` / Mode 2 of /bramber:process): the exact
    full units a view projects, JSON-able. The agent reads these + the view Thesis and writes
    prose — it does NOT re-derive selection, so the baseline and the agent always agree on the
    set."""
    view_name, sel, selected = _resolve(data_root, view_slug, trace=trace)
    return {
        "view_slug": view_slug,
        "view_name": view_name,
        "section": sel["section"],
        "count": len(selected),
        "corroborated": sum(1 for s in selected if s["support"] > 1),
        "units": [{k: v for k, v in s.items() if k != "_project_fields"} for s in selected],
    }


# ---------------------------------------------------------------------------
# render — a deterministic RESOURCE.md body (no date/version embedded, so the
# sha is stable and an unchanged re-compile mints no new version)
# ---------------------------------------------------------------------------

def _bullet(item: dict, project_fields: list) -> str:
    """One projected unit as one bullet, from declared fields only.

    First projected field is the subject; the rest render as `name: value` metadata; support and
    floor close it. Nothing here knows what any field *means*, which is the point.
    """
    fields = item["fields"]
    subject = str(fields.get(project_fields[0], "") or "").strip() or item["dedup_key"]
    rest = [f"{f}: {fields[f]}" for f in project_fields[1:]
            if fields.get(f) not in (None, "", [])]
    line = f"- **{subject}**"
    if rest:
        line += " — " + " · ".join(rest)
    attest = f"{item['support']} source" + ("s" if item["support"] != 1 else "")
    if item.get("reliability_floor"):
        attest += f" · floor: {item['reliability_floor']}"
    return f"{line}  _({attest})_"


def _render(view_slug: str, view_name: str, resource_slug: str, sel: dict,
            items: list[dict]) -> str:
    load_when = sel["load_when"] or f"you need the {view_name.lower()} reading of these sources"
    description = sel["description"] or f"The {view_name} view of these sources."
    # `source_count` is contributing SOURCES, per FORMAT-SPEC — counted across every unit's
    # merged provenance, so a unit asserted by three sources contributes all three.
    source_count = len({a.get("extract_path") for i in items for a in i["source_artifacts"]})
    floor = reliability_floor(
        a.get("reliability_tier") for i in items for a in i["source_artifacts"])
    lines = [
        "---",
        f"name: {resource_slug}",
        f"title: {view_name}",
        f'description: "{description}"',
        f"view: {view_slug}",
        f"source_count: {source_count}",
    ]
    if floor:
        # Computed from the inputs BEFORE any prose exists, so a synthesis step can never
        # re-score its own floor (specs/08 §4.1 rule 3).
        lines.append(f"reliability_floor: {floor}")
    lines += [
        "maintainer: agent",
        "---",
        "",
        f"# {view_name}",
        "",
        f"**Load this resource when:** {load_when}.",
        "",
        f"## {sel['section']}",
    ]
    if not items:
        lines.append("_No units were selected for this view._")
    for item in items:
        lines.append(_bullet(item, sel["project"]))
    return "\n".join(lines) + "\n"


def compile_view(data_root, view_slug, *, resource_slug="overview", trace=None) -> dict:
    """Load the shared `_bramber/units/*.json` store, apply the view's selector, write a
    RESOURCE.md version with lineage. Returns the `db.write_resource_version` result.

    Syncs from disk first so (a) the view row exists (write_resource_version requires it) and
    (b) the extracts are indexed as sources — `db._link_source` keys lineage on `extract_path`,
    so a source must be synced before it can be linked.
    """
    trace = trace or _trace.NULL_TRACE
    db.configure(root=data_root)

    with trace.step("sync", "Reconstruct the index from disk, so the view row exists and "
                            "extracts are indexed as sources for lineage to link against.") as st:
        counts = db.sync_from_disk()
        st.inputs["root"] = str(db.ROOT)
        st.outputs["index row counts"] = counts

    view_name, sel, selected = _resolve(data_root, view_slug, trace=trace)
    items = _project(selected)

    with trace.step("render", "Project each selected unit to one bullet and render the "
                              "RESOURCE.md body (deterministic: no date or version in the "
                              "content, so an unchanged recompile mints no version).") as st:
        content = _render(view_slug, view_name, resource_slug, sel, items)
        # One lineage row per (unit × contributing source). A unit asserted by three sources
        # writes three rows — that is the corroboration record, and it is only expressible
        # because provenance is a list.
        sources = [
            {"extract": a.get("extract_path"),
             "scan": a.get("scan_path") or i["units_path"],
             # The key selection actually deduped on, never a fixed field name: `dedup_by` is
             # configurable per view, so a hardcoded key wrote NULL contributions on every
             # lineage row of any view that set its own (specs/07 §5.1).
             "contribution": i["dedup_key"]}
            for i in items for a in i["source_artifacts"]
        ]
        st.inputs["section heading"] = sel["section"]
        st.inputs["bullets to render"] = len(items)
        st.outputs["content_sha"] = db.sha256(content)
        st.outputs["lineage rows"] = len(sources)
        st.outputs["RESOURCE.md"] = _trace.clip(content)
        for i in items:
            st.row("ok", str(i["fields"].get(sel["project"][0], i["dedup_key"])),
                   detail=f"→ bullet; {i['support']} contributing source(s)", data=i)

    with trace.step("write version", "Mint an immutable version + lineage, or no-op if the "
                                     "content sha is unchanged.") as st:
        res = db.write_resource_version(
            view_slug,
            resource_slug,
            title=view_name,
            content=content,
            change_summary="initial compile",
            sources=sources,
            description=sel["description"] or f"The {view_name} view of these sources.",
        )
        st.inputs["resource"] = f"bramber://{view_slug}/{resource_slug}"
        st.inputs["lineage links to write"] = len(sources)
        st.outputs["result"] = res
        if res.get("created"):
            st.row("created", f"{view_slug}/{resource_slug} v{res['version_num']}",
                   detail=f"snapshot: views/{view_slug}/resources/{resource_slug}"
                          f"/versions/{res['version_num']}.md")
        else:
            st.row("unchanged", f"{view_slug}/{resource_slug} v{res['version_num']}",
                   reason="content sha matches the current version — no version minted")

    return res
