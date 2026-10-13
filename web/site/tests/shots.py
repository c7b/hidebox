# SPDX-License-Identifier: MIT
"""Writes the curated screenshots in web/site/shots/: the six pages of the ghost at 1440×900 and
390×844 (iPhone-class), the home in both themes, every scene of "How it works" on both, and the
reduced-motion stills. WebP from headless Chromium (PNG with --png); run as `build` on ultron:

  python3 -I web/site/tests/shots.py [--out DIR] [--png] [--only home,how,pages]

The home shows the app's own drop widget, served from web/app/ like every other app file.
"""
import argparse
import shutil
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools")]
import serve  # noqa: E402
from cdp import Browser  # noqa: E402

DESKTOP, IPHONE = (1440, 900, False), (390, 844, True)
PAGES = ["/", "/how", "/made", "/judges", "/fine-print", "/no-such-page"]
NAMES = {"/": "home", "/no-such-page": "404"}


def start(args):
    srv, origin = serve.make_server(serve.options(["--port", "0", *args]))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, origin


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=HERE.parent / "shots")
    p.add_argument("--png", action="store_true")
    p.add_argument("--only", default="home,how,pages")
    args = p.parse_args()
    only = set(args.only.split(","))
    ext = "png" if args.png else "webp"
    out = args.out
    if out == HERE.parent / "shots":
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    srv, origin = start(["--mode", "direct", "--seallog"])
    with Browser() as browser:
        for w, h, mobile in (DESKTOP, IPHONE):
            if "pages" in only:
                for path in PAGES:
                    page = browser.page(w, h, mobile=mobile)
                    page.goto(origin + path, settle=2)
                    page.screenshot(str(out / f"{NAMES.get(path, path.strip('/'))}-{w}.{ext}"))
                    if path in ("/made", "/judges", "/fine-print"):
                        page.screenshot(str(out / f"{NAMES.get(path, path.strip('/'))}-{w}-full.{ext}"), full=True)
            if "home" in only:
                for dark in (False, True):
                    page = browser.page(w, h, mobile=mobile, dark=dark)
                    page.goto(origin + "/", settle=2.5)
                    page.screenshot(str(out / f"home-{w}-{'dark' if dark else 'light'}.{ext}"))
                page = browser.page(w, h, mobile=mobile)
                page.goto(origin + "/", settle=2)
                page.cmd("Input.dispatchDragEvent", {"type": "dragEnter", "x": 300, "y": 500, "data": {
                    "items": [], "files": [str(Path(__file__).resolve().parent / "fixtures" / "canary.json")], "dragOperationsMask": 1}})
                browser.pump(0.6)
                page.screenshot(str(out / f"home-{w}-catch.{ext}"))
            if "how" in only:
                for reduce in (False, True):
                    page = browser.page(w, h, mobile=mobile, reduce=reduce)
                    page.goto(origin + "/how", settle=1.5)
                    for n in range(1, 9):
                        y = page.eval(f"(() => {{ const li = document.querySelector('.captions li[data-scene=\"{n}\"]');"
                                      " return li.getBoundingClientRect().top + scrollY + li.offsetHeight / 2 - innerHeight / 2; })()")
                        page.scroll_to(y, 1.6 if not reduce else 0.6)
                        if reduce and n not in (4, 5):
                            continue
                        page.screenshot(str(out / f"how-{w}-scene{n}{'-reduced' if reduce else ''}.{ext}"))
    srv.shutdown()
    files = list(out.iterdir())
    print(f"{len(files)} screenshots, {sum(f.stat().st_size for f in files) / 1e6:.2f} MB in {out}")


if __name__ == "__main__":
    main()
