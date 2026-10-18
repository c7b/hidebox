# SPDX-License-Identifier: MIT
"""The headline candidates (docs/review/copy-1.md): each set as the hero's second line (.h1-2) on the home of a tree's test
server, at 390, 1440, 360 and 1280, in headless Chromium as `build` on the server: its text width and how many lines it takes.

  python3 -I docs/evidence/2026-10-18/copy-1/tagline_candidates.py TREE CANDIDATES.json > tagline-candidates.json
"""
import json, socket, subprocess, sys, time, urllib.request
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(ROOT / "web/site/tools")]
from cdp import Browser
CANDS = json.loads(Path(sys.argv[2]).read_text())
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
proc = subprocess.Popen([sys.executable, "-I", str(ROOT / "web/site/tests/serve.py"), "--port", str(port), "--mode", "direct", "--seallog", "--pay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
origin = f"http://127.0.0.1:{port}"
for _ in range(80):
    try:
        urllib.request.urlopen(origin + "/robots.txt", timeout=1).read(); break
    except OSError:
        time.sleep(0.25)
out = {}
JS = """((cands) => { const el = document.querySelector('.h1-2'); const cs = getComputedStyle(el); const lh = parseFloat(cs.lineHeight);
  const r = {font: cs.fontSize + ' ' + cs.fontWeight, lh, width: el.getBoundingClientRect().width, cands: {}};
  for (const c of cands) { el.textContent = c; const range = document.createRange(); range.selectNodeContents(el);
    const lines = new Set([...range.getClientRects()].map(x => Math.round(x.top))).size;
    const span = document.createElement('span'); span.textContent = c; span.style.whiteSpace = 'nowrap'; el.textContent = ''; el.appendChild(span);
    r.cands[c] = {lines, textWidth: Math.round(span.getBoundingClientRect().width)}; }
  return JSON.stringify(r); })"""
try:
    with Browser() as b:
        for width, height, mobile in ((390, 844, True), (1440, 900, False), (360, 780, True), (1280, 800, False)):
            page = b.page(width, height, mobile=mobile, android=mobile, reduce=True)
            page.goto(origin + "/", settle=2.0)
            out[width] = json.loads(page.eval(f"{JS}({json.dumps(CANDS)})"))
            page.close()
finally:
    proc.kill()
print(json.dumps(out, indent=1))
