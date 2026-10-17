# SPDX-License-Identifier: MIT
"""Home v3 screenshots and probes (docs/review/home-v3.md), headless Chromium as `build` on the server, from the
repository root:

  python3 -I docs/evidence/2026-10-18/home-v3/shots_v3.py [--origin URL] [--out DIR] [--only shots,probe]

Without --origin it serves this tree with web/site/tests/serve.py (production's CSP, the API from fixtures, as the live
deployment is set: direct sends, SealLog, pay to open); with --origin it reads the live site.
shots: /v3 at 1440 and 390, dark (the page's default) and light (the switch pressed): the first screen, the whole page
after scrolling through it (in parts when it is taller than one capture), each section with a still on its own, the
header's tile, and the first screen with reduced motion. probe: the network log at load and after scrolling, with the
browser cache off and on (which stills were asked for, and the bytes), for a computer, an Android phone, an iPhone's
user agent and reduced motion; writes probe.json (probe-live.json with --origin) beside the shots.
"""
import argparse
import base64
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "web/site/tests"), str(ROOT / "web/site/tools")]
from cdp import Browser  # noqa: E402

SIZES = {1440: (1440, 900, False), 390: (390, 844, True)}
LIGHT = "try { localStorage.setItem('mutis.theme', 'light'); } catch (e) {}"
DARK = "try { localStorage.removeItem('mutis.theme'); } catch (e) {}"   # no choice made: the page's own default
PART = 6000   # Chromium draws at most 8,192 px in one capture (a taller one repeats its top), so a long page comes in parts
SECTIONS = ((".v2-hero", "hero"), ("#different", "different"), ("#who", "who"), ("#tari", "tari"), (".end", "closing"))
PICS = """[...document.querySelectorAll('.stage .pic')].map((i) => ({ stage: i.closest('.stage').classList[1],
  src: i.currentSrc.split('/').pop(), done: i.complete && i.naturalWidth > 0, w: Math.round(i.getBoundingClientRect().width) }))"""


def stills(page):
    return [{"file": r["url"].rsplit("/", 1)[-1], "status": r["status"], "bytes": r["bytes"]}
            for r in page.requests() if "/site/media/" in r["url"]]


def total(page):
    return sum(r["bytes"] for r in page.requests())


def through(page):
    h = page.height * 0.5
    end = int(page.eval("document.documentElement.scrollHeight"))
    for y in range(0, end + int(h), int(h)):
        page.scroll_to(y, 0.5)
    page.b.pump(1.0)


def new_page(b, width, height, mobile, light=False, reduce=False, android=False, cache=False):
    page = b.page(width, height, mobile=mobile, android=android, reduce=reduce)
    page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": LIGHT if light else DARK})
    if cache:
        page.cmd("Network.setCacheDisabled", {"cacheDisabled": False})
    return page


def full(page, path):
    h = page.eval("document.documentElement.scrollHeight")
    if h <= 8000:
        page.screenshot(str(path), full=True)
        return 1
    n = 0
    for i, y in enumerate(range(0, h, PART)):
        clip = {"x": 0, "y": y, "width": page.width, "height": min(PART, h - y), "scale": 1}
        data = page.cmd("Page.captureScreenshot", {"format": "webp", "quality": 82, "captureBeyondViewport": True, "clip": clip})["data"]
        (path.parent / f"{path.stem}-{i + 1}{path.suffix}").write_bytes(base64.b64decode(data))
        n += 1
    return n


def section(page, sel, path):
    """One part of the page, with the sticky header taken out of the way (CSSOM, which the CSP allows)."""
    page.eval("document.querySelector('.site-header').style.position = 'static'")
    page.eval(f"document.querySelector({json.dumps(sel)}).scrollIntoView({{block: 'center'}})")
    page.b.pump(1.5)
    page.screenshot_element(sel, str(path))
    page.eval("document.querySelector('.site-header').style.position = ''")


def shots(b, origin, out):
    n = 0
    for w, (width, height, mobile) in SIZES.items():
        for theme in ("dark", "light"):
            page = new_page(b, width, height, mobile, light=theme == "light", android=mobile)
            page.goto(origin + "/v3", settle=3.0)
            page.screenshot(str(out / f"v3-{w}-{theme}.webp"))
            page.screenshot_element(".site-header .wm", str(out / f"v3-{w}-{theme}-mark.png"))
            through(page)
            page.scroll_to(0, 1.0)
            n += 2 + full(page, out / f"v3-{w}-{theme}-full.webp")
            for sel, part in SECTIONS:
                section(page, sel, out / f"v3-{w}-{theme}-{part}.webp")
                n += 1
            page.close()
    page = new_page(b, 1440, 900, False, reduce=True)
    page.goto(origin + "/v3", settle=3.0)
    page.screenshot(str(out / "v3-1440-reduced.webp"))
    page.close()
    return n + 1


def probe(b, origin):
    report = {}
    for name, kw in (("desktop", dict(width=1440, height=900, mobile=False)),
                     ("android", dict(width=390, height=844, mobile=True, android=True)),
                     ("iphone", dict(width=390, height=844, mobile=True)),
                     ("reduced", dict(width=1440, height=900, mobile=False, reduce=True))):
        for cache in (False, True):
            page = new_page(b, cache=cache, **kw)
            page.goto(origin + "/v3", settle=3.0)
            at_load = {"stills": stills(page), "bytes": total(page), "requests": len(page.requests())}
            through(page)
            after = {"stills": stills(page), "bytes": total(page), "requests": len(page.requests()), "pictures": page.eval(PICS)}
            report[f"{name}{'-cached' if cache else ''}"] = {
                "at_load": at_load, "after_scroll": after, "videos": page.eval("document.querySelectorAll('video').length"),
                "console": [l for l in page.console() if l.startswith(("error", "exception")) or "Content Security Policy" in l]}
            page.close()
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--origin")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--only", default="shots,probe")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    srv = None
    origin = args.origin
    if not origin:
        import serve
        srv, origin = serve.make_server(serve.options(["--port", "0", "--mode", "direct", "--seallog", "--pay"]))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    result = {"origin": origin if args.origin else "web/site/tests/serve.py"}
    with Browser() as b:
        if "shots" in args.only:
            result["shots"] = shots(b, origin, args.out)
        if "probe" in args.only:
            result["probe"] = probe(b, origin)
    if srv:
        srv.shutdown()
    if "probe" in args.only:
        (args.out / ("probe-live.json" if args.origin else "probe.json")).write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "probe"}))
    for k, v in result.get("probe", {}).items():
        names = lambda m: [x["file"] for x in m]   # noqa: E731
        print(f"{k}: load {v['at_load']['bytes']:,} B {names(v['at_load']['stills'])}; after scroll {v['after_scroll']['bytes']:,} B "
              f"{names(v['after_scroll']['stills'])}; videos {v['videos']}; console {v['console'][:3]}")


if __name__ == "__main__":
    main()
