# SPDX-License-Identifier: MIT
"""The v3 design as the home (docs/review/promote-v3.md): screenshots and the redirect, headless Chromium as `build` on
the server, from the repository root:

  python3 -I docs/evidence/2026-10-18/promote-v3/shots_promote.py [--out DIR] [--before TREE]

Serves this tree with web/site/tests/serve.py (production's CSP, the API from fixtures, set as the live deployment is:
direct sends, SealLog, pay to open). home: / at 1440 and 390, dark (the page's default) and light (a stored choice),
the first screen and the whole page after scrolling through it (in parts when it is taller than one capture), and the
header's tile. v2: /v2 at 1440 and 390, the first screen and the whole page, with reduced motion so the loops show
their posters and every capture is the same each time; with --before (a tree of the commit before this pass, e.g. a
`git archive origin/main`), the same captures of that tree's /v2 and a pixel comparison (PNG bytes from the same
Chromium) in v2-compare.json. v3: /v3 and /v3/ asked for without following redirects (status and Location), then
opened in the browser (where it lands), in redirect.json and v3-redirect-1440.webp.
"""
import argparse
import base64
import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "web/site/tools")]
from cdp import Browser  # noqa: E402

SIZES = {1440: (1440, 900, False), 390: (390, 844, True)}
LIGHT = "try { localStorage.setItem('mutis.theme', 'light'); } catch (e) {}"
DARK = "try { localStorage.removeItem('mutis.theme'); } catch (e) {}"   # no choice made: the page's own default
PART = 6000   # Chromium draws at most 8,192 px in one capture (a taller one repeats its top), so a long page comes in parts


def serve(tree: Path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-I", str(tree / "web/site/tests/serve.py"), "--port", str(port),
                             "--mode", "direct", "--seallog", "--pay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    origin = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(origin + "/robots.txt", timeout=1).read()
            return proc, origin
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit(f"serve.py from {tree} didn't start")


def new_page(b, width, height, mobile, light=False, reduce=False):
    page = b.page(width, height, mobile=mobile, android=mobile, reduce=reduce)
    page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": LIGHT if light else DARK})
    return page


def through(page):
    h = page.height * 0.5
    end = int(page.eval("document.documentElement.scrollHeight"))
    for y in range(0, end + int(h), int(h)):
        page.scroll_to(y, 0.5)
    page.b.pump(1.5)
    page.scroll_to(0, 1.0)


def capture(page, clip, fmt="webp"):
    params = {"format": fmt, "captureBeyondViewport": True, "clip": {**clip, "scale": 1}}
    if fmt == "webp":
        params["quality"] = 82
    return base64.b64decode(page.cmd("Page.captureScreenshot", params)["data"])


def full(page, path, fmt="webp"):
    """The whole page, in parts of PART px when taller than 8,000 px; returns the files written and their bytes."""
    h = page.eval("document.documentElement.scrollHeight")
    clips = [{"x": 0, "y": y, "width": page.width, "height": min(PART, h - y)} for y in range(0, h, PART)] if h > 8000 \
        else [{"x": 0, "y": 0, "width": page.width, "height": h}]
    written = []
    for i, clip in enumerate(clips):
        data = capture(page, clip, fmt)
        name = path.with_suffix(f".{fmt}") if len(clips) == 1 else path.parent / f"{path.stem}-{i + 1}.{fmt}"
        if fmt == "webp":
            name.write_bytes(data)
        written.append((name.name, data))
    return written, h


def home(b, origin, out):
    notes = []
    for w, (width, height, mobile) in SIZES.items():
        for theme in ("dark", "light"):
            page = new_page(b, width, height, mobile, light=theme == "light")
            page.goto(origin + "/", settle=3.0)
            page.screenshot(str(out / f"home-{w}-{theme}.webp"))
            page.screenshot_element(".site-header .wm", str(out / f"home-{w}-{theme}-mark.png"))
            through(page)
            files, h = full(page, out / f"home-{w}-{theme}-full")
            notes.append({"page": "/", "width": w, "theme": page.eval("document.documentElement.dataset.theme"),
                          "height": h, "files": [f for f, _ in files]})
            page.close()
    return notes


def v2(b, origin, out, tag):
    """/v2 with reduced motion (posters, no reveals): the same pixels on every run of the same tree."""
    shots = {}
    for w, (width, height, mobile) in SIZES.items():
        page = new_page(b, width, height, mobile, reduce=True)
        page.goto(origin + "/v2", settle=3.0)
        through(page)
        first = capture(page, {"x": 0, "y": 0, "width": width, "height": height}, "png")
        if tag == "after":
            (out / f"v2-{w}.webp").write_bytes(capture(page, {"x": 0, "y": 0, "width": width, "height": height}))
            full(page, out / f"v2-{w}-full")
        files, h = full(page, out / f"v2-{w}-full-{tag}", fmt="png")
        shots[w] = {"height": h, "first_screen_sha256": hashlib.sha256(first).hexdigest(),
                    "full_sha256": [hashlib.sha256(d).hexdigest() for _, d in files]}
        page.close()
    return shots


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def v3(b, origin, out):
    report = {}
    for path in ("/v3", "/v3/"):
        try:
            with urllib.request.build_opener(NoRedirect).open(origin + path, timeout=10) as r:
                report[path] = {"status": r.status, "location": r.headers.get("Location")}
        except urllib.error.HTTPError as e:
            report[path] = {"status": e.code, "location": e.headers.get("Location")}
    page = new_page(b, 1440, 900, False)
    page.goto(origin + "/v3", settle=3.0)
    report["browser"] = {"asked": "/v3", "landed": page.eval("location.pathname"), "title": page.eval("document.title"),
                         "body": page.eval("document.body.className")}
    page.screenshot(str(out / "v3-redirect-1440.webp"))
    page.close()
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--before", type=Path, help="a tree of the commit before this pass, for /v2's pixel comparison")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    proc, origin = serve(ROOT)
    report = {}
    try:
        with Browser() as b:
            report["home"] = home(b, origin, args.out)
            report["v3"] = v3(b, origin, args.out)
            report["v2_after"] = v2(b, origin, args.out, "after")
        if args.before:
            proc_b, origin_b = serve(args.before)
            try:
                with Browser() as b:
                    report["v2_before"] = v2(b, origin_b, args.out, "before")
            finally:
                proc_b.kill()
            report["v2_same_pixels"] = {w: report["v2_before"][w] == report["v2_after"][w] for w in SIZES}
            (args.out / "v2-compare.json").write_text(json.dumps({k: report[k] for k in ("v2_before", "v2_after", "v2_same_pixels")},
                                                                 indent=1) + "\n")
        (args.out / "redirect.json").write_text(json.dumps(report["v3"], indent=1) + "\n")
        (args.out / "shots.json").write_text(json.dumps(report["home"], indent=1) + "\n")
    finally:
        proc.kill()
    for f in args.out.glob("v2-*-full-*.png"):
        f.unlink()   # the comparison's raw captures: their hashes are in v2-compare.json
    print(json.dumps({k: v for k, v in report.items() if k in ("v3", "v2_same_pixels")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
