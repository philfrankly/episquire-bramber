# Genre view starters

One corpus, many views — that is the product's demonstration shape: the same sources project
into a stakeholder brief, a requirements set, a risk register, a current-state analysis, a
commercial read, and a decision log, each selecting and weighting the shared claims its own way.

Pick the starter whose genre matches the document you need (or the blank `../view.md` for an
angle none of these fit), copy it to `views/<slug>/view.md`, and **instantiate it**: replace
every `<angle-bracket>` placeholder, set the frontmatter `name`/`slug`, and sharpen the Thesis
to your domain — the Thesis is the frame the shared claim store is projected through, and it is
human-owned (only `/bramber:evaluate` changes it after first use). `/bramber:new-view` walks
this end to end, and compiles the new view against the existing store immediately — adding a
view costs no corpus work.

Each starter ships with a valid ```selector block (`dedup_by`, `order_by`, `project` are
required and have no defaults — a view missing one fails loudly at compile). Selectors may
reference the unit payload fields: `claim_key`, `statement`, `evidence_strength`
(`strong | moderate | weak | speculative`), `recency`, `topics` (list; `match.topics` is
any-of — narrow a starter to your subject with the tags the store actually uses).

These starters are domain-neutral on purpose; keeping them that way is tested
(`tests/test_plugin_integrity.py`).
