# SPDX-License-Identifier: MIT
"""Brand kit 1 screenshots (docs/review/brand-kit-1.md), as `build` on the server, from a copy of the repository:

  python3 -I docs/evidence/2026-10-19/brand-kit-1/shots_brand.py --out DIR [--only 1440,390] [--surfaces LIST] [--readme DIR]

The UI suite's harness (web/app/ui/tests/run.py: the build, the real API on a dev server with its fake chain, headless
Chromium) serves the tree. Every surface that draws the mark, or the name as a logo, at 1440 × 900 (a computer) and
390 × 844 (a phone, pictured at 1.5×), in light and in dark (data-theme): the first screen of /, /how, /made,
/judges, /fine-print, a missing page and /v2; a link that doesn't exist (the link page's error); /drive with no drive
(the start card); the empty drive; the drive with two files (its sidebar; on the phone, in its sheet); Delivered on a
drop page; a folder link opened (its top bar); and the holding page (tools/build.py --holding). Close-ups at 4×,
PNG: the header's lockup on / (header-<width>-<theme>.png), the comparison's head (compare-1440-<theme>.png), the
drive's lockup (drive-mark-<width>-<theme>.png). WebP elsewhere, <surface>-<width>-<theme>.webp.

--readme DIR also makes the README's pictures in DIR: home.webp (/ at 1440 × 900, dark), drive.webp and share.webp
(960 × 600: the drive dark with notes.txt shared Once and agenda.txt kept Private; the share window's result light,
its QR blurred), and social-preview.png (1280 × 640, from social-preview.html beside this script: the kit's lockup,
the home's headline and the hero's still, set in the pinned Geist); and og-candidate.png, what og.png would be with the
kit's marks (og.png itself is kept as it is). Python stdlib only.
"""
import argparse
import base64
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TESTS = ROOT / "web/app/ui/tests"
sys.path.insert(0, str(TESTS))
os.chdir(ROOT)
import run  # noqa: E402
from cdp import DEVICES, Browser  # noqa: E402
import flows  # noqa: E402
import flows_drive  # noqa: E402
import flows_share  # noqa: E402

WIDTHS = {1440: "desktop", 390: "iphone"}
THEMES = ("dark", "light")
SITE = (("home", "/"), ("how", "/how"), ("made", "/made"), ("judges", "/judges"), ("fine-print", "/fine-print"),
        ("missing", "/no-such-page"), ("v2", "/v2"))
BLUR_QR = "document.querySelectorAll('[data-testid=\"share-qr\"] svg, [data-testid=\"share-qr\"] canvas, [data-testid=\"share-qr\"] img')" \
          ".forEach((e) => { e.style.filter = 'blur(7px)'; })"


def theme(page, which):
    page.eval(f"document.documentElement.dataset.theme = {which!r}")
    time.sleep(0.4)


def capture(page, path, clip=None, scale=None, fmt=None):
    """The viewport (or a clip of the page, in CSS pixels of the document), a phone at 1.5×."""
    d = page.device
    page.settle()
    fmt = fmt or ("png" if str(path).endswith(".png") else "webp")
    if clip is None:
        clip = {"x": 0, "y": page.eval("scrollY"), "width": d["width"], "height": d["height"]}
    params = {"format": fmt, "captureBeyondViewport": True, "clip": {**clip, "scale": scale or (1 if d["dpr"] == 1 else 1.5 / d["dpr"])}}
    if fmt == "webp":
        params["quality"] = 80
    data = page.cmd("Page.captureScreenshot", params, timeout=90)["data"]
    Path(path).write_bytes(base64.b64decode(data))
    print(f"  shot {Path(path).name}", flush=True)


def close_up(page, selector, path, pad=8):
    """`selector`'s box with `pad` px around it, at 4× (a close look at the mark)."""
    r = page.eval(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null;"
                  " const r = e.getBoundingClientRect(); return [r.left + scrollX, r.top + scrollY, r.width, r.height]; })()")
    if not r:
        print(f"  no {selector}", flush=True)
        return
    x, y, w, h = r
    capture(page, path, {"x": max(0, x - pad), "y": max(0, y - pad), "width": w + 2 * pad, "height": h + 2 * pad},
            scale=4 / page.device["dpr"])


