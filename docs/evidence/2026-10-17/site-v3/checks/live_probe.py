# SPDX-License-Identifier: MIT
"""Site v3 on production (as `build` on ultron): python3 -I live_probe.py [origin]
The header's Open your drive on /, /how and /judges at the top and the end; motion.js and pixel.js after the load
event; the hero picture's decode (an aria-hidden layer, the real words kept) and its DOM after; nothing left
hidden after scrolling through; the pixel field live and paused off screen; no CSP violation; reduced motion
(neither module, every word shown) and no JavaScript (every word shown), at 1440 and 390."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path.home() / "work/site-v3/web/site/tools")]
from cdp import Browser  # noqa: E402

O = sys.argv[1] if len(sys.argv) > 1 else "https://srv2052606.hstgr.cloud"
LOADED = "(n) => { const r = performance.getEntriesByType('resource').find((e) => e.name.endsWith('/site/js/' + n)); return r ? Math.round(r.startTime) : null; }"
HIDDEN = "document.querySelectorAll('.mo-h:not(.mo-in), .dc-c:not(.dc-ok), .mo-w').length"
SHOWN = "(t) => { const e = document.querySelector(`[data-testid=\"${t}\"]`); return !!e && e.checkVisibility() && e.textContent.trim(); }"
fails = 0


def ok(cond, text):
    global fails
    fails += not cond
    print(("PASS " if cond else "FAIL ") + text, flush=True)


with Browser() as b:
    q = b.page(1440, 900, reduce=True)
    q.goto(O + "/", settle=3)
    still = q.eval("document.querySelector('.hero .slice').innerHTML")
    ok(q.eval(f"({LOADED})('motion.js')") is None and q.eval(f"({LOADED})('pixel.js')") is None, "reduced motion: neither module loads")
    ok(q.eval("getComputedStyle(document.querySelector('.hero .slice .name')).opacity") == "1", "reduced motion: the picture's words show at once")
    for w, h, m in ((1440, 900, False), (390, 844, True)):
        p = b.page(w, h, mobile=m)
        p.goto(O + "/", settle=0.1)
        mid = p.wait_for("!!document.querySelector('.hero .slice .dc-layer')", 8)
        ok(mid and p.eval("document.querySelector('.dc-layer').getAttribute('aria-hidden')") == "true"
           and "passport-scan.pdf" in p.eval("document.querySelector('.hero .slice').textContent"),
           f"/ @{w}: the picture decodes behind an aria-hidden layer, its real words kept")
        t = p.eval(f"[({LOADED})('motion.js'), Math.round(performance.getEntriesByType('navigation')[0].loadEventEnd)]")
        ok(t[0] is not None and t[0] >= t[1], f"/ @{w}: motion.js at {t[0]} ms, after the load event ({t[1]} ms)")
        ok(p.eval(f"({SHOWN})('head-make')") == "Open your drive", f"/ @{w}: the header's Open your drive at the top")
        for y in range(0, int(p.eval("document.documentElement.scrollHeight")) + int(h * .6), int(h * .6)):
            p.scroll_to(y, 0.25)
        p.b.pump(1.5)
        ok(p.eval(f"({SHOWN})('head-make')") == "Open your drive", f"/ @{w}: the header's Open your drive at the end")
        ok(not p.eval(HIDDEN), f"/ @{w}: nothing left hidden after scrolling through ({p.eval(HIDDEN)})")
        ok(p.eval("document.querySelector('.hero .slice').innerHTML") == still, f"/ @{w}: the picture's DOM after the decode is the page's")
        live = p.wait_for("document.querySelector('[data-pixel]').classList.contains('live')", 6)
        px = p.eval(f"({LOADED})('pixel.js')")
        ok(live and px is not None and px > t[1], f"/ @{w}: the pixel field live (pixel.js at {px} ms)")
        p.scroll_to(0, 0.6)
        a = p.eval("document.querySelector('[data-pixel]').frames")
        p.b.pump(0.6)
        ok(p.eval("document.querySelector('[data-pixel]').frames") == a, f"/ @{w}: the pixel field pauses off screen")
        bad = [c for c in p.console() if "Content Security Policy" in c or "Trusted Type" in c]
        ok(not bad, f"/ @{w}: no CSP or Trusted Types violation {bad[:2]}")
    for path in ("/how", "/judges"):
        p = b.page(1440, 900)
        p.goto(O + path, settle=1.5)
        ok(p.eval(f"({LOADED})('motion.js')") is not None and p.eval(f"({SHOWN})('head-make')") == "Open your drive",
           f"{path}: motion.js loads; the header says Open your drive")
        for y in range(0, int(p.eval("document.documentElement.scrollHeight")) + 540, 540):
            p.scroll_to(y, 0.25)
        p.b.pump(1.5)
        ok(not p.eval(HIDDEN), f"{path}: nothing left hidden after scrolling through")
    n = b.page(390, 844, mobile=True)
    n.cmd("Emulation.setScriptExecutionDisabled", {"value": True})
    n.goto(O + "/", settle=1.5)
    hid = n.eval("[...document.querySelectorAll('main h1, main h2, main p, main li, main td, main .badge')].filter((e) => e.checkVisibility() && getComputedStyle(e).opacity !== '1').length")
    ok(hid == 0, f"no JavaScript: every word on / fully shown ({hid} not)")
print(f"live probe: {'PASS' if not fails else 'FAIL'} ({fails} failed)")
