"""Reference adapters. Domain logic lives here; the engine never imports these.

- text  : agent-fetched markdown in `_bramber/inbox/`; content_sha identity.

One adapter ships. A `code` adapter was withdrawn 2026-07-21 (it wrapped an extraction
engine nobody could install); the use-case is preserved as a requirement for a future
adapter, and the seam it plugged into is unchanged.
"""