def both(page, out, name, width, before=None):
    for th in THEMES:
        theme(page, th)
        if before:
            before(th)
        capture(page, out / f"{name}-{width}-{th}.webp")


def site(t, out, width):
    p = t.actor(WIDTHS[width])
    for name, path in SITE:
        p.goto(t.origin + path)
        p.wait("document.readyState === 'complete'", 30)
        time.sleep(1.6)                     # the hero's arrival and the reveals of the first screen
        both(p, out, name, width)
        if name == "home":
            for th in THEMES:
                theme(p, th)
                close_up(p, ".site-header .wm", out / f"header-{width}-{th}.png")
            if width == 1440:               # the comparison's head shows from 720 px (a phone reads each row as a card)
                p.eval("document.querySelector('.compare').scrollIntoView({ block: 'center' })")
                time.sleep(1.4)
                for th in THEMES:
                    theme(p, th)
                    close_up(p, ".compare thead .us", out / f"compare-{width}-{th}.png", pad=6)
                p.eval("window.scrollTo(0, 0)")
    p.goto(t.origin + "/s/AAAAAAAAAAAAAAAAAAAAAA#1" + "A" * 43)   # a link that doesn't exist: the link page's error
    p.wait_state("view-root", flows.VIEW_ASK + ("not-found", "error"), 60)
    time.sleep(1)
    both(p, out, "link-missing", width)


def drive(t, out, width):
    device = WIDTHS[width]
    s = t.actor(device)
    s.goto(t.origin + "/drive")
    s.wait_for("drive-start", 60)
    s.wait("(() => { const i = document.querySelector('[data-testid=\"start-pic\"] img'); return i && i.complete && i.naturalWidth > 0; })()", 30)
    both(s, out, "drive-start", width)
    for th in THEMES:
        theme(s, th)
        close_up(s, ".start-card .brand", out / f"drive-start-mark-{width}-{th}.png")
    a = flows_share.drive_page(t, device=device)
    a.wait_for("drive-empty", 30)
    time.sleep(1)
    both(a, out, "drive-empty", width)
    flows_drive.upload_files(t, a, ["notes.txt", "agenda.txt"])
    a.eval("document.querySelector('[data-testid=\"upload-panel\"] .uploads-head .btn')?.click()")
    time.sleep(1)
    if width == 1440:
        both(a, out, "drive", width)
        for th in THEMES:
            theme(a, th)
            close_up(a, "aside .sidebar-header", out / f"drive-mark-{width}-{th}.png")
    else:
        a.eval("document.querySelector('[data-sidebar-trigger]').click()")
        a.wait("!document.getElementById('side-sheet').hidden", 10)
        time.sleep(0.8)
        both(a, out, "drive-sheet", width)
        for th in THEMES:
            theme(a, th)
            close_up(a, "#side-sheet .sidebar-header", out / f"drive-mark-{width}-{th}.png")


def delivered(t, out, width):
    _, drop, _ = flows.owner_with_drop(t, device="desktop")
    b = t.actor(WIDTHS[width])
    b.goto(drop)
    b.wait_state("dd-root", ("ready",), 60)
    b.set_files("dd-input", [t.fixture("photo-gps.jpg")])
    b.wait_state("dd-root", ("delivered",), 240)
    b.eval("document.querySelector('[data-testid=\"dd-root\"] .done')?.scrollIntoView({ block: 'center' })")
    time.sleep(1.6)                         # the done moment runs once, about a second
    both(b, out, "delivered", width)


def folder(t, out, width):
    a = flows_share.drive_page(t)
    flows_share.folder_with_files(t, a)
    url = flows_share.share_folder(t, a, opens="few")
    v, _ = flows_share.stranger(t, url, device=WIDTHS[width])
    v.click("view-open")
    v.wait_for("folder-view", 60)
    time.sleep(1)
    both(v, out, "folder", width)
    for th in THEMES:
        theme(v, th)
        close_up(v, ".fv-top .brand", out / f"folder-mark-{width}-{th}.png")


