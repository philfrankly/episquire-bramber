"""bramber index — the candidate index: retrieval NOMINATES, it never asserts.

Canonical spec: `specs/10-retrieval-over-the-claim-store.md` §4.1, as ruled by
`specs/11-retrieval-over-the-witnessed-ledger.md` (G1, G2, G7).

**What this is:** a rebuildable cache of embedding vectors and keyword tokens over the unit
store, used to shortlist candidate keys for the mint-or-reuse feed and the retrieval surface.
The full feed is O(N²) in context tokens and its recall collapses around ~12k keys; a top-k
shortlist restores O(N·k) and roughly constant recall. The shortlist can afford to be lossy and
low-precision because the decide step it feeds must still quote the minted statement it
endorses (the witness) and resolve against the minted set — a bad nomination can cost recall,
never truth.

**What this is not, by ruling — each clause is load-bearing:**

  - It asserts nothing: no merge, no support increment, no edge. `search` returns
    `(kind, key, score)` nominations and nothing else — a caller that wants a statement or a
    `reuse_as` token reads the store fresh (`scan.known_keys`), never this cache (G2: vectors
    may be stale, tokens may not).
  - It derives exclusively from `_bramber/units/*.json` (G1) — the post-resolution envelopes —
    keyed by the FINAL stored key, invalidated per-envelope by content sha. An index over scans
    would nominate unresolved keys and could serve a `reuse_as` that disagrees with the store.
  - It is a losable cache with exactly `bramber.db`'s status: disk is truth, deleting
    `_bramber/index/` is a non-event, the next build regenerates it.

**The one true dependency is a LOCAL embedding model** — `fastembed`, held behind the
`[embed]` extra and ruled 2026-08-08
(the 2026-08-08 ruling "embeddings run on a local model"). It runs in-process on ONNX (no
torch), needs no API key, and makes no network call at index or serve time: a corpus can be
indexed offline and **nothing about it leaves the machine**. That is a product property, not
an implementation detail — this repo's whole leak discipline (the leak tripwire,
the 2026-07-23 ruling "context leak remediation") exists to stop corpus specifics escaping,
and a hosted embedding API would have POSTed every claim's verbatim statement to a third
party. `specs/00 §208` recorded the same constraint from the client side: in-perimeter
clients may forbid egress.

It is imported lazily inside `default_embedder`, so this module — and everything that imports
it — stays importable on a stdlib-only install. The Stop hook's guarantee is untouched. Absent
the extra, the feed degrades to the full universe with no error (G7); only `bramber index`
itself, whose entire job is the vectors, refuses with the install hint.

**Brute-force cosine, deliberately.** Tens of thousands of short unit-normalized vectors dot
sub-second in pure Python; a vector-store dependency at this scale would buy nothing and cost
the stdlib guarantee. The hybrid's keyword half costs no dependency at all and catches exact
terms an embedding fuzzes over — key names, entity spellings, topic tags.

**One entry per (envelope, kind, key), not per key** — each source's own phrasing of a reused
claim is a free retrieval text (specs/11 M4), so corroborated claims become MORE retrievable
with every endorsement, which is exactly the right bias. Search aggregates per (kind, key) by
max over the entries.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
from pathlib import Path
from typing import Callable, Iterable, Optional

from bramber.engine import db

EMBED_PACKAGE = "fastembed"
# 384 dimensions, ~50 MB ONNX, downloaded once on first use and cached by fastembed. Small on
# purpose: the index stores a vector per (envelope, kind, key), so dimensionality is the term
# that decides the cache's size on disk (~2.7x smaller than a 1024-dim model).
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
INDEX_VERSION = 1

# An embedder maps texts -> vectors. `kind` is "document" (index time) or "query" (serve
# time) — retrieval-tuned providers embed the two asymmetrically, and a fake in a test
# ignores it. Injectable everywhere, so no test touches the network and swapping the
# provider is a one-function change.
Embedder = Callable[..., list]


def embed_available() -> bool:
    """Is the [embed] extra installed? A presence check, never an import — checking by
    importing would pay the import cost on the degrade path that exists to avoid it."""
    return importlib.util.find_spec(EMBED_PACKAGE) is not None


def default_embed_model() -> str:
    return os.environ.get("BRAMBER_EMBED_MODEL") or DEFAULT_EMBED_MODEL


def default_embedder() -> Embedder:
    """The local, in-process embedder, constructed lazily.

    Raises with the install hint rather than degrading: the callers that reach here (the
    `bramber index` CLI, a feed shape that decided to shortlist) have already chosen the
    retrieval path, and silently serving keyword-only results would report a recall the
    index does not have. The graceful degrade lives one level up, where `[embed]`-absent
    means the full feed and no retrieval at all (G7).

    Documents and queries are embedded through **different** entry points where the model
    asks for it. Retrieval-tuned models (BGE among them) are trained with an instruction
    prefix on the query side only; `fastembed` owns that per-model detail in `query_embed`,
    so asking for it here is what keeps a query and a passage comparable instead of quietly
    off by a prefix. A model whose build lacks the method falls back to the symmetric path.
    """
    if not embed_available():
        raise SystemExit(
            f"[bramber] index: the local embedding model ({EMBED_PACKAGE!r}) is not "
            f"installed. Retrieval is an optional extra — `pip install bramber[embed]`. It "
            f"runs locally: no API key, no network, nothing about your corpus leaves the "
            f"machine (the model itself downloads once, then works offline). Without it "
            f"every feed serves the full universe and nothing else changes; the discipline "
            f"degrades, it does not break.")
    from fastembed import TextEmbedding  # the [embed] extra; imported only on this path

    model = TextEmbedding(model_name=default_embed_model())
    query_embed = getattr(model, "query_embed", None)

    def embed(texts: list, *, kind: str = "document") -> list:
        texts = list(texts)
        if not texts:
            return []
        producer = query_embed if (kind == "query" and query_embed) else model.embed
        # fastembed yields numpy arrays lazily; materialize to plain lists so nothing
        # downstream — `_unit_norm`, the JSON cache — has to know a numpy type exists.
        return [[float(x) for x in vec] for vec in producer(texts)]

    return embed


# ---------------------------------------------------------------------------
# deriving entries from the envelopes (G1: units, never scans)
# ---------------------------------------------------------------------------

# Per unit kind: the payload key that is the FINAL stored identity, and how to build the
# retrieval text. Statements carry a claim's content; names + glosses carry an entity's or
# term's. Topics ride the keyword half for every kind.
_KIND_KEYS = {
    "claim": "claim_key",
    "contradiction": "contradiction_key",
    "entity": "entity_key",
    "term": "term_key",
}


def _retrieval_text(kind: str, payload: dict) -> Optional[str]:
    if kind in ("claim", "contradiction"):
        return payload.get("statement") or None
    if kind == "entity":
        name, gloss = payload.get("entity_name") or "", payload.get("gloss") or ""
        return f"{name} — {gloss}".strip(" —") or None
    if kind == "term":
        name, gloss = payload.get("term_name") or "", payload.get("gloss") or ""
        return f"{name} — {gloss}".strip(" —") or None
    return None


def _extra_tokens(kind: str, payload: dict) -> list:
    """Keyword-half material beyond the retrieval text: topics on every kind, aliases and
    relations where the payload carries them. Exact-term matches are the whole point of the
    keyword half, so the surface forms go in as written (then normalized by `_tokens`)."""
    extras: list = list(payload.get("topics") or [])
    extras += payload.get("aliases") or []
    extras += payload.get("relates_to") or []
    return [str(t) for t in extras if str(t).strip()]


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(*texts: str) -> set:
    out: set = set()
    for t in texts:
        out |= set(_TOKEN_RE.findall((t or "").casefold()))
    return out


def _unit_norm(vec: Iterable[float]) -> list:
    v = [float(x) for x in vec]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def _entries_for_envelope(slug: str, envelope: dict) -> list:
    out = []
    for u in (envelope.get("units") or []):
        kind = u.get("kind")
        key_field = _KIND_KEYS.get(kind)
        if not key_field:
            continue
        payload = u.get("payload") or {}
        key = payload.get(key_field)
        text = _retrieval_text(kind, payload)
        if not key or not text:
            continue
        out.append({
            "kind": kind, "key": str(key), "envelope": slug, "text": text,
            "extra_tokens": _extra_tokens(kind, payload),
        })
    return out


# ---------------------------------------------------------------------------
# the on-disk cache
# ---------------------------------------------------------------------------

def index_dir(data_root) -> Path:
    return Path(data_root).resolve() / "_bramber" / "index"


def _index_path(data_root) -> Path:
    return index_dir(data_root) / "index.json"


def load(data_root) -> Optional[dict]:
    p = _index_path(data_root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None  # a corrupt cache is a missing cache — disk is truth, rebuild
    if data.get("version") != INDEX_VERSION:
        return None
    return data


def _units_files(data_root) -> list:
    units_dir = Path(data_root).resolve() / "_bramber" / "units"
    return sorted(units_dir.glob("*.json")) if units_dir.exists() else []


def build(data_root, *, embedder: Optional[Embedder] = None, model: Optional[str] = None,
          rebuild: bool = False) -> dict:
    """Build or incrementally update the index. Returns a summary, never entries.

    Incremental by envelope content sha: an unchanged envelope keeps its entries and their
    vectors untouched; a changed one re-derives its entries, reusing vectors for texts that
    survived the change byte-identically; a removed one takes its entries with it. A changed
    embed model invalidates everything — two models' vector spaces do not compare, and a
    cosine across them is a number that looks like evidence.
    """
    model = model or default_embed_model()
    prev = None if rebuild else load(data_root)
    if prev and prev.get("embed_model") != model:
        prev = None

    prev_shas: dict = (prev or {}).get("envelopes") or {}
    prev_by_env: dict = {}
    for e in (prev or {}).get("entries") or []:
        prev_by_env.setdefault(e["envelope"], []).append(e)

    envelopes: dict = {}
    entries: list = []
    to_embed: list = []          # entries whose vector is still missing
    reused = 0

    for uf in _units_files(data_root):
        slug = uf.stem
        raw = uf.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        envelopes[slug] = sha

        if prev_shas.get(slug) == sha:
            kept = prev_by_env.get(slug, [])
            entries.extend(kept)
            reused += len(kept)
            continue

        # Changed or new: re-derive, but reuse a vector when the text is byte-identical —
        # an envelope edit that adds one claim must not re-pay the other forty.
        old_vec = {(e["kind"], e["key"], e["text"]): e.get("vector")
                   for e in prev_by_env.get(slug, [])}
        for entry in _entries_for_envelope(slug, json.loads(raw.decode("utf-8"))):
            vec = old_vec.get((entry["kind"], entry["key"], entry["text"]))
            if vec is not None:
                entry["vector"] = vec
                reused += 1
            else:
                to_embed.append(entry)
            entries.append(entry)

    if to_embed:
        embedder = embedder or default_embedder()
        vectors = embedder([e["text"] for e in to_embed], kind="document")
        if len(vectors) != len(to_embed):
            raise SystemExit(
                f"[bramber] index: the embedder returned {len(vectors)} vector(s) for "
                f"{len(to_embed)} text(s) — refusing to guess which text lost its vector.")
        for entry, vec in zip(to_embed, vectors):
            entry["vector"] = _unit_norm(vec)

    out_dir = index_dir(data_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    _index_path(data_root).write_text(json.dumps({
        "version": INDEX_VERSION,
        "embed_model": model,
        "envelopes": envelopes,
        "entries": entries,
    }), encoding="utf-8")

    return {
        "envelopes": len(envelopes),
        "entries": len(entries),
        "embedded": len(to_embed),
        "reused_vectors": reused,
        "removed_envelopes": sorted(set(prev_shas) - set(envelopes)),
    }


def status(data_root) -> dict:
    """What the index covers versus what is on disk. Stdlib-only — no embedder needed to ask.

    `stale` names envelopes whose sha no longer matches (or were never indexed), which is the
    at-most-one-source-stale window G1 accepts between a materialize and the next build.
    """
    idx = load(data_root)
    on_disk = {uf.stem: hashlib.sha256(uf.read_bytes()).hexdigest()
               for uf in _units_files(data_root)}
    indexed = (idx or {}).get("envelopes") or {}
    return {
        "present": idx is not None,
        "embed_model": (idx or {}).get("embed_model"),
        "envelopes_indexed": len(indexed),
        "envelopes_on_disk": len(on_disk),
        "entries": len((idx or {}).get("entries") or []),
        "stale": sorted(s for s, sha in on_disk.items() if indexed.get(s) != sha),
        "orphaned": sorted(set(indexed) - set(on_disk)),
    }


# ---------------------------------------------------------------------------
# search — nomination only, ever
# ---------------------------------------------------------------------------

def _keyword_score(query_tokens: set, entry_tokens: set) -> float:
    """Fraction of the QUERY's tokens the entry covers. Query-anchored on purpose: a long
    statement that happens to contain one query word should not outrank a short one that
    contains them all."""
    if not query_tokens:
        return 0.0
    return len(query_tokens & entry_tokens) / len(query_tokens)


def _score_entries(entries: list, query_vec: Optional[list], query_tokens: set,
                   kinds: Optional[set]) -> dict:
    best: dict = {}
    for e in entries:
        if kinds and e["kind"] not in kinds:
            continue
        cos = 0.0
        vec = e.get("vector")
        if query_vec is not None and vec:
            cos = max(0.0, sum(a * b for a, b in zip(query_vec, vec)))
        kw = _keyword_score(query_tokens, _tokens(e["text"], *e.get("extra_tokens") or []))
        score = 0.5 * cos + 0.5 * kw
        ident = (e["kind"], e["key"])
        if score > best.get(ident, (0.0,))[0]:
            best[ident] = (score,)
    return {ident: s[0] for ident, s in best.items()}


def search(data_root, query_text: str, *, k: int = 10, kinds: Optional[Iterable[str]] = None,
           embedder: Optional[Embedder] = None) -> list:
    """The top-k candidates for one query text. Rows are `{kind, key, score}` — nominations.

    Nothing else, structurally: no statement, no witness, no `reuse_as`, no provenance. A
    caller that served those from here would be serving a cache where the ledger requires the
    store (G2), so the shape refuses the mistake rather than trusting every caller to
    remember. Only an agent or a human decides; only recorded provenance asserts.
    """
    idx = load(data_root)
    if idx is None:
        raise SystemExit(
            "[bramber] index: no usable index on disk (missing, unreadable, or an older "
            "index version) — run `bramber index` first. (The index is a rebuildable "
            "cache; a corrupt one is a missing one, and rebuilding is cheap.)")
    embedder = embedder or default_embedder()
    query_vec = _unit_norm(embedder([query_text], kind="query")[0])
    scored = _score_entries(idx["entries"], query_vec, _tokens(query_text),
                            set(kinds) if kinds else None)
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"kind": kind, "key": key, "score": round(score, 6)}
            for (kind, key), score in ranked[:k]]


def nominate_for_extract(data_root, extract_rel: str, *, limit: int = 200,
                         kinds: Optional[Iterable[str]] = ("claim", "contradiction"),
                         embedder: Optional[Embedder] = None) -> list:
    """Shape B's candidate pool: every key similar to ANY section of one extract.

    The extract is bramber's own normalized artifact — embedding it is not parsing a source;
    the adapter did that once, at ingest. Sections are split on H2 headings (paragraph blocks
    when a source has none), each embedded as its own query, and the per-section shortlists
    union with max score. Coarse by design (`specs/10` §4.2): ~100–300 rows the agent reads
    once, with no mid-scan round trips. Returns `{kind, key, score}` rows like `search`.
    """
    path = Path(data_root).resolve() / extract_rel
    if not path.exists():
        raise SystemExit(f"[bramber] index: no extract at {extract_rel!r} under {data_root}")
    _, _, body = db.split_frontmatter(path.read_text(encoding="utf-8"))
    sections = [s.strip() for s in re.split(r"^##\s+", body, flags=re.M) if s.strip()]
    if len(sections) <= 1:
        sections = [s.strip() for s in re.split(r"\n\s*\n", body) if s.strip()] or [body]

    idx = load(data_root)
    if idx is None:
        raise SystemExit(
            "[bramber] index: no usable index on disk (missing, unreadable, or an older "
            "index version) — run `bramber index` first. (The index is a rebuildable "
            "cache; a corrupt one is a missing one, and rebuilding is cheap.)")
    embedder = embedder or default_embedder()
    vectors = [_unit_norm(v) for v in embedder(sections, kind="query")]

    wanted = set(kinds) if kinds else None
    per_section_k = max(20, limit // max(1, len(sections)))
    best: dict = {}
    for section, vec in zip(sections, vectors):
        scored = _score_entries(idx["entries"], vec, _tokens(section), wanted)
        ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:per_section_k]
        for ident, score in ranked:
            best[ident] = max(best.get(ident, 0.0), score)

    ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"kind": kind, "key": key, "score": round(score, 6)}
            for (kind, key), score in ranked]
