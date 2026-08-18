"""
Intake server for a bramber project.

Serves a small HTML page on http://localhost:47825 that accepts file uploads
(drag-and-drop) and URL submissions. Files land in <root>/_bramber/inbox/. Links
become single-line text files in the same inbox, ready for the fetch/normalize
step of `/bramber:orchestrate`.

Launched by the /bramber:intake slash command (or `bramber intake`). Stops when the
user clicks "Done" in the browser, times out ~90s after the last heartbeat, or is
killed manually. Ported from the predecessor factory's engine/intake_server.py.
bramber takes 47825, deliberately clear of the 4782x band the author's other
intake servers occupy, so several projects can run side by side.

Stdlib-only, like everything reachable from the bramber package — but this module is
never imported by the sync path; it runs only as a dedicated process.
"""

import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

PORT = 47825
IDLE_TIMEOUT = 90  # seconds without a browser heartbeat before self-shutdown

# Set by _configure() at startup — module import has no filesystem side effects,
# so importing this file (e.g. from a test) never creates directories.
ROOT: Path | None = None
INBOX: Path | None = None
last_heartbeat = time.time()


def _configure(root=None) -> None:
    """Resolve the project root ($BRAMBER_ROOT > cwd) and ensure the inbox exists."""
    global ROOT, INBOX
    ROOT = Path(root or os.environ.get("BRAMBER_ROOT") or Path.cwd()).resolve()
    INBOX = ROOT / "_bramber" / "inbox"
    INBOX.mkdir(parents=True, exist_ok=True)


HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>bramber - Intake</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 640px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }
  h1 { font-size: 1.15em; font-weight: 600; margin-bottom: 4px; }
  .sub { color: #666; font-size: 0.9em; margin-bottom: 24px; }
  .drop { border: 2px dashed #aaa; border-radius: 8px; padding: 60px 20px;
          text-align: center; color: #666; transition: all 0.15s;
          cursor: pointer; margin: 16px 0; }
  .drop.over { background: #eef6ff; border-color: #2080ff; color: #2080ff; }
  .link-row { display: flex; gap: 8px; margin: 16px 0; }
  .link-row input { flex: 1; padding: 8px 12px; font-size: 14px;
                    border: 1px solid #ccc; border-radius: 4px; }
  button { padding: 8px 16px; font-size: 14px; background: #2080ff;
           color: white; border: none; border-radius: 4px; cursor: pointer; }
  button:hover { background: #1060df; }
  button.secondary { background: transparent; color: #666;
                     border: 1px solid #ccc; }
  button.secondary:hover { background: #f5f5f5; }
  #status { margin: 16px 0; min-height: 20px; font-size: 14px; font-family: monospace; }
  .status-success { color: #1a8a3a; }
  .status-error { color: #c8242a; }
  .footer { margin-top: 32px; display: flex; justify-content: space-between;
            align-items: center; }
  .hint { font-size: 0.85em; color: #888; }
</style>
</head>
<body>
<h1>Drop a file or paste a link</h1>
<div class="sub">Lands in <code>_bramber/inbox/</code>. Run <code>/bramber:orchestrate</code> next.</div>

<div class="drop" id="drop">
  Drop files here, click to pick, or paste from clipboard
  <input type="file" id="picker" multiple style="display:none">
</div>

<div class="link-row">
  <input type="url" id="url" placeholder="https://...">
  <button id="submitUrl">Save link</button>
</div>

<div id="status"></div>

<div class="footer">
  <span class="hint">Server: localhost:47825</span>
  <button class="secondary" id="done">Done (stop server)</button>
</div>

<script>
const drop = document.getElementById('drop');
const picker = document.getElementById('picker');
const statusEl = document.getElementById('status');
const urlInput = document.getElementById('url');

drop.addEventListener('click', () => picker.click());
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', async e => {
  e.preventDefault();
  drop.classList.remove('over');
  for (const f of e.dataTransfer.files) await uploadFile(f);
});
picker.addEventListener('change', async e => {
  for (const f of e.target.files) await uploadFile(f);
  picker.value = '';
});

document.addEventListener('paste', async e => {
  for (const item of e.clipboardData.items) {
    if (item.kind === 'file') {
      const f = item.getAsFile();
      if (f) await uploadFile(f);
    } else if (item.kind === 'string' && item.type === 'text/plain') {
      item.getAsString(s => {
        const trimmed = s.trim();
        if (/^https?:\\/\\//.test(trimmed)) urlInput.value = trimmed;
      });
    }
  }
});

async function uploadFile(file) {
  setStatus(`Uploading ${file.name}...`);
  try {
    const r = await fetch('/upload', {
      method: 'POST',
      headers: { 'X-Filename': encodeURIComponent(file.name) },
      body: file
    });
    const data = await r.json();
    if (r.ok && data.saved) setStatus(`Saved: ${data.saved}`, 'success');
    else setStatus(`Error: ${data.error || r.statusText}`, 'error');
  } catch (err) {
    setStatus(`Error: ${err.message}`, 'error');
  }
}

document.getElementById('submitUrl').addEventListener('click', submitUrl);
urlInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitUrl(); });

async function submitUrl() {
  const url = urlInput.value.trim();
  if (!url) return;
  setStatus(`Saving link...`);
  try {
    const r = await fetch('/link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await r.json();
    if (r.ok && data.saved) {
      setStatus(`Saved: ${data.saved}`, 'success');
      urlInput.value = '';
    } else setStatus(`Error: ${data.error || r.statusText}`, 'error');
  } catch (err) {
    setStatus(`Error: ${err.message}`, 'error');
  }
}

let alive = true;
const HEARTBEAT_MS = 30000;

function heartbeat() {
  if (!alive) return;
  fetch('/heartbeat', { method: 'POST', keepalive: true }).catch(() => {});
}
heartbeat();
const heartbeatTimer = setInterval(heartbeat, HEARTBEAT_MS);

window.addEventListener('pagehide', () => {
  if (alive) navigator.sendBeacon('/shutdown');
});

document.getElementById('done').addEventListener('click', async () => {
  alive = false;
  clearInterval(heartbeatTimer);
  try { await fetch('/shutdown', { method: 'POST' }); } catch (e) {}
  setStatus('Server stopped. You can close this tab.', 'success');
});

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = kind ? 'status-' + kind : '';
}
</script>
</body>
</html>
"""


def slugify(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:max_len] if s else "x"


def safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._")
    return name[:200] or "unnamed"


def unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return target.with_name(f"{target.stem}-{ts}{target.suffix}")


class IntakeHandler(http.server.BaseHTTPRequestHandler):
    def _json(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        global last_heartbeat
        last_heartbeat = time.time()
        if self.path == "/upload":
            self._handle_upload()
        elif self.path == "/link":
            self._handle_link()
        elif self.path == "/heartbeat":
            self._json(200, {"ok": True})
        elif self.path == "/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=self._delayed_shutdown, daemon=True).start()
        else:
            self._json(404, {"error": "not found"})

    def _handle_upload(self) -> None:
        raw = self.headers.get("X-Filename", "")
        try:
            name = urllib.parse.unquote(raw)
        except Exception:
            name = raw
        filename = safe_filename(name)
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        data = self.rfile.read(length)
        target = unique_path(INBOX / filename)
        target.write_bytes(data)
        print(f"[intake] saved file: {target.name} ({len(data)} bytes)")
        self._json(200, {"saved": target.name})

    def _handle_link(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._json(400, {"error": f"bad json: {e}"})
            return
        url = (body.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            self._json(400, {"error": "url must be http(s) with a host"})
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = slugify(parsed.netloc + parsed.path)
        target = unique_path(INBOX / f"link-{ts}-{slug}.txt")
        target.write_text(url + "\n", encoding="utf-8")
        print(f"[intake] saved link: {target.name} -> {url}")
        self._json(200, {"saved": target.name})

    def _delayed_shutdown(self) -> None:
        time.sleep(0.3)
        print("[intake] shutdown requested via browser")
        os._exit(0)

    def log_message(self, *_args, **_kwargs) -> None:
        return


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _watchdog() -> None:
    while True:
        time.sleep(5)
        if time.time() - last_heartbeat > IDLE_TIMEOUT:
            print(f"[intake] no heartbeat for {IDLE_TIMEOUT}s, exiting")
            os._exit(0)


def main(root=None) -> None:
    global last_heartbeat
    _configure(root)
    url = f"http://localhost:{PORT}"
    print(f"[intake] serving on {url}")
    print(f"[intake] inbox: {INBOX}")
    try:
        httpd = ReusableTCPServer(("localhost", PORT), IntakeHandler)
    except OSError as e:
        print(f"[intake] could not bind {PORT}: {e}")
        print("[intake] is the server already running? open the existing tab "
              f"at {url}, or close the other process and retry.")
        sys.exit(1)
    last_heartbeat = time.time()
    threading.Thread(target=_watchdog, daemon=True).start()
    if not os.environ.get("INTAKE_NO_BROWSER"):
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[intake] interrupted")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
