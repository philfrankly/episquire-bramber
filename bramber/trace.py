"""bramber trace — an observability recorder for a single command invocation.

Answers the auditor's question: *for each step of the pipeline, what went in, what came
out, and — for everything that did not come out — why not?*

`--trace` on `bramber ingest|select|compile` records each pipeline step to
`_bramber/traces/<ts>-<command>.json` and renders a self-contained `.html` beside it.

Three constraints shape this module:

  1. **The engine never learns that tracing exists.** `bramber/engine/` is domain-blind and
     stdlib-only, and the falsifiable seam test (CLAUDE.md) is that adding capability must
     not require editing it. Observability is a cross-cutting concern — exactly the kind
     that pollutes an engine if you let it in. So the recorder lives here, at the same
     level as `ingest.py`/`compile.py`, and only those two front-half modules call it.
  2. **Stdlib-only**, like everything on the `bramber sync` path — no template engine, no
     serializer. The HTML is a string template with one JSON payload spliced in.
  3. **Domain-blind vocabulary.** A step records rows of `{status, ref, detail, reason}`.
     It does not know what a claim, a symbol, or a blog post is — the *callers* supply
     domain strings. The same recorder traces a code ingest and a text ingest.

Disabled is the default and costs nothing: `NULL_TRACE.step(...)` returns a shared no-op
step, so instrumented call sites need no `if trace:` guards.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MAX_PREVIEW = 2000          # chars of any single free-text value carried into the trace


def clip(text, limit: int = MAX_PREVIEW) -> str:
    """Trim a free-text value to a previewable size, marking that it was trimmed.

    Extract bodies are arbitrarily large; a trace is a lens on the run, not a copy of it.
    """
    s = "" if text is None else str(text)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n… [{len(s) - limit} more chars]"


# ---------------------------------------------------------------------------
# the recorded shapes
# ---------------------------------------------------------------------------

@dataclass
class Step:
    """One pipeline step: its inputs, its outputs, and a row per item it handled.

    `rows` is where the audit lives. **Every item a step considered gets a row** — the
    dropped ones included, each carrying the reason it was dropped. A step that reports
    only what survived is a log; a step that reports what it rejected and why is an
    account you can either trust or argue with.

    Rows carry an optional `group`, and the page renders grouped rows source-first: every
    unit a source produced, listed together, each marked with what became of it. That is
    the shape of the question a reader actually has — "this symbol produced four units,
    why did only one make it in?" — so the answer is visible rather than searched for.
    """

    name: str
    summary: str = ""
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    groups: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    duration_ms: float | None = None
    _t0: float = field(default=0.0, repr=False)

    def row(self, status: str, ref: str, *, tag: str = "", group: str = "",
            detail: str = "", reason: str = "", data=None) -> None:
        """Record one item this step handled.

        status  — 'selected' / 'rejected' / 'deduped' / 'ok' / 'error' (free string; the
                  page colours known ones and falls back to neutral for the rest)
        ref     — how a human names the item (a qualified name, a source ref, a path)
        tag     — a short chip beside the name (a lens, a kind — the caller's vocabulary)
        group   — the source this item came from; rows sharing one render together
        detail  — what the step produced for it
        reason  — why it was dropped (the audit payload; empty for kept items)
        data    — the full object, shown in the row's expander for deep inspection
        """
        self.rows.append({
            "status": status,
            "ref": str(ref),
            "tag": tag,
            "group": group,
            "detail": clip(detail, 400),
            "reason": clip(reason, 400),
            "data": data,
        })

    def group(self, name: str, **meta) -> None:
        """Attach metadata to a group (an extract path, a title) for its header."""
        self.groups[name] = {k: v for k, v in meta.items() if v}

    def note(self, text: str) -> None:
        self.notes.append(str(text))

    @contextmanager
    def timing(self):
        """Accumulate elapsed time into this step, across however many calls.

        For steps whose work is *interleaved* with other steps': `ingest` runs all five
        adapter phases per source inside one loop, so "when did this step start and end"
        is meaningless — every step would report the whole loop's wall clock, the same
        misleading number five times. Accumulating instead answers the question actually
        worth asking: how much of the run did *this phase* consume?
        """
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.duration_ms = round(
                (self.duration_ms or 0.0) + (time.perf_counter() - t0) * 1000, 2)

    def close(self) -> None:
        """Stamp elapsed time — unless `timing()` already accumulated a real figure, which
        is the truthful one for an interleaved step."""
        if self.duration_ms is None:
            self.duration_ms = round((time.perf_counter() - self._t0) * 1000, 2)

    def __enter__(self) -> "Step":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
        return None

    def as_dict(self) -> dict:
        counts: dict[str, int] = {}
        for r in self.rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {
            "name": self.name,
            "summary": self.summary,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "rows": self.rows,
            "groups": self.groups,
            "notes": self.notes,
            "counts": counts,
            "duration_ms": self.duration_ms,
        }


class _NullStep(Step):
    """A step that records nothing — the disabled path, so call sites need no guards.

    Deliberately allocated fresh per `step()` rather than shared: call sites assign into
    the public `inputs`/`outputs` dicts, which no-op *methods* cannot intercept, so a
    shared instance would accumulate every disabled run's data forever. Five throwaway
    objects per command is not a cost worth a cleverer design.
    """

    def row(self, *a, **k) -> None:
        return None

    def group(self, *a, **k) -> None:
        return None

    def note(self, *a, **k) -> None:
        return None

    def timing(self):
        return nullcontext()

    def close(self) -> None:
        return None


class Trace:
    """A recording of one command invocation. `save()` writes the JSON + the HTML page."""

    enabled = True

    def __init__(self, command: str, root, args: dict | None = None):
        self.command = command
        self.root = Path(root)
        self.args = args or {}
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.steps: list[Step] = []

    def step(self, name: str, summary: str = "") -> Step:
        """Open a step. Usable as a context manager (times itself) or bare (append rows
        across a loop, as `ingest` does — its steps mirror the Adapter Protocol and each
        one accrues a row per source as the loop runs)."""
        s = Step(name=name, summary=summary)
        s._t0 = time.perf_counter()
        self.steps.append(s)
        return s

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "root": str(self.root),
            "args": self.args,
            "started_at": self.started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "steps": [s.as_dict() for s in self.steps],
        }

    def save(self, out_dir=None) -> Path:
        """Write `<ts>-<command>.json` + `.html` to `_bramber/traces/`; return the page path.

        The JSON is the record (diffable, assertable in tests, machine-auditable); the HTML
        is a rendering of it. Both are derived artifacts — safe to delete, gitignored.
        """
        data = self.as_dict()
        out = Path(out_dir) if out_dir else (self.root / "_bramber" / "traces")
        out.mkdir(parents=True, exist_ok=True)

        # Two runs in the same second must not collide: `compile --view a` followed by
        # `compile --view b` takes well under a second, and an audit artifact that silently
        # overwrites another audit artifact is the one failure this tool cannot have.
        base = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{self.command}"
        stem, n = base, 2
        while (out / f"{stem}.html").exists() or (out / f"{stem}.json").exists():
            stem, n = f"{base}-{n}", n + 1

        (out / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        page = out / f"{stem}.html"
        page.write_text(render_html(data), encoding="utf-8")
        return page


class NullTrace(Trace):
    """The `--trace`-off path: every step is a no-op and nothing is written."""

    enabled = False

    def __init__(self):
        super().__init__("null", Path("."))

    def step(self, name: str, summary: str = "") -> Step:
        return _NullStep(name=name)

    def save(self, out_dir=None):
        return None


NULL_TRACE = NullTrace()


def make(enabled: bool, command: str, root, args: dict | None = None) -> Trace:
    """The one construction point call sites use: `trace.make(args.trace, "compile", root)`."""
    return Trace(command, root, args) if enabled else NULL_TRACE


# ---------------------------------------------------------------------------
# render — a self-contained page (no network at view time; the JSON is inlined)
# ---------------------------------------------------------------------------

def render_html(data: dict) -> str:
    """Splice the trace JSON into the page template.

    `</` is escaped because a `</script>` sequence inside a JSON string value would
    otherwise close the tag early — the one real hazard of inlining data into HTML.
    """
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    return _TEMPLATE.replace("__TRACE_JSON__", payload).replace(
        "__TITLE__", f"bramber trace — {data.get('command', '')}")


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>__TITLE__</title>
<script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script>
  tailwind.config = {
    darkMode: 'class',
    theme: { extend: {
      colors: {
        border: 'hsl(var(--border))', input: 'hsl(var(--input))', ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))', foreground: 'hsl(var(--foreground))',
        primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
        secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },
        muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
        accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },
        card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
      },
      borderRadius: { lg: '0.5rem', md: 'calc(0.5rem - 2px)', sm: 'calc(0.5rem - 4px)' },
    } },
  }
</script>
<style>
  :root {
    --background: 0 0% 100%; --foreground: 222.2 84% 4.9%;
    --card: 0 0% 100%; --card-foreground: 222.2 84% 4.9%;
    --primary: 222.2 47.4% 11.2%; --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96.1%; --secondary-foreground: 222.2 47.4% 11.2%;
    --muted: 210 40% 96.1%; --muted-foreground: 215.4 16.3% 46.9%;
    --accent: 210 40% 96.1%; --accent-foreground: 222.2 47.4% 11.2%;
    --border: 214.3 31.8% 91.4%; --input: 214.3 31.8% 91.4%; --ring: 222.2 84% 4.9%;
  }
  .dark {
    --background: 222.2 84% 4.9%; --foreground: 210 40% 98%;
    --card: 222.2 84% 4.9%; --card-foreground: 210 40% 98%;
    --primary: 210 40% 98%; --primary-foreground: 222.2 47.4% 11.2%;
    --secondary: 217.2 32.6% 17.5%; --secondary-foreground: 210 40% 98%;
    --muted: 217.2 32.6% 17.5%; --muted-foreground: 215 20.2% 65.1%;
    --accent: 217.2 32.6% 17.5%; --accent-foreground: 210 40% 98%;
    --border: 217.2 32.6% 17.5%; --input: 217.2 32.6% 17.5%; --ring: 212.7 26.8% 83.9%;
  }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  code, pre { font-family: ui-monospace, SFMono-Regular, 'Cascadia Code', Consolas, monospace; }
</style>
</head>
<body class="bg-background text-foreground min-h-screen">
<div id="root"></div>
<script>
  if (window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.classList.add('dark');
  const TRACE = __TRACE_JSON__;
</script>
<script type="text/babel">
const { useState, useMemo } = React;
const cn = (...c) => c.filter(Boolean).join(' ');

const Card = ({ className, children }) => (
  <div className={cn('rounded-lg border bg-card text-card-foreground shadow-sm', className)}>{children}</div>
);

const TONES = {
  selected: 'border-emerald-600/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  ok:       'border-emerald-600/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  created:  'border-emerald-600/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  rejected: 'border-rose-600/30 bg-rose-500/10 text-rose-700 dark:text-rose-400',
  error:    'border-rose-600/30 bg-rose-500/10 text-rose-700 dark:text-rose-400',
  deduped:  'border-amber-600/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  skipped:  'border-amber-600/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  empty:    'border-border bg-muted text-muted-foreground',
  unchanged:'border-sky-600/30 bg-sky-500/10 text-sky-700 dark:text-sky-400',
};
// A shape as well as a colour: the marker has to survive colour-blindness and a greyscale print.
const MARKS = { selected: '✓', ok: '✓', created: '✓', rejected: '✗', error: '✗',
                deduped: '⧉', skipped: '⊘', empty: '⊘', unchanged: '=' };

const Badge = ({ status, children }) => (
  <span className={cn('inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap',
    TONES[status] || 'border-border bg-muted text-muted-foreground')}>{children ?? status}</span>
);

const Mark = ({ status }) => (
  <span title={status} className={cn('inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold',
    TONES[status] || 'border-border bg-muted text-muted-foreground')}>{MARKS[status] || '•'}</span>
);

const Input = (props) => (
  <input {...props} className={cn('flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm',
    'placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', props.className)} />
);

const Value = ({ v }) => {
  const s = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
  if (s === '' || s == null) return <span className="text-muted-foreground italic">empty</span>;
  return <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">{s}</pre>;
};

/* Each value scrolls inside its own box. A step's inputs are context for the rows below —
   one long value must never push the actual items off the screen. */
const KeyValues = ({ title, obj }) => {
  const keys = Object.keys(obj || {});
  return (
    <Card className="p-4 min-w-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">{title}</h3>
      {keys.length === 0 ? <p className="text-sm text-muted-foreground italic">nothing recorded</p> : (
        <dl className="space-y-3">
          {keys.map(k => (
            <div key={k} className="min-w-0">
              <dt className="text-xs font-medium text-muted-foreground mb-1">{k}</dt>
              <dd className="max-h-56 overflow-auto rounded-md bg-muted/60 p-2"><Value v={obj[k]} /></dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
};

/* One item: a marker saying what became of it, and — when it was dropped — why.
   The reason sits inline, not behind a click: the point is that a reader who was not
   looking for it still reads it. */
function Item({ row, idx, openKey, setOpenKey }) {
  const isOpen = openKey === idx;
  return (
    <li className="border-t first:border-t-0">
      <div className={cn('flex items-start gap-2.5 px-3 py-2', row.data && 'cursor-pointer hover:bg-muted/40')}
           onClick={() => row.data && setOpenKey(isOpen ? null : idx)}>
        <Mark status={row.status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-xs break-all">{row.ref}</span>
            {row.tag && <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{row.tag}</span>}
          </div>
          {row.detail && <p className="mt-0.5 text-xs text-muted-foreground">{row.detail}</p>}
          {row.reason && (
            <p className="mt-0.5 text-xs">
              <span className="font-medium text-rose-700 dark:text-rose-400">{row.status}: </span>
              <span className="text-muted-foreground">{row.reason}</span>
            </p>
          )}
        </div>
        {row.data && <span className="shrink-0 text-xs text-muted-foreground">{isOpen ? '▾' : '▸'}</span>}
      </div>
      {isOpen && row.data && (
        <pre className="max-h-96 overflow-auto border-t bg-muted/40 p-3 text-xs leading-relaxed">
          {JSON.stringify(row.data, null, 2)}
        </pre>
      )}
    </li>
  );
}

/* Rows grouped under the source that produced them. Every unit a source yielded is here,
   kept or dropped — the reader scans sources, not a filtered table. */
function SourceGroup({ name, meta, rows, openKey, setOpenKey }) {
  const counts = useMemo(() => rows.reduce((a, { r }) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {}), [rows]);
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b bg-muted/30 px-3 py-2">
        <div className="min-w-0">
          <div className="font-mono text-xs font-semibold break-all">{name}</div>
          {meta?.extract && <div className="font-mono text-[10px] text-muted-foreground break-all">{meta.extract}</div>}
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          {Object.entries(counts).map(([s, n]) => <Badge key={s} status={s}>{n} {s}</Badge>)}
        </div>
      </div>
      <ul>
        {rows.map(({ r, i }) => <Item key={i} row={r} idx={i} openKey={openKey} setOpenKey={setOpenKey} />)}
      </ul>
    </Card>
  );
}

function Rows({ step }) {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('all');
  const [openKey, setOpenKey] = useState(null);
  const rows = step.rows || [];
  const grouped = rows.some(r => r.group);
  const statuses = useMemo(() => ['all', ...Object.keys(step.counts || {})], [step]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .map((r, i) => ({ r, i }))
      .filter(({ r }) => status === 'all' || r.status === status)
      .filter(({ r }) => !needle ||
        `${r.ref} ${r.tag} ${r.group} ${r.detail} ${r.reason}`.toLowerCase().includes(needle));
  }, [rows, q, status]);

  // Preserve source order (the run's order), not first-seen-filtered order.
  const groups = useMemo(() => {
    const m = new Map();
    shown.forEach(x => {
      const g = x.r.group || '(ungrouped)';
      if (!m.has(g)) m.set(g, []);
      m.get(g).push(x);
    });
    return [...m.entries()];
  }, [shown]);

  if (!rows.length) return null;
  return (
    <div className="mt-4">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input placeholder="Filter by name, source, lens, or reason…" value={q}
               onChange={e => setQ(e.target.value)} />
        <div className="flex flex-wrap gap-1 rounded-md bg-muted p-1">
          {statuses.map(s => (
            <button key={s} onClick={() => setStatus(s)}
              className={cn('rounded-sm px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap',
                status === s ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
              {s}{s !== 'all' && <span className="ml-1.5 opacity-60">{step.counts[s]}</span>}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">Nothing matches that filter.</Card>
      ) : grouped ? (
        <>
          <p className="mb-2 text-xs text-muted-foreground">
            {shown.length} of {rows.length} items across {groups.length} source{groups.length === 1 ? '' : 's'}
            {rows.some(r => r.data) && ' — click an item for its full record'}
          </p>
          <div className="space-y-3">
            {groups.map(([name, rs]) => (
              <SourceGroup key={name} name={name} meta={step.groups?.[name]} rows={rs}
                           openKey={openKey} setOpenKey={setOpenKey} />
            ))}
          </div>
        </>
      ) : (
        <Card className="overflow-hidden">
          <ul>{shown.map(({ r, i }) => <Item key={i} row={r} idx={i} openKey={openKey} setOpenKey={setOpenKey} />)}</ul>
          <div className="border-t p-3 text-xs text-muted-foreground">Showing {shown.length} of {rows.length}</div>
        </Card>
      )}
    </div>
  );
}

function App() {
  const [active, setActive] = useState(0);
  const steps = TRACE.steps || [];
  const step = steps[active];

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-8">
      <header className="mb-6">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">bramber trace</h1>
          <code className="rounded bg-muted px-2 py-0.5 text-sm">{TRACE.command}</code>
          <span className="text-sm text-muted-foreground">{TRACE.started_at}</span>
        </div>
        <p className="mt-1 font-mono text-xs text-muted-foreground break-all">{TRACE.root}</p>
        {Object.keys(TRACE.args || {}).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(TRACE.args).map(([k, v]) => (
              <span key={k} className="rounded-md border bg-card px-2 py-1 text-xs">
                <span className="text-muted-foreground">{k}</span>{' '}
                <span className="font-mono">{String(v)}</span>
              </span>
            ))}
          </div>
        )}
      </header>

      <nav className="mb-6 flex flex-wrap gap-2">
        {steps.map((s, i) => (
          <button key={i} onClick={() => setActive(i)}
            className={cn('rounded-md border px-3 py-2 text-left text-sm transition-colors',
              i === active ? 'border-primary bg-primary text-primary-foreground' : 'bg-card hover:bg-accent')}>
            <span className="opacity-60 mr-1.5 text-xs">{i + 1}</span>
            <span className="font-medium">{s.name}</span>
            {s.rows.length > 0 && <span className="ml-1.5 text-xs opacity-70">({s.rows.length})</span>}
          </button>
        ))}
      </nav>

      {!step ? <Card className="p-8 text-center text-muted-foreground">No steps recorded.</Card> : (
        <section>
          <div className="mb-4">
            <h2 className="text-lg font-semibold">{step.name}</h2>
            {step.summary && <p className="text-sm text-muted-foreground">{step.summary}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {Object.entries(step.counts || {}).map(([s, n]) => <Badge key={s} status={s}>{n} {s}</Badge>)}
              {step.duration_ms != null && <span className="text-xs text-muted-foreground">{step.duration_ms} ms</span>}
            </div>
          </div>

          {step.notes?.length > 0 && (
            <Card className="mb-4 p-4">
              <ul className="list-inside list-disc space-y-1 text-sm">
                {step.notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </Card>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <KeyValues title="Input" obj={step.inputs} />
            <KeyValues title="Output" obj={step.outputs} />
          </div>

          <Rows step={step} />
        </section>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body>
</html>
"""
