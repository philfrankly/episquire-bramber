"""bramber — a view-agnostic claims compiler.

Many sources, scanned once each into a shared store of graded, provenance-pinned
claims; views are cheap, re-runnable projections over that store — versioned,
lineage-tracked, MCP-served. One engine, many domains.

See specs/00-normalize-adapter-contract.md for the one seam a domain implements,
and specs/09-view-agnostic-claim-scan.md for the scan pipeline.
"""

__version__ = "0.0.0"
