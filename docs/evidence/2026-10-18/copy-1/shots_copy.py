# SPDX-License-Identifier: MIT
"""The copy pass (docs/review/copy-1.md): screenshots and the headline's measure, headless Chromium as `build` on
the server, from the repository root:

  python3 -I docs/evidence/2026-10-18/copy-1/shots_copy.py [--out DIR] [--before TREE]

Serves this tree with web/site/tests/serve.py (production's CSP, the API from fixtures, set as the live deployment is:
direct sends, SealLog, pay to open). The home at 1440 and 390, dark (the page's default) and light (a stored choice):
the first screen (`home-{w}-{theme}.webp`) and the whole page after scrolling through it (`-full`, in parts when it is
taller than one capture); /how and /judges at both widths, light, the first screen and the whole page. headline.json:
for the hero's h1 at 360, 390, 1280 and 1440, the second line's font, box width, text width and how many lines it
takes. statements.json: on /, /how and /judges at 1440 (the page's visible text, document.body.innerText, after the
deployment's variants), its words and how many times each key statement of DESIGN.md's Say It Once rule shows.
With --before (a tree of the commit before this pass), the same home first screens as `before-home-*`, and the
headline and statements of that tree.
"""
import argparse
import base64
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "web/site/tools")]
from cdp import Browser  # noqa: E402

SIZES = {1440: (1440, 900, False), 390: (390, 844, True)}
LIGHT = "try { localStorage.setItem('mutis.theme', 'light'); } catch (e) {}"
DARK = "try { localStorage.removeItem('mutis.theme'); } catch (e) {}"
PART = 6000
MEASURE = """(() => { const h1 = document.querySelector('#hero-h'), two = h1.querySelector('.h1-2'), cs = getComputedStyle(two);
  const lines = (el) => { const r = document.createRange(); r.selectNodeContents(el);
    return new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size; };
  const probe = document.createElement('span'); probe.textContent = two.textContent; probe.style.whiteSpace = 'nowrap';
  probe.style.position = 'absolute'; probe.style.visibility = 'hidden'; two.appendChild(probe);
  const width = Math.round(probe.getBoundingClientRect().width); probe.remove();
  return JSON.stringify({h1: h1.textContent.replace(/\\s+/g, ' ').trim(), font: cs.fontSize + ' ' + cs.fontWeight,
    box: Math.round(two.getBoundingClientRect().width), text: width, lines: lines(two)}); })()"""


def serve(tree: Path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-I", str(tree / "web/site/tests/serve.py"), "--port", str(port),
                             "--mode", "direct", "--seallog", "--pay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    origin = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(origin + "/robots.txt", timeout=1).read()
            return proc, origin
        except OSError:
            time.sleep(0.25)
    proc.kill()
    raise SystemExit(f"serve.py from {tree} didn't start")


def new_page(b, width, height, mobile, light=False):
    page = b.page(width, height, mobile=mobile, android=mobile)
    page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": LIGHT if light else DARK})
    return page


def through(page):
    h = page.height * 0.5
    end = int(page.eval("document.documentElement.scrollHeight"))
    for y in range(0, end + int(h), int(h)):
        page.scroll_to(y, 0.5)
    page.b.pump(1.5)
    page.scroll_to(0, 1.0)


def full(page, path):
    h = page.eval("document.documentElement.scrollHeight")
    clips = [{"x": 0, "y": y, "width": page.width, "height": min(PART, h - y)} for y in range(0, h, PART)] if h > 8000 \
        else [{"x": 0, "y": 0, "width": page.width, "height": h}]
    names = []
    for i, clip in enumerate(clips):
        data = base64.b64decode(page.cmd("Page.captureScreenshot", {"format": "webp", "quality": 82, "captureBeyondViewport": True,
                                                                      "clip": {**clip, "scale": 1}})["data"])
        name = path.with_suffix(".webp") if len(clips) == 1 else path.parent / f"{path.stem}-{i + 1}.webp"
        name.write_bytes(data)
        names.append(name.name)
    return names, h


def shoot(b, origin, out, prefix, pages=True):
    notes = []
    for w, (width, height, mobile) in SIZES.items():
        for theme in ("dark", "light"):
            page = new_page(b, width, height, mobile, light=theme == "light")
            page.goto(origin + "/", settle=3.0)
            page.screenshot(str(out / f"{prefix}home-{w}-{theme}.webp"))
            if pages:
                through(page)
                files, h = full(page, out / f"{prefix}home-{w}-{theme}-full")
                notes.append({"page": "/", "width": w, "theme": theme, "height": h, "files": files})
            page.close()
        if pages:
            for path in ("/how", "/judges"):
                page = new_page(b, width, height, mobile, light=True)
                page.goto(origin + path, settle=3.0)
                page.screenshot(str(out / f"{prefix}{path.strip('/')}-{w}.webp"))
                through(page)
                files, h = full(page, out / f"{prefix}{path.strip('/')}-{w}-full")
                notes.append({"page": path, "width": w, "theme": "light", "height": h, "files": files})
                page.close()
    return notes


STATEMENTS = {
    "1 the lock": r"locks? in (this|your) browser|locked right here|lock here, in your browser|locked before it leaves",
    "2 the server": r"scrambled noise",
    "3 the names": r"can't read your file names",
    "4 the exit rules": r"gets its own rule",
    "5 the chain hides the amount": r"hidden amount|hides the amount|amount and the owner are hidden",
    "6 the chain record": r"(write|wrote) that on the Tari chain|goes on the Tari chain",
    "7 no email, no password": r"no email, no password|no email|no password|no sign-up",
    "8 losing the key": r"nobody can let you back in",
    "the testnet line": r"worth nothing",
}


def statements(b, origin):
    out = {}
    for path in ("/", "/how", "/judges"):
        page = b.page(1440, 900, reduce=True)
        page.goto(origin + path, settle=3.0)
        text = page.eval("document.body.innerText")
        out[path] = {"words": len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’™.#-]*", text)),
                     **{k: len(re.findall(rx, text, re.I)) for k, rx in STATEMENTS.items()}}
        page.close()
    return out


def measure(b, origin):
    out = {}
    for width, height, mobile in ((360, 780, True), (390, 844, True), (1280, 800, False), (1440, 900, False)):
        page = b.page(width, height, mobile=mobile, android=mobile, reduce=True)
        page.goto(origin + "/", settle=2.0)
        out[width] = json.loads(page.eval(MEASURE))
        page.close()
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--before", type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {}
    proc, origin = serve(ROOT)
    try:
        with Browser() as b:
            report["after"] = shoot(b, origin, args.out, "")
            report["headline_after"] = measure(b, origin)
            report["statements_after"] = statements(b, origin)
    finally:
        proc.kill()
    if args.before:
        proc, origin = serve(args.before)
        try:
            with Browser() as b:
                shoot(b, origin, args.out, "before-", pages=False)
                report["headline_before"] = measure(b, origin)
                report["statements_before"] = statements(b, origin)
        finally:
            proc.kill()
    (args.out / "headline.json").write_text(json.dumps({k: v for k, v in report.items() if k.startswith("headline")}, indent=1) + "\n")
    (args.out / "statements.json").write_text(json.dumps({k: v for k, v in report.items() if k.startswith("statements")}, indent=1) + "\n")
    (args.out / "shots.json").write_text(json.dumps(report["after"], indent=1) + "\n")
    print(json.dumps(report.get("headline_after"), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