def holding(browser, out, work, widths):
    """The holding page, built with --holding and served as files (it has no API)."""
    dist = Path(work) / "holding"
    res = subprocess.run([sys.executable, "-I", "tools/build.py", "--holding", "--origin", "http://127.0.0.1:8787", "--out", str(dist),
                          "--source", "0000000", "brand-shots", str(int(time.time())),
                          "--release", str(Path(work) / "holding-release")], capture_output=True, text=True)
    if res.returncode:
        print(f"  holding build failed: {res.stdout[-400:]} {res.stderr[-400:]}", flush=True)
        return
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(dist)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        t = run.T(run.Results(), browser, f"http://127.0.0.1:{httpd.server_port}", work, None)
        for width in widths:
            p = t.actor(WIDTHS[width])
            p.goto(t.origin + "/")
            time.sleep(1)
            both(p, out, "holding", width)
        t.close()
    finally:
        httpd.shutdown()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def readme(t, out, work):
    """The README's pictures: the home, the drive and the share window, and the repository's social card."""
    p = t.actor("desktop")
    p.goto(t.origin + "/")
    p.wait("document.readyState === 'complete'", 30)
    time.sleep(1.6)
    theme(p, "dark")
    capture(p, out / "home.webp")
    a = flows_share.drive_page(t)
    a.device = {**DEVICES["desktop"], "width": 960, "height": 600}
    a.cmd("Emulation.setDeviceMetricsOverride", {"width": 960, "height": 600, "deviceScaleFactor": 1, "mobile": False})
    flows_drive.upload_files(t, a, ["notes.txt", "agenda.txt"])
    a.eval("document.querySelector('[data-testid=\"upload-panel\"] .uploads-head .btn')?.click()")
    flows_share.open_share(a, "notes.txt")
    flows_share.to_opens(a)
    flows_share.make_link(a)
    a.wait("!!document.querySelector('[data-testid=\"share-qr\"] svg, [data-testid=\"share-qr\"] canvas, [data-testid=\"share-qr\"] img')", 30)
    a.eval(BLUR_QR)
    theme(a, "light")
    time.sleep(0.8)
    capture(a, out / "share.webp")
    flows_share.close_dialog(a)
    flows_share.wait_rule(a, "notes.txt", "once")
    theme(a, "dark")
    time.sleep(0.8)
    capture(a, out / "drive.webp")
    social(t.browser, out)
    og_candidate(t.browser, out)


