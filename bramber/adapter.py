"""bramber Adapter contract — the one seam a domain implements.

Canonical spec: specs/00-normalize-adapter-contract.md, as amended by
specs/09-view-agnostic-claim-scan.md (units are view-agnostic; the per-view
extraction scope was withdrawn 2026-08-07).

bramber owns integrate + serve (domain-blind). An Adapter owns normalize + extract
(domain-specific). Two hard rules define the seam:
  1. bramber never parses a source.
  2. the Adapter never writes bramber.db / resource files / the MCP surface.

An Adapter produces Extract + Unit objects and source identities at *ingest* time;
bramber persists them. The engine never imports an Adapter (so `--sync`, run by the
Stop hook every turn, stays stdlib-only and fast): adapters materialize extracts to
disk with the generalized header that db.py parses.

**Units are per-source, never per-view.** A unit is extracted once, from the source
alone, and every view downstream *selects* over the shared store — no view ever
re-derives extraction. For text the extraction is interpretive and happens in a
second pass (the agent's scan, `bramber materialize`), so `TextAdapter.extract_units`
returning nothing is a correct answer, not a stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceIdentity:
    """Opaque, comparable, serializable. The staleness anchor (spec 00 §6)."""
    kind: str                       # "content_sha" | ... (pluggable per domain)
    key: str                        # stable dedupe hash
    data: dict = field(default_factory=dict)   # structured identity, adapter-defined


@dataclass
class Source:
    """A raw input. `ref` is an adapter-private handle (file path, symbol qname, URL)."""
    source_type: str
    title: Optional[str] = None
    url: Optional[str] = None
    author: Optional[str] = None
    date_published: Optional[str] = None
    ref: Optional[str] = None


@dataclass
class Extract:
    """Normalized, view-agnostic representation of a source. Materialized to disk."""
    source: Source
    identity: SourceIdentity
    body: str
    extract_path: Optional[str] = None


@dataclass
class Unit:
    """The atomic finding. Text: a claim, read out of a scan. View-agnostic by contract.

    **`provenance["source_artifacts"]` is a list, minimum length one** (specs/08 §4.2). This is
    the shape that makes corroboration expressible without a schema break: a claim asserted by
    five sources is ONE unit with five provenance entries — not five units, and not one unit
    that quietly forgot the other four. Two different scalars fall out of it and both are
    wanted, because they aggregate in opposite directions:

        support = len(source_artifacts)          "how well attested is this?"   (count)
        floor   = min(reliability_tier)          "how much may I claim?"        (weakest link)

    A claim backed by five sources of which one is weak is **well-attested and weakly-floored at
    the same time**, and reporting only one of those numbers hides half the picture.

    Each entry: {extract_path, scan_path, reliability_tier}.
    """
    kind: str                       # "claim" | ...
    payload: dict
    provenance: dict = field(default_factory=dict)


# The reliability tiers, weakest -> strongest. The ORDER IS the precedence table (specs/08 §4.1).
#
# Deliberately a small enum and never a float: aggregation is `min()`, which is total,
# deterministic and explainable, with no threshold to tune. A float invites averaging, and
# averaging is how a weak claim gets laundered into a strong one.
#
# Orthogonal to the scan's `evidence_strength`, and both exist on purpose. The tier asks
# *what is this source's relationship to the fact* (provenance; assigned mechanically by source
# class). `evidence_strength` asks *how strong is this claim inside the source* (content;
# assigned interpretively). Collapsing them would merge two different questions into one
# unusable number.
RELIABILITY_TIERS = ("derived", "reported", "authoritative")


def reliability_floor(tiers) -> Optional[str]:
    """The weakest tier present — what bounds any claim built on these units.

    A strong unit never lifts a weak co-cited one: one `reported` unit caps the document at
    `reported` however many `authoritative` units sit beside it.
    """
    ranked = [t for t in tiers if t in RELIABILITY_TIERS]
    if not ranked:
        return None
    return min(ranked, key=RELIABILITY_TIERS.index)


@runtime_checkable
class Adapter(Protocol):
    """A domain plugs into bramber by implementing this. See the reference adapters."""

    domain: str

    def discover_sources(self, root: str) -> Iterable[Source]:
        """Enumerate sources under a project root (files, URLs, records)."""
        ...

    def identity(self, source: Source) -> SourceIdentity:
        """Compute the source's identity — content_sha for text. bramber stores it; diffs
        drive staleness."""
        ...

    def normalize(self, source: Source) -> Extract:
        """Raw source -> view-agnostic Extract. Runs once per source, at ingest time."""
        ...

    def extract_units(self, extract: Extract) -> list[Unit]:
        """Produce units at ingest time, from the source alone — never per view. A domain
        whose extraction is interpretive (text) returns `[]` here and materializes units in
        a second pass (`bramber materialize`, from the agent's scans). Returning `[]` is a
        correct answer, not a stub."""
        ...

    def changed(self, prev: SourceIdentity, cur: SourceIdentity) -> bool:
        """True if the source materially changed (drives `stale` marking).
        Default semantics: prev != cur."""
        ...
