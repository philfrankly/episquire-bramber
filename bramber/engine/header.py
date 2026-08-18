"""The extract header — the one declared channel between an adapter and the engine.

`specs/06` T1.1. This module exists because of a bug that shipped: `ingest.py` (the writer)
and `db._sync_sources` (the reader) each carried their own list of header keys, the lists
silently disagreed, and every text source indexed with a NULL url — an invisible lineage hole
in an engine whose product is cited provenance. The header is the **only** channel between an
adapter (which knows the provenance) and the engine (which never imports one), so a key that
only one side knows about is a column that is NULL forever.

Testing a sample passing through the channel cannot catch that. So the key set is declared
once, here, and both sides derive from it:

  - the writer calls `render()`, which **raises** unless it supplies a value for exactly the
    declared fields — adding a field here breaks ingest until ingest is taught to fill it;
  - the reader calls `read()`, which maps a parsed frontmatter dict onto `upsert_source`'s
    keywords — adding a field here reaches the writer call until the schema gains a column.

Either way a one-sided change fails loudly instead of writing NULLs. That is the difference
between catching this bug class and making it impossible (`tests/test_seam.py` guards it).

Domain-blind, like the rest of `bramber/engine/`: these are `Source` fields, not any domain's.
"""

from __future__ import annotations

# Header key -> the `db.upsert_source` keyword it feeds. Order is the order rendered; it
# matches what the writer emitted before this module existed, so re-ingesting an existing
# corpus rewrites byte-identical extracts.
#
# `source_url` -> `url` is the one place the two names differ, and is exactly the sort of
# near-miss that makes two hand-maintained lists drift.
SOURCE_FIELDS: dict[str, str] = {
    "identity_kind":  "identity_kind",
    "identity_key":   "identity_key",
    "identity_json":  "identity_json",
    "source_type":    "source_type",
    "title":          "title",
    "source_url":     "url",
    "author":         "author",
    "date_published": "date_published",
    "date_ingested":  "date_ingested",
}

# Rendered inside double quotes. `db.split_frontmatter` strips a matched surrounding pair, so
# this is a writer convention the reader undoes — it keeps a title's leading/trailing space and
# any `#` from confusing a flat parser.
QUOTED_FIELDS = frozenset({"title"})

# Fields an adapter may legitimately not have (a code symbol has no URL or author). Omitted
# from the header entirely rather than written empty, so "absent" and "blank" stay distinct.
OPTIONAL_FIELDS = frozenset({"source_url", "author", "date_published", "identity_json"})


def render(values: dict) -> list[str]:
    """The header block (including the `---` fences and trailing blank), as lines.

    Raises ValueError unless `values` covers exactly `SOURCE_FIELDS` — that is the check that
    makes this a single declaration rather than a third list to keep in sync. A required field
    whose value is empty also raises: silently dropping it is how a NULL gets into the index.
    """
    missing = [k for k in SOURCE_FIELDS if k not in values]
    unknown = [k for k in values if k not in SOURCE_FIELDS]
    if missing or unknown:
        raise ValueError(
            f"extract header does not match the declaration in {__name__}: "
            f"missing={sorted(missing)} unknown={sorted(unknown)}. Every declared field needs "
            f"a value (use None for an absent optional one)."
        )

    lines = ["---"]
    for key in SOURCE_FIELDS:
        value = values[key]
        blank = value is None or str(value).strip() == ""
        if blank:
            if key in OPTIONAL_FIELDS:
                continue
            raise ValueError(
                f"extract header field {key!r} is required but empty — writing the extract "
                f"anyway would index a NULL that no later pass can recover."
            )
        # Collapsed to one line: `split_frontmatter` is a flat `key: value` parser, so an
        # embedded newline would silently truncate the header there. A colon *inside* the
        # value is safe — it partitions on the first one only, which keeps URLs intact.
        flat = " ".join(str(value).split())
        if key in QUOTED_FIELDS:
            flat = '"{}"'.format(flat.replace('"', "'"))
        lines.append(f"{key}: {flat}")
    lines += ["---", ""]
    return lines


def read(fields: dict) -> dict:
    """A parsed frontmatter dict -> `db.upsert_source` keywords, for every declared field.

    Absent keys come back None rather than missing, so the caller applies its fallbacks
    (identity defaults, ingest date) explicitly instead of relying on `.get`'s silence.
    """
    return {param: fields.get(key) for key, param in SOURCE_FIELDS.items()}
