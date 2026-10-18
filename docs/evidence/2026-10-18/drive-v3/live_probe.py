# SPDX-License-Identifier: MIT
"""Drive v3 on production (docs/review/drive-v3.md), as `build` on the server, from a copy of the repository:

  python3 -I docs/evidence/2026-10-18/drive-v3/live_probe.py https://srv2052606.hstgr.cloud

Reads what /drive serves (its icons, the app's token file and stylesheet) and opens /drive with no drive in headless
Chromium at 1440 and 390, light and dark: the home's open box on the start screen from its AVIF, one lime action,
v3's gunmetal card in light and the void in dark, nothing sideways, no CSP or Trusted Types violation. It makes no
drive (the API's pace stays the e2e batch's). One PASS or FAIL line per check. Python stdlib only.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "web/app/ui/tests"))
from cdp import Browser, Page  # noqa: E402

LIME = "rgb(188, 254, 0)"
failed = []


def check(ok, what):
    print(f"{'PASS' if ok else 'FAIL'} {what}", flush=True)
    if not ok:
        failed.append(what)


def get(origin, path):
    with urllib.request.urlopen(origin + path, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    origin = sys.argv[1].rstrip("/")
    st, html = get(origin, "/drive")
    check(st == 200 and all(x in html for x in ('href="/favicon-32.png"', 'href="/favicon.svg"', 'href="/apple-touch-icon.png"')),
          "/drive names the open box's icons (the 32 px PNG, the SVG, the touch icon)")
    st, tokens = get(origin, "/shared/ui/tokens.css")
    check(st == 200 and "oklch(0.178 0.0045 258.4)" in tokens and "--glass:" in tokens and "oklch(0.51 0 0)" in tokens,
          "the app's tokens are v3's (the gunmetal rail, the glass, the site's #666666)")
    st, css = get(origin, "/app/css/drive.css")
    check(st == 200 and ".start:has(> .start-pic)" in css and "backdrop-filter" in css, "the drive's stylesheet has the start picture and the frosted header")
    for width, device in ((1440, "desktop"), (390, "iphone")):
        b = Browser(())
        try:
            for theme in ("light", "dark"):
                p = Page(b, device)
                p.goto(origin + "/drive")
                p.wait("!!document.querySelector('[data-testid=\"drive-start\"]')", 60)
                p.eval(f"document.documentElement.dataset.theme = {json.dumps(theme)}")
                p.wait("(() => { const i = document.querySelector('[data-testid=\"start-pic\"] img'); return i && i.complete && i.naturalWidth > 0; })()", 30)
                time.sleep(0.4)
                src = p.eval("document.querySelector('[data-testid=\"start-pic\"] img').currentSrc")
                limes = p.eval("[...document.querySelectorAll('button, a')].filter((e) => e.getClientRects().length && getComputedStyle(e).backgroundColor === %s)"
                               ".map((e) => e.dataset.testid || e.textContent.trim())" % json.dumps(LIME))
                stage = p.eval("[getComputedStyle(document.querySelector('.start-pic')).backgroundImage.slice(0, 15), getComputedStyle(document.querySelector('.start-pic img')).mixBlendMode]")
                fold = p.eval("document.querySelector('[data-testid=\"drive-make\"]').getBoundingClientRect().bottom <= innerHeight")
                wide = p.eval("document.scrollingElement.scrollWidth <= innerWidth")
                want = ["radial-gradient", "lighten"] if theme == "light" else ["none", "normal"]
                where = f"{width} {theme}"
                check(src.startswith(origin + "/site/media/v3/hero-") and src.endswith(".avif"), f"{where}: the start screen shows the open box from its AVIF ({src.rsplit('/', 1)[-1]})")
                check(limes == ["drive-make"], f"{where}: one lime action, Make my drive ({limes})")
                check(stage == want, f"{where}: {'on the gunmetal card, lighten' if theme == 'light' else 'on the void'} ({stage})")
                check(fold and wide, f"{where}: Make my drive in the first screen, nothing sideways")
                check(not p.csp_violations(), f"{where}: no CSP or Trusted Types violation")
                p.close()
        finally:
            b.close()
    print(f"live probe {'PASS' if not failed else 'FAIL'} {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
