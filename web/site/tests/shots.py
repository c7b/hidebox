# SPDX-License-Identifier: MIT
"""Writes the curated screenshots in web/site/shots/ (M-02): every home section and every page at
1440×900, 390×844 (iPhone-class) and 412×915 (Android-class), the exit wall frame by frame, the
reduced-motion grid, dark mode and Spanish. WebP from headless Chromium; run as `build` on the server:

  python3 -I web/site/tests/shots.py

The hero shows the app's own drop widget, served from web/app/ like every other app file.
"""
import shutil
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools")]
import serve  # noqa: E402
from cdp import Browser  # noqa: E402

OUT = HERE.parent / "shots"
DESKTOP, IPHONE, ANDROID = (1440, 900, False, False), (390, 844, True, False), (412, 915, True, True)
SECTIONS = ["#two-locks", "#send", "#what-we-store", "#try", "#cant-hide", "#free", "#open-source", ".closing"]
PAGES = ["/how", "/security", "/pricing", "/faq", "/judges", "/terms", "/privacy", "/abuse", "/status", "/no-such-page"]
WALL_FRAMES = (0.05, 0.22, 0.4, 0.58, 0.74, 1.0)


def start(args):
    srv, origin = serve.make_server(serve.options(["--port", "0", *args]))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, origin


def section_top(page, selector):
    return page.eval(f"document.querySelector('{selector}').getBoundingClientRect().top + scrollY")


def wake_wall(page):
    """Like a visitor starting to scroll: the wall's code loads while its lockers are still below the fold."""
    page.scroll_to(page.eval("document.getElementById('exit-wall').offsetTop - innerHeight + 40"), 1.5)


def shoot_home(browser, origin, tag, device, dark=False):
    w, h, mobile, android = device
    page = browser.page(w, h, mobile=mobile, android=android, dark=dark)
    page.goto(f"{origin}/", settle=2.5)
    page.screenshot(str(OUT / f"{tag}-hero.webp"))
    wake_wall(page)
    top, height = page.eval("(() => { const r = document.getElementById('exit-wall').getBoundingClientRect(); return [r.top + scrollY, r.height]; })()")
    for i, f in enumerate(WALL_FRAMES):
        page.scroll_to(top + f * (height - h), 0.7)
        page.screenshot(str(OUT / f"{tag}-wall-{i}.webp"))
    for selector in SECTIONS:
        page.scroll_to(section_top(page, selector), 1)
        page.screenshot(str(OUT / f"{tag}-{selector.strip('#.')}.webp"))
    page.scroll_to(section_top(page, ".site-footer"), 0.4)
    page.screenshot(str(OUT / f"{tag}-footer.webp"))


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    servers = []
    with Browser() as browser:
        srv, origin = start([])
        servers.append(srv)
        shoot_home(browser, origin, "home-1440", DESKTOP)
        shoot_home(browser, origin, "home-390", IPHONE)
        shoot_home(browser, origin, "home-412", ANDROID)
        shoot_home(browser, origin, "home-dark-1440", DESKTOP, dark=True)
        for w, h, mobile, _ in (DESKTOP, IPHONE):
            page = browser.page(w, h, mobile=mobile, reduce=True)
            page.goto(origin + "/", settle=2)
            wake_wall(page)
            page.screenshot_element("#exit-wall", str(OUT / f"wall-reduced-{w}.webp"))
            for path in PAGES:
                page = browser.page(w, h, mobile=mobile)
                page.goto(origin + path, settle=1.5)
                page.screenshot(str(OUT / f"page-{path.strip('/')}-{w}.webp"))
        for scenario in ("quiet", "8"):
            srv, origin = start(["--wall", scenario])
            servers.append(srv)
            page = browser.page(*DESKTOP[:2])
            page.goto(origin + "/", settle=2.5)
            wake_wall(page)
            page.scroll_to(section_top(page, "#exit-wall") + 0.1 * 1800, 0.7)
            page.screenshot(str(OUT / f"wall-{scenario}-1440.webp"))
        srv, origin = start(["--mode", "direct", "--seallog"])
        servers.append(srv)
        page = browser.page(*DESKTOP[:2])
        page.goto(origin + "/", settle=2.5)
        page.scroll_to(section_top(page, "#two-locks"), 0.5)
        page.screenshot(str(OUT / "variant-direct-seallog-locks-1440.webp"))
        page.scroll_to(section_top(page, "#cant-hide"), 0.5)
        page.screenshot(str(OUT / "variant-direct-seallog-cant-hide-1440.webp"))
    for srv in servers:
        srv.shutdown()
    total = sum(f.stat().st_size for f in OUT.iterdir())
    print(f"{len(list(OUT.iterdir()))} screenshots, {total / 1e6:.2f} MB in {OUT}")


if __name__ == "__main__":
    main()
