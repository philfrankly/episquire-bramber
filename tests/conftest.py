"""Shared fixtures.

Currently one: `no_embed_extra`, which decouples the `[embed]` degrade tests from whatever
happens to be installed in the developer's environment.

**Why this exists.** The degrade tests (specs/11 G7 — no `[embed]`, no index: the full feed, a
stderr notice, no error) used to read the *real* environment, and were honest only while
`fastembed` was absent from it. `tests/test_index.py` carried a tripwire saying so, which fired
on 2026-08-17 the first time the extra was installed — correctly, because at that moment two
tests that claimed to exercise the no-embed path were silently exercising the embed path
instead. A test that stops discriminating without going red is the failure this repo already
has one documented instance of (the eval queue, Layer B's `fabrication 0.0000`).

**What this is not.** It is not a mock of the degrade. `index.build`, `scan.feed_like` and the
CLI's degrade branch all run for real; only the single OS-level probe underneath
`index.embed_available()` — `importlib.util.find_spec("fastembed")` — is made to answer the way
it would on a machine without the extra. Everything the tests assert about is downstream of
that one call, so the path under test is the shipped one either way.
"""

from __future__ import annotations

import importlib.util

import pytest

from bramber import index as index_mod


@pytest.fixture
def no_embed_extra(monkeypatch):
    """Make `index.embed_available()` answer False, whether or not the extra is installed.

    Narrow by construction: only `EMBED_PACKAGE` is reported missing; every other `find_spec`
    query is delegated to the real implementation, so nothing else in the import machinery
    changes shape for the duration of the test. `monkeypatch` restores the attribute at
    teardown — `test_the_forced_absence_does_not_leak_between_tests` is the guard on that.

    The assertion below is the tripwire this fixture inherits from the environment check it
    replaced: it fails loudly if the forcing ever stops working (an `embed_available` rewritten
    to probe some other way), rather than letting the degrade tests quietly pass for the wrong
    reason.
    """
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == index_mod.EMBED_PACKAGE:
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    assert not index_mod.embed_available(), (
        "the forced-absence fixture no longer forces absence — embed_available() has stopped "
        "resolving through importlib.util.find_spec, and every degrade test is now testing "
        "whatever the environment happens to have installed")
    return fake_find_spec
