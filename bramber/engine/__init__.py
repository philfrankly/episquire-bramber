"""bramber engine — the domain-blind core: SQLite index + lineage, MCP server.

Lifted from the predecessor factory's engine/ per specs/01-engine-lift.md.
Generalized at exactly two points: source identity (content_sha -> pluggable
identity_kind/identity_key/identity_json) and the view spec filename
(lens.md -> view.md, with lens.md accepted as a fallback).
"""
