# SPDX-License-Identifier: MIT
"""Site v3 screenshots (docs/review/site-v3.md), as `build` on the server, from the repository root:

  python3 -I docs/review/site-v3/shots_v3.py [--out DIR] [--pages /,/how,/judges] [--widths 1440,390]

For each page, width and theme: the first screen once the hero has arrived, and the whole page after scrolling
through it (so every reveal has run and the pixel field is live). Then the hero picture caught mid-decode and
the closing's pixel field in both themes, at both widths. WebP from headless Chromium.
"""
import argparse
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "web/site/tests"), str(ROOT / "web/site/tools")]
import serve  # noqa: E402
from cdp import Browser  # noqa: E402

NAMES = {"/": "home"}


def through(page):
    h = page.height * 0.6
    for y in range(0, int(page.eval("document.documentElement.scrollHeight")) + int(h), int(h)):
        page.scroll_to(y, 0.25)
    page.b.pump(1.5)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=ROOT / "docs/review/site-v3")
    p.add_argument("--pages", default="/,/how,/judges")
    p.add_argument("--widths", default="1440,390")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    srv, origin = serve.make_server(serve.options(["--port", "0", "--mode", "direct", "--seallog", "--pay"]))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sizes = {1440: (1440, 900, False), 390: (390, 844, True)}
    n = 0
    with Browser() as b:
        for w in map(int, args.widths.split(",")):
            width, height, mobile = sizes[w]
            for dark in (False, True):
                theme = "dark" if dark else "light"
                for path in args.pages.split(","):
                    name = NAMES.get(path, path.strip("/"))
                    page = b.page(width, height, mobile=mobile, dark=dark)
                    page.goto(origin + path, settle=3)
                    page.screenshot(str(args.out / f"{name}-{w}-{theme}.webp"))
                    through(page)
                    page.scroll_to(0, 0.6)
                    page.screenshot(str(args.out / f"{name}-{w}-{theme}-full.webp"), full=True)
                    n += 2
                # the hero picture mid-decode, and the pixel field
                page = b.page(width, height, mobile=mobile, dark=dark)
                page.goto(origin + "/", settle=0.05)
                if page.wait_for("!!document.querySelector('.hero .slice .dc-layer')", 6):
                    page.b.pump(0.15)
                    page.screenshot_element(".hero .slice", str(args.out / f"decode-{w}-{theme}.webp"))
                    n += 1
                page.scroll_to(page.eval("document.querySelector('.end').offsetTop - 40"), 0.4)
                if page.wait_for("document.querySelector('[data-pixel]').classList.contains('live')", 6):
                    page.b.pump(2.2)
                    page.screenshot_element(".end", str(args.out / f"pixel-{w}-{theme}.webp"))
                    n += 1
    srv.shutdown()
    print(f"{n} screenshots in {args.out}")


if __name__ == "__main__":
    main()
