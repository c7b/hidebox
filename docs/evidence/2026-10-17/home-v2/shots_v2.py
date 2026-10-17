# SPDX-License-Identifier: MIT
"""Home v2 screenshots and probes (docs/review/home-v2.md), headless Chromium as `build` on ultron, from the
repository root:

  python3 -I docs/evidence/2026-10-17/home-v2/shots_v2.py [--origin URL] [--out DIR] [--only shots,frames,probe]

Without --origin it serves this tree with web/site/tests/serve.py (production's CSP, the API from fixtures, as
the live deployment is set: direct sends, SealLog, pay to open); with --origin it reads the live site.
shots: /v2 at 1440 and 390, dark (the page's default) and light (the switch pressed), the first screen and the
whole page after scrolling through it (a phone's in two parts), each section with a loop on its own at 1440, an
iPhone's Safari (the MP4s) in both themes, and the first screen with reduced motion. frames: the hero's loop twice, a second
apart, with its currentTime (it plays). probe: the network log at load and after scrolling (which media were
asked for, when, and how many bytes), reduced motion (posters only, nothing plays), WebKit's MP4, every loop
paused off screen; writes probe.json beside the shots.
"""
import argparse
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
# Chromium draws at most 8,192 px in one capture (a taller one repeats its top), so a long page comes in parts.
PART = 6000
CLIPS = "[...document.querySelectorAll('video[data-clip]')]"
STATE = CLIPS + (".map((v) => ({ stage: v.parentElement.className, live: v.dataset.live || '', src: v.currentSrc.split('/').pop(),"
                 " poster: (v.getAttribute('poster') || '').split('/').pop(), paused: v.paused, t: +v.currentTime.toFixed(2),"
                 " shown: v.getBoundingClientRect().bottom > 0 && v.getBoundingClientRect().top < innerHeight }))")
MEDIA = (".webm", ".mp4", "_poster.png")


def media(page, origin):
    out = []
    for r in page.requests():
        if r["url"].endswith(MEDIA):
            out.append({"file": r["url"].rsplit("/", 1)[-1], "status": r["status"], "bytes": r["bytes"], "failed": r["failed"]})
    return out


def total(page):
    return sum(r["bytes"] for r in page.requests())


def through(page, stops=None):
    """Scroll down the page a step at a time; at each stop, record which loops are on screen and playing."""
    h = page.height * 0.5
    seen = []
    end = int(page.eval("document.documentElement.scrollHeight"))
    for y in range(0, end + int(h), int(h)):
        page.scroll_to(y, 0.9)
        seen.append({"y": y, "clips": page.eval(STATE)})
    page.b.pump(1.0)
    return seen


def new_page(b, width, height, mobile, light=False, reduce=False, android=False):
    page = b.page(width, height, mobile=mobile, android=android, reduce=reduce)
    page.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": LIGHT if light else DARK})
    return page


def full(page, path):
    """The whole page, in parts of PART px when it is taller than one capture can be."""
    import base64
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
    page.b.pump(2.0)
    page.screenshot_element(sel, str(path))
    page.eval("document.querySelector('.site-header').style.position = ''")


def shots(b, origin, out):
    n = 0
    for w, (width, height, mobile) in SIZES.items():
        for theme in ("dark", "light"):
            page = new_page(b, width, height, mobile, light=theme == "light", android=mobile)
            page.goto(origin + "/v2", settle=3.0)
            page.screenshot(str(out / f"v2-{w}-{theme}.webp"))
            through(page)
            page.scroll_to(0, 1.0)
            n += 1 + full(page, out / f"v2-{w}-{theme}-full.webp")
            if w == 1440:
                for sel, part in ((".v2-hero", "hero"), ("#different", "different"), ("#who", "who"), ("#tari", "tari"), (".end", "closing")):
                    section(page, sel, out / f"v2-{w}-{theme}-{part}.webp")
                    n += 1
            page.close()
    # WebKit (an iPhone's Safari): the MP4 on its black stage, both themes; reduced motion: the still poster
    for theme in ("dark", "light"):
        page = new_page(b, 390, 844, True, light=theme == "light")
        page.goto(origin + "/v2", settle=3.0)
        page.scroll_to(300, 2.0)
        page.screenshot(str(out / f"v2-390-iphone-{theme}.webp"))
        page.close()
        n += 1
    page = new_page(b, 1440, 900, False, reduce=True)
    page.goto(origin + "/v2", settle=3.0)
    page.screenshot(str(out / "v2-1440-reduced.webp"))
    page.close()
    return n + 1


def frames(b, origin, out):
    page = new_page(b, 1440, 900, False)
    page.goto(origin + "/v2", settle=1.0)
    page.wait_for("(() => { const v = document.querySelector('.stage-a video'); return v.currentTime > 1.2 && !v.paused; })()", 20)
    t1 = page.eval("document.querySelector('.stage-a video').currentTime")
    page.screenshot_element(".stage-a", str(out / "v2-hero-frame-1.png"))
    page.b.pump(1.0)
    t2 = page.eval("document.querySelector('.stage-a video').currentTime")
    page.screenshot_element(".stage-a", str(out / "v2-hero-frame-2.png"))
    page.screenshot(str(out / "v2-1440-dark-midloop.webp"))
    a, b2 = (out / "v2-hero-frame-1.png").read_bytes(), (out / "v2-hero-frame-2.png").read_bytes()
    page.close()
    return {"t1": round(t1, 2), "t2": round(t2, 2), "frames_differ": a != b2}


def probe(b, origin):
    report = {}
    for name, kw in (("desktop", dict(width=1440, height=900, mobile=False)),
                     ("android", dict(width=390, height=844, mobile=True, android=True)),
                     ("iphone", dict(width=390, height=844, mobile=True)),
                     ("reduced", dict(width=1440, height=900, mobile=False, reduce=True))):
        page = new_page(b, **kw)
        page.goto(origin + "/v2", settle=4.0)
        at_load = {"media": media(page, origin), "bytes": total(page), "clips": page.eval(STATE)}
        steps = through(page)
        after = {"media": media(page, origin), "bytes": total(page), "clips": page.eval(STATE)}
        bad = [f"{s['y']}: {c['stage']} {'playing off screen' if c['shown'] else 'paused on screen'}"
               for s in steps for c in s["clips"]
               if c["live"] and ((not c["paused"] and not c["shown"]))]
        report[name] = {"at_load": at_load, "after_scroll": after, "playing_off_screen": bad,
                        "console": [l for l in page.console() if l.startswith(("error", "exception")) or "Content Security Policy" in l]}
        page.close()
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--origin")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--only", default="shots,frames,probe")
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
        if "frames" in args.only:
            result["frames"] = frames(b, origin, args.out)
        if "probe" in args.only:
            result["probe"] = probe(b, origin)
    if srv:
        srv.shutdown()
    name = "probe-live.json" if args.origin else "probe.json"
    (args.out / name).write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "probe"}))
    for k, v in result.get("probe", {}).items():
        files = lambda m: sorted({x["file"] for x in m})   # noqa: E731
        print(f"{k}: load {v['at_load']['bytes']:,} B {files(v['at_load']['media'])}; after scroll {v['after_scroll']['bytes']:,} B "
              f"{files(v['after_scroll']['media'])}; off-screen playing {len(v['playing_off_screen'])}; console {v['console'][:3]}")


if __name__ == "__main__":
    main()
