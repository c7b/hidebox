# SPDX-License-Identifier: MIT
"""The home's hero after the tagline change (docs/review/tagline-2.md), as `build` on the server, from a copy of the
repository:

  python3 -I docs/evidence/2026-10-21/tagline-2/shots_tagline.py --out DIR

The UI suite's harness (web/app/ui/tests/run.py: the build, the real API on a dev server, headless Chromium) serves
the tree. The first screen of / at 1440 × 900 (a computer) and 390 × 844 (a phone, pictured at 1.5×), dark and
light (data-theme), as hero-<width>-<theme>.webp. Then the hero's three lines measured at 360, 390, 768, 960, 1024,
1100, 1180, 1280 and 1440 px in both themes (hero-metrics.json): each line's text, font size and weight, colour,
contrast on the page, rendered line count and box, and where Open your drive sits against the first screen. Python
stdlib only.
"""
import argparse
import base64
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TESTS = ROOT / "web/app/ui/tests"
sys.path.insert(0, str(TESTS))
os.chdir(ROOT)
import run  # noqa: E402
from cdp import DEVICES  # noqa: E402
from cdp import Browser  # noqa: E402

SHOTS = {1440: "desktop", 390: "iphone"}
MEASURE = ((360, 740, True), (390, 844, True), (768, 1024, True), (960, 720, False), (1024, 768, False), (1100, 800, False),
           (1180, 820, False), (1280, 800, False), (1440, 900, False))
THEMES = ("dark", "light")

# Each line of the hero's words: its text, type, colour, contrast against the page behind it, and how many lines it
# wraps to (its client rects, one per line box). The colour of the page is the hero's computed background, else the
# body's (the hero is transparent on the page).
METRICS = """(() => {
  const rgb = (s) => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number);
  const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= .03928 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; };
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return Math.round((x + .05) / (y + .05) * 100) / 100; };
  const bg = rgb(getComputedStyle(document.body).backgroundColor);
  const line = (el) => {
    if (!el) return null;
    const s = getComputedStyle(el);
    const range = document.createRange(); range.selectNodeContents(el);
    const tops = new Set([...range.getClientRects()].filter((r) => r.width > 1).map((r) => Math.round(r.top)));
    const b = el.getBoundingClientRect();
    return { text: el.textContent.trim(), size: parseFloat(s.fontSize), weight: s.fontWeight, color: s.color,
             contrast: ratio(rgb(s.color), bg), lines: tops.size, box: [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)] };
  };
  const h1 = document.querySelector('#hero-h');
  const head = h1 && h1.firstChild ? (() => { const r = document.createRange(); r.setStart(h1.firstChild, 0); r.setEnd(h1.firstChild, h1.firstChild.length);
    const tops = new Set([...r.getClientRects()].filter((x) => x.width > 1).map((x) => Math.round(x.top)));
    const s = getComputedStyle(h1); return { text: h1.firstChild.nodeValue.trim(), size: parseFloat(s.fontSize), weight: s.fontWeight,
      color: s.color, contrast: ratio(rgb(s.color), bg), lines: tops.size }; })() : null;
  const cta = [...document.querySelectorAll('.hero .cta-row a')].find((a) => a.checkVisibility());
  const c = cta ? cta.getBoundingClientRect() : null;
  return { width: innerWidth, theme: document.documentElement.dataset.theme, page: getComputedStyle(document.body).backgroundColor,
           headline: head, subline: line(document.querySelector('#hero-h .h1-2')), third: line(document.querySelector('.hero .hero-line')),
           lede: line(document.querySelector('.hero .lede')), note: line(document.querySelector('.hero .hero-note')),
           cta_bottom: c ? Math.round(c.bottom) : null, fold: innerHeight,
           overflow: document.documentElement.scrollWidth > innerWidth };
})()"""


def theme(page, which):
    page.eval(f"document.documentElement.dataset.theme = {which!r}")
    time.sleep(0.4)


def capture(page, path):
    """The first screen; a phone at 1.5× (its device pixels are 3×)."""
    d = page.device
    page.settle()
    clip = {"x": 0, "y": 0, "width": d["width"], "height": d["height"], "scale": 1 if d["dpr"] == 1 else 1.5 / d["dpr"]}
    data = page.cmd("Page.captureScreenshot", {"format": "webp", "quality": 82, "captureBeyondViewport": True, "clip": clip}, timeout=90)["data"]
    Path(path).write_bytes(base64.b64decode(data))
    print(f"  shot {Path(path).name}", flush=True)


def home(t, page):
    page.goto(t.origin + "/")
    page.wait("document.readyState === 'complete'", 30)
    time.sleep(1.6)                         # the hero's arrival: each line rises within 700 ms of the last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = tempfile.mkdtemp(prefix="mutis-tagline-shots-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    port = run.free_port()
    dist = run.build(work, f"http://127.0.0.1:{port}")
    server = run.serve(dist, os.path.join(work, "data"), port)
    browser = Browser()
    metrics = []
    try:
        t = run.T(run.Results(), browser, f"http://127.0.0.1:{port}", work, None)
        for width, device in SHOTS.items():
            p = t.actor(device)
            home(t, p)
            for th in THEMES:
                theme(p, th)
                capture(p, out / f"hero-{width}-{th}.webp")
        for width, height, mobile in MEASURE:
            p = t.actor("desktop")
            p.device = {**DEVICES["desktop"], "width": width, "height": height, "mobile": mobile}
            p.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
            home(t, p)
            for th in THEMES:
                theme(p, th)
                metrics.append(p.eval(METRICS))
        t.close()
    finally:
        browser.close()
        server.terminate()
        server.wait(10)
        shutil.rmtree(work, ignore_errors=True)
    (out / "hero-metrics.json").write_text(json.dumps(metrics, indent=1) + "\n")
    for m in metrics:
        lines = {k: (m[k]["lines"], m[k]["size"], m[k]["contrast"]) for k in ("headline", "subline", "third", "lede", "note") if m.get(k)}
        print(f"  {m['width']} {m['theme']}: {lines} cta bottom {m['cta_bottom']} / fold {m['fold']}, overflow {m['overflow']}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
