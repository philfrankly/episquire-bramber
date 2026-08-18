"""TextAdapter — the predecessor factory's behavior, as a bramber adapter.

The front half of a *text* domain — market intelligence, a project resource factory, any
corpus of fetched documents the agent has already read. Sources are
documents the agent has already fetched and normalized to markdown — a web article, a
YouTube transcript, a PDF/doc — and deposited in `<root>/_bramber/inbox/<name>.md` with flat
frontmatter. Identity is the `content_sha` of the normalized body (text is static, so the
body hash is a stable, kind-agnostic dedupe key — spec 00 §6).

**Fetching is agent-driven, by design.** The engine must stay stdlib-only (the Stop hook
runs `bramber sync` every turn and must never fail on a missing dependency), so this adapter
does **no network I/O**: the agent fetches (WebFetch / youtube-transcript-api / yt-dlp /
pandoc), writes normalized markdown into `_bramber/inbox/`, and this adapter only reads,
identifies, and normalizes those files. That keeps `pip install bramber` dependency-free for
the text domain.

**Unit extraction is interpretive**, so `extract_units` returns `[]` — and that is the
correct answer rather than a stub. Deciding what a source *asserts* is the agent's judgment,
not a parse, so it cannot happen inside a deterministic ingest. Units are materialized in a
second pass out of the agent's view-agnostic scans (`bramber.scan`, `bramber materialize`),
which is what gives text a real `bramber compile` selector path — and every view downstream
selects over that one shared store.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Optional

from bramber.adapter import Adapter, Extract, Source, SourceIdentity, Unit


class TextAdapter(Adapter):
    domain = "text"

    def __init__(self):
        # The inbox root, remembered at discover time so identity()/normalize() — which
        # receive only a Source — can resolve the file. Adapter-layer state; no Protocol
        # or engine change is needed to carry it.
        self._root: Optional[str] = None

    # --- the Adapter contract --------------------------------------------

    def discover_sources(self, root: str) -> Iterable[Source]:
        self._root = root
        inbox = Path(root) / "_bramber" / "inbox"
        if not inbox.exists():
            return
        for f in sorted(inbox.glob("*.md")):
            fields, _ = self._split_frontmatter(f.read_text(encoding="utf-8"))
            yield Source(
                source_type=fields.get("source_type") or "document",
                title=fields.get("title"),
                url=fields.get("source_url"),
                author=fields.get("author"),
                date_published=fields.get("date_published"),
                ref=f.name,                       # filename — readable, stable slug base
            )

    def identity(self, source: Source) -> SourceIdentity:
        key = self._sha(self._read_body(source))
        return SourceIdentity(kind="content_sha", key=key, data={"ref": source.ref})

    def normalize(self, source: Source) -> Extract:
        body = self._read_body(source)
        return Extract(source=source, identity=self.identity(source), body=body)

    def extract_units(self, extract: Extract) -> list[Unit]:
        return []  # text units are derived by the agent at scan time (interpretive, per source)

    def changed(self, prev: SourceIdentity, cur: SourceIdentity) -> bool:
        return prev.key != cur.key

    # --- helpers (adapter-local; stdlib-only, no engine import) ----------

    def _read_body(self, source: Source) -> str:
        """The normalized markdown body of an inbox source, frontmatter stripped."""
        if self._root is None:
            raise RuntimeError("TextAdapter: discover_sources() must run before identity()/normalize()")
        path = Path(self._root) / "_bramber" / "inbox" / (source.ref or "")
        return self._split_frontmatter(path.read_text(encoding="utf-8"))[1]

    @staticmethod
    def _sha(body: str) -> str:
        """sha256 of the stripped body — byte-identical to `db.sha256`, so a re-sync
        recomputes the same identity_key (dedup + staleness stay consistent)."""
        return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[dict, str]:
        """Minimal flat `key: value` frontmatter parser between leading `---` fences.

        Returns (fields, body). Mirrors `db.split_frontmatter` semantics (so what the agent
        writes into an inbox file is read back the same way) but is adapter-local — the
        adapter never imports the engine. No frontmatter -> ({}, text).
        """
        if not text.startswith("---"):
            return {}, text
        lines = text.splitlines()
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            return {}, text
        fields: dict[str, str] = {}
        for ln in lines[1:end]:
            if ":" not in ln or ln.strip().startswith("#") or not ln.strip():
                continue
            key, _, val = ln.partition(":")
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            fields[key] = val
        body = "\n".join(lines[end + 1:]).strip("\n") + "\n"
        return fields, body
