"""Guard the declared Python floor against syntax only newer interpreters accept.

`pyproject.toml` says `requires-python = ">=3.11"` and CI runs 3.11 and 3.13. The failure
mode this exists for is asymmetric and expensive: PEP 701 relaxed f-strings in 3.12, so a
backslash or a same-quote nesting inside an f-string EXPRESSION is ordinary code on a modern
dev machine and a **SyntaxError at import** on 3.11 — which fails collection of the whole
test module rather than one assertion. A green local suite on 3.13 says nothing about it.

Caught in the wild 2026-07-27: the render-resources eval shipped
`f'{" aria-current=\\"true\\"" if i == 0 else ""}'`, green on 3.13, red on the CI 3.11 leg.

This check runs where the mistake is MADE (3.12+, using that version's f-string tokens) and
is inert on 3.11 itself, where the interpreter is already the authority. It is a lint, not a
parser: it does not pretend to model every version difference, only the one that has bitten.
"""

import io
import sys
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("bramber", "evals", "tests", "tools")

pytestmark = pytest.mark.skipif(
    not hasattr(tokenize, "FSTRING_START"),
    reason="f-string tokens are 3.12+; on 3.11 the interpreter itself rejects this syntax")


def _violations(src: str) -> list:
    """Tokens inside an f-string expression that 3.11's tokenizer would refuse."""
    problems = []
    quotes = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.FSTRING_START:
            quotes.append(tok.string[-1])          # f" / rf''' -> the quote character
        elif tok.type == tokenize.FSTRING_END:
            if quotes:
                quotes.pop()
        elif quotes and tok.type != tokenize.FSTRING_MIDDLE:
            # FSTRING_MIDDLE is the literal text, where a backslash is fine on any version.
            # Everything else between START and END is the expression part.
            if "\\" in tok.string:
                problems.append(f"line {tok.start[0]}: backslash inside an f-string "
                                f"expression — {tok.string!r}")
            elif tok.type == tokenize.STRING and tok.string[:1] == quotes[-1]:
                problems.append(f"line {tok.start[0]}: f-string expression reuses the "
                                f"enclosing {quotes[-1]} quote — {tok.string!r}")
    return problems


def _sources():
    for d in SOURCE_DIRS:
        yield from sorted((REPO / d).rglob("*.py"))


def test_no_pep701_only_fstrings_anywhere_in_the_repo():
    offenders = {}
    for path in _sources():
        found = _violations(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(REPO))] = found
    assert not offenders, (
        "syntax that requires Python 3.12+, but pyproject declares >=3.11:\n"
        + "\n".join(f"  {f}: {'; '.join(v)}" for f, v in offenders.items()))


def test_the_guard_detects_the_construct_that_broke_ci():
    """Mutation check: the exact shape that shipped must be caught, and its 3.11-safe
    rewrite must not be."""
    broke_ci = 'tabs = f\'<button{" aria-current=\\"true\\"" if first else ""}>\''
    assert _violations(broke_ci), "guard is inert against the construct it exists for"

    rewritten = ('current = \' aria-current="true"\' if first else ""\n'
                 "tabs = f'<button{current}>'\n")
    assert _violations(rewritten) == []


def test_repo_sources_are_scanned():
    """A guard that silently scans nothing passes forever."""
    assert len(list(_sources())) > 20
    assert sys.version_info >= (3, 12)   # implied by the skipif; stated so the skip is visible
