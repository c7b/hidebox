#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Self-test of the E2E driver (cdp.py, harness.py) before any scenario depends on it.

  python3 -I tests/e2e/test_harness.py [--host ultron]

Serves a small page that follows the data-testid conventions on the server's loopback (as build,
with the app CSP), then drives it with the same primitives the scenarios use: pointer and touch
clicks, typing, a file input, a download (hashed on the server), keyboard focus, the accessibility
tree, data-state waits, and capture of requests and CSP violations.
"""
import argparse
import hashlib
import shlex
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp  # noqa: E402
import headers_spec  # noqa: E402
from harness import REMOTE_DIR, Env, Remote, T  # noqa: E402

PORT = 18081
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>driver self-test</title>
<script type="module" src="/page.js"></script></head><body>
<main data-testid="view-root" data-state="ready">
<button data-testid="view-open" type="button">Open it</button>
<input data-testid="drop-input" type="file" aria-label="Choose a file">
<textarea data-testid="drop-textarea" aria-label="Text"></textarea>
<button data-testid="who" value="link" type="button">Link</button><button data-testid="who" value="password" type="button">Password</button>
<a data-testid="view-save" href="/file.bin" download="file.bin">Save file</a>
<p role="status" class="md-live"></p></main></body></html>"""
SCRIPT = """const root = document.querySelector('[data-testid="view-root"]');
document.querySelector('[data-testid="view-open"]').addEventListener('click', () => { root.dataset.state = 'opened'; });
document.querySelectorAll('[data-testid="who"]').forEach(b => b.addEventListener('click', () => { root.dataset.who = b.value; }));
document.querySelector('[data-testid="drop-input"]').addEventListener('change', e => {
  document.querySelector('.md-live').textContent = 'chose ' + e.target.files[0].name; });
fetch('/ping', {method: 'POST', body: 'hello'});
const s = document.createElement('img'); s.src = 'https://example.invalid/x.png'; document.body.append(s);"""
SERVER = f"""
import http.server, os
CSP = {headers_spec.APP_CSP!r}
FILES = {{'/': ('text/html', {PAGE!r}.encode()), '/page.js': ('text/javascript', {SCRIPT!r}.encode()),
         '/file.bin': ('application/octet-stream', bytes(range(256)) * 4096), '/ping': ('text/plain', b'ok')}}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self):
        kind, body = FILES.get(self.path, ('text/plain', b'missing'))
        self.send_response(200); self.send_header('Content-Type', kind); self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Security-Policy', CSP); self.end_headers(); self.wfile.write(body)
    do_GET = reply
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0))); self.reply()
http.server.ThreadingHTTPServer(('127.0.0.1', {PORT}), H).serve_forever()
"""


def run(env: Env) -> list[tuple[str, bool]]:
    results = []
    t = T(env, "harness")
    try:
        for device in ("desktop", "iphone"):
            page = t.actor(device)
            page.goto(f"http://127.0.0.1:{PORT}/")
            page.wait_for("view-open")
            page.click("view-open")
            results.append((f"{device}: a {'touch' if device == 'iphone' else 'pointer'} press runs the handler",
                            page.wait_state("view-root", ("opened",), 10) == "opened"))
            page.choose("who", "password")
            results.append((f"{device}: choose() picks a button by value", page.attr("view-root", "data-who") == "password"))
            page.fill("drop-textarea", "typed text ✓")
            results.append((f"{device}: fill() types into a textarea", page.value("drop-textarea") == "typed text ✓"))
            page.set_files("drop-input", [t.fixture("notes.txt")])
            results.append((f"{device}: set_files() hands the server's file to the input",
                            page.wait("document.querySelector('.md-live').textContent", 10) == "chose notes.txt"))
            page.click("view-save")
            want = hashlib.sha256(bytes(range(256)) * 4096).hexdigest()
            results.append((f"{device}: a download lands on the server with the right SHA-256", t.download_sha256(page) == want))
            page.collect()
            results.append((f"{device}: requests and their bodies are captured",
                            any(r["url"].endswith("/ping") and r["body"] == "hello" for r in page.requests)))
            results.append((f"{device}: the CSP violation of a remote image is reported", bool(page.csp_violations())))
            results.append((f"{device}: the accessibility tree has named buttons",
                            any((n.get("name") or {}).get("value") == "Open it" for n in page.ax_tree())))
        desk = t.actor()
        desk.goto(f"http://127.0.0.1:{PORT}/")
        desk.wait_for("view-open")
        desk.key("Tab")
        results.append(("Tab moves focus to the first control",
                        desk.eval("document.activeElement?.dataset?.testid") == "view-open"))
    finally:
        t.close()
    return results


def main() -> int:
    p = argparse.ArgumentParser(description="E2E driver self-test")
    p.add_argument("--host", default="ultron")
    args = p.parse_args()
    env = Env("http://127.0.0.1", Remote(args.host, Path(tempfile.mkdtemp(prefix="mutis-harness-"))), Path("."))
    env.stage()
    env.remote.as_build(f"cat > {REMOTE_DIR}/selftest_server.py", SERVER.encode())
    env.remote.run(f"sudo -iu build bash -c {shlex.quote(f'cd {REMOTE_DIR} && (setsid python3 -I selftest_server.py >/dev/null 2>&1 &)')}")
    time.sleep(1)
    try:
        results = run(env)
    finally:
        env.remote.run("sudo pkill -u build -f selftest_server.py", check=False)
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    failed = [n for n, ok in results if not ok]
    print(f"test_harness: {'PASS' if not failed else 'FAIL'} ({len(results) - len(failed)}/{len(results)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
