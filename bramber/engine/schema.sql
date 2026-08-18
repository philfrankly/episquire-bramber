-- bramber — SQLite index + lineage graph.
--
-- The .md tree is authoritative for CONTENT; this DB is the authoritative INDEX +
-- LINEAGE graph and stores a content snapshot per version. Every version is also
-- written to views/<slug>/resources/<rslug>/versions/<n>.md, so bramber.db is fully
-- rebuildable from disk via `python -m bramber.cli rebuild --root <project>`.
-- Because it is derived state, bramber.db is gitignored.
--
-- Lifted from the predecessor factory's engine/schema.sql (specs/01). Renamed
-- prfs -> views; generalized the sources identity columns (specs/00 §6).

PRAGMA journal_mode = WAL;   -- consistent reads for the MCP reader while the agent writes

-- A processing batch. One command invocation. Groups everything below.
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('intake','orchestrate','process','evaluate','consistency')),
    view_id       INTEGER REFERENCES views(id),     -- null for project-level runs
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    summary       TEXT
);

-- Raw inputs, view-agnostic, deduped. One row per distinct source.
-- Identity is pluggable (specs/00 §6): text -> content_sha; code -> git_anchored.
CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER PRIMARY KEY,
    url            TEXT,                             -- original URL / file:// path (text); null otherwise
    title          TEXT,
    source_type    TEXT,                             -- domain string: blog|transcript|symbol|...
    author         TEXT,
    date_published TEXT,
    date_ingested  TEXT NOT NULL,
    identity_kind  TEXT NOT NULL DEFAULT 'content_sha',  -- 'content_sha' | 'git_anchored' | ...
    identity_key   TEXT NOT NULL,                    -- the dedupe hash (was content_sha)
    identity_json  TEXT,                             -- structured identity (commit/path/qname/...) for code; else NULL
    extract_path   TEXT,                             -- _bramber/extracts/<file>.md
    UNIQUE (identity_key)
);

-- One row per view (the integrate-layer projection unit; was PRF's "prf"). Backs bramber://<slug>/.
CREATE TABLE IF NOT EXISTS views (
    id            INTEGER PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,             -- 'architecture'
    name          TEXT NOT NULL,
    view_path     TEXT NOT NULL,                    -- views/<slug>/view.md
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','stale','retired')),
    created_at    TEXT NOT NULL
);

-- One row per resource (a named output of a view). Current pointer; content lives in versions + .md.
CREATE TABLE IF NOT EXISTS resources (
    id                 INTEGER PRIMARY KEY,
    view_id            INTEGER NOT NULL REFERENCES views(id),
    slug               TEXT NOT NULL,               -- 'module-map'
    title              TEXT NOT NULL,
    description        TEXT,                         -- from RESOURCE.md frontmatter (for resources/list)
    maintainer         TEXT NOT NULL DEFAULT 'agent' CHECK (maintainer IN ('agent','human')),
    status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','stale','retired')),
    resource_path      TEXT NOT NULL,               -- views/<slug>/resources/<rslug>/RESOURCE.md
    current_version_id INTEGER REFERENCES resource_versions(id),
    created_at         TEXT NOT NULL,
    UNIQUE (view_id, slug)                           -- bramber://<view-slug>/<resource-slug> is unique
);

-- Immutable content snapshots. Append-only. The version history axis.
CREATE TABLE IF NOT EXISTS resource_versions (
    id             INTEGER PRIMARY KEY,
    resource_id    INTEGER NOT NULL REFERENCES resources(id),
    version_num    INTEGER NOT NULL,                -- 1,2,3... per resource
    content        TEXT NOT NULL,                   -- full markdown snapshot at write time
    content_sha    TEXT NOT NULL,                   -- sha256(content) -> suppress no-op versions
    change_summary TEXT NOT NULL,                   -- "what changed and why"
    run_id         INTEGER REFERENCES runs(id),
    created_at     TEXT NOT NULL,
    UNIQUE (resource_id, version_num)
);

-- Lineage: which sources caused a given version. Join table.
CREATE TABLE IF NOT EXISTS version_sources (
    version_id     INTEGER NOT NULL REFERENCES resource_versions(id),
    source_id      INTEGER NOT NULL REFERENCES sources(id),
    scan_path      TEXT,                            -- the per-source scan that fed this version
    contribution   TEXT,                            -- the unit key this source contributed
    -- `contribution` is IN the key. It was not, and the PK was (version_id, source_id) with an
    -- INSERT OR IGNORE writer, so when N units from one source fed a version only the FIRST
    -- contribution survived — the rest were discarded in silence. A resource built from 40
    -- claims across 3 sources recorded 3 lineage rows and lost the other 37 back-pointers,
    -- which in an engine whose product is cited provenance is the artifact failing at its job.
    PRIMARY KEY (version_id, source_id, contribution)
);

-- The propose-approve loop for view changes. Views are human-gated; agents propose here.
CREATE TABLE IF NOT EXISTS evaluations (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER REFERENCES runs(id),
    scope          TEXT NOT NULL CHECK (scope IN ('view')),
    target         TEXT NOT NULL,                   -- view-slug
    recommendation TEXT NOT NULL,
    rationale      TEXT,
    status         TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected')),
    decided_at     TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rv_resource    ON resource_versions(resource_id);
CREATE INDEX IF NOT EXISTS idx_vs_source      ON version_sources(source_id);
CREATE INDEX IF NOT EXISTS idx_eval_status    ON evaluations(status);
CREATE INDEX IF NOT EXISTS idx_resources_view ON resources(view_id);
