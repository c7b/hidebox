# SPDX-License-Identifier: MIT
"""Writes the curated screenshots in web/site/shots/: the six pages (16-drive-design §2, §11) at 1440×900
and 390×844 (iPhone-class): the first screen in the light and the dark theme, and the whole page in the light.
WebP from headless Chromium (PNG with --png); run as `build` on ultron:

  python3 -I web/site/tests/shots.py [--out DIR] [--png] [--only home,pages]

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
    p.add_argument("--only", default="home,pages")
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
            for dark in (False, True):
                theme = "dark" if dark else "light"
                for path in PAGES:
                    name = NAMES.get(path, path.strip("/"))
                    if ("home" if path == "/" else "pages") not in only:
                        continue
                    page = browser.page(w, h, mobile=mobile, dark=dark)
                    page.goto(origin + path, settle=2)
                    page.eval("document.fonts.ready.then(() => true)", True)
                    page.screenshot(str(out / f"{name}-{w}-{theme}.{ext}"))
                    if path != "/no-such-page" and not dark:   # the whole page once, in the light theme
                        page.screenshot(str(out / f"{name}-{w}-{theme}-full.{ext}"), full=True)
    srv.shutdown()
    files = list(out.iterdir())
    print(f"{len(files)} screenshots, {sum(f.stat().st_size for f in files) / 1e6:.2f} MB in {out}")


if __name__ == "__main__":
    main()