def social(browser, out):
    """social-preview.html at 1280 × 640: Geist from the pinned file and the sprite's two marks put in as data
    (a file:// page can load neither), the still decoded, then the picture."""
    sprite = (ROOT / "web/shared/ui/icons.svg").read_text()
    font = "data:font/woff2;base64," + base64.b64encode((ROOT / "web/shared/fonts/geist/Geist-Variable.woff2").read_bytes()).decode()
    t = run.T(run.Results(), browser, "file://", str(out), None)
    p = t.actor("desktop")
    p.device = {**DEVICES["desktop"], "width": 1280, "height": 640}
    p.cmd("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 640, "deviceScaleFactor": 1, "mobile": False})
    p.goto((HERE / "social-preview.html").as_uri())
    p.eval(f"""(async () => {{
      const doc = new DOMParser().parseFromString({json.dumps(sprite)}, 'image/svg+xml');
      const keep = document.getElementById('sprite');
      for (const id of ['i-hidebox', 'i-wordmark']) keep.append(document.importNode(doc.getElementById(id), true));
      const face = new FontFace('Geist', `url({font})`, {{ weight: '100 900' }});
      document.fonts.add(face);
      await face.load();
      await document.fonts.ready;
      await Promise.all([...document.images].map((i) => i.decode()));
      return true; }})()""")
    capture(p, out / "social-preview.png", {"x": 0, "y": 0, "width": 1280, "height": 640}, scale=1)
    t.close()


def attempt(what, fn, *args):
    """One surface; a failure is printed and the others still run."""
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001 (evidence: report and go on)
        print(f"  FAILED {what}: {type(e).__name__}: {str(e)[:300]}", flush=True)


def og_candidate(browser, out):
    """What og.png would be with the kit's marks (og.png itself stays as it is, by the owner's word): og.html with the
    sprite's open box in its tile and the wordmark in place of the typed name, everything else as render-images.py
    draws it (Geist, {{BRAND}}, the still decoded), at 1200 × 630."""
    sprite = (ROOT / "web/shared/ui/icons.svg").read_text()
    font = "data:font/woff2;base64," + base64.b64encode((ROOT / "web/shared/fonts/geist/Geist-Variable.woff2").read_bytes()).decode()
    t = run.T(run.Results(), browser, "file://", str(out), None)
    p = t.actor("desktop")
    p.device = {**DEVICES["desktop"], "width": 1200, "height": 630}
    p.cmd("Emulation.setDeviceMetricsOverride", {"width": 1200, "height": 630, "deviceScaleFactor": 1, "mobile": False})
    p.goto((ROOT / "web/site/og/og.html").as_uri())
    p.eval(f"""(async () => {{
      const doc = new DOMParser().parseFromString({json.dumps(sprite)}, 'image/svg+xml');
      const keep = document.querySelector('.sprite');
      for (const id of ['i-hidebox', 'i-wordmark']) keep.append(document.importNode(doc.getElementById(id), true));
      document.querySelector('.brandrow .tile use').setAttribute('href', '#i-hidebox');
      document.querySelector('.brandrow .tile').style.color = '#ACFF00';   // the kit's lime, as og-s.html's tile
      const word = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      word.setAttribute('class', 'word');
      const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      use.setAttribute('href', '#i-wordmark');
      word.append(use);
      document.querySelector('.brandrow .name').replaceWith(word);
      const face = new FontFace('Geist', `url({font})`, {{ weight: '100 900' }});
      document.fonts.add(face);
      const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n; (n = walk.nextNode());) n.nodeValue = n.nodeValue.replaceAll('{{{{BRAND}}}}', 'hidebox');
      await face.load();
      await document.fonts.ready;
      await Promise.all([...document.images].map((i) => i.decode()));
      return true; }})()""")
    capture(p, out / "og-candidate.png", {"x": 0, "y": 0, "width": 1200, "height": 630}, scale=1)
    t.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="1440,390")
    ap.add_argument("--surfaces", default="holding,site,delivered,drive,folder", help="which of them, comma-separated")
    ap.add_argument("--readme", default=None)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    widths = [int(w) for w in args.only.split(",")]
    work = tempfile.mkdtemp(prefix="mutis-brand-shots-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    port, port2 = run.free_port(), run.free_port()
    dist = run.build(work, f"http://127.0.0.1:{port}")
    server = run.serve(dist, os.path.join(work, "data"), port)
    server2 = run.serve(dist, os.path.join(work, "data-folders"), port2, None, ("folders",))   # the drive's folders
    run.make_fixtures(os.path.join(work, "fixtures"))
    browser = Browser()
    try:
        surfaces = set(args.surfaces.split(",")) - {""}
        if "holding" in surfaces:
            attempt("holding", holding, browser, out, work, widths)
        for width in widths:
            t = run.T(run.Results(), browser, f"http://127.0.0.1:{port}", work, None)
            try:
                for name, fn in (("site", site), ("delivered", delivered), ("drive", drive), ("folder", folder)):
                    if name in surfaces:
                        t.origin = f"http://127.0.0.1:{port2 if name in ('drive', 'folder') else port}"
                        attempt(f"{name} {width}", fn, t, out, width)
            finally:
                t.close()
        if args.readme:
            Path(args.readme).mkdir(parents=True, exist_ok=True)
            t = run.T(run.Results(), browser, f"http://127.0.0.1:{port2}", work, None)
            try:
                attempt("readme", readme, t, Path(args.readme), work)
            finally:
                t.close()
    finally:
        browser.close()
        for proc in (server, server2):
            proc.terminate()
            proc.wait(10)
        shutil.rmtree(work, ignore_errors=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
