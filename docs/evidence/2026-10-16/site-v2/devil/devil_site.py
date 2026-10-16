# SPDX-License-Identifier: MIT
"""Integration devil for site v2: screenshots and measured checks on the pages served by serve.py
(production CSP, features as live), headless Chromium on the server as build.

  python3 -I web/site/tests/devil_site.py --out DIR [--origin URL]
"""
import argparse
import base64
import json
import struct
import sys
import threading
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools")]
import serve  # noqa: E402
from cdp import Browser  # noqa: E402

PAGES = ["/", "/how", "/judges", "/made", "/fine-print", "/no-such-page"]
NAME = {"/": "home", "/no-such-page": "404"}
FIELD = "document.querySelector('[data-field]')"
OUT = None
REPORT = []


def note(ok, what):
    REPORT.append(("PASS" if ok else ("NOTE" if ok is None else "FAIL"), what))
    print(("PASS " if ok else ("NOTE " if ok is None else "FAIL ")) + what, flush=True)


def png_rgb(data):
    """Decode an 8-bit RGB/RGBA PNG (what Chromium writes) to (w, h, rows of (r, g, b))."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    i, idat, w = 8, b"", 0
    while i < len(data):
        n, kind = struct.unpack(">I4s", data[i:i + 8])
        body = data[i + 8:i + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            bpp = 4 if ctype == 6 else 3
        elif kind == b"IDAT":
            idat += body
        i += 12 + n
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev, pos = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    return w, h, [[tuple(r[x * bpp:x * bpp + 3]) for x in range(w)] for r in rows]


def lum(rgb):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def parse_color(css):
    # rgb(r, g, b) / rgba(...) / color(srgb r g b / a)
    s = css.strip()
    if s.startswith("color(srgb"):
        parts = s[len("color(srgb"):-1].replace("/", " ").split()
        r, g, b = (round(float(v) * 255) for v in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1
    else:
        inner = s[s.index("(") + 1:-1].replace("/", ",").replace(" ", ",")
        vals = [v for v in inner.split(",") if v]
        r, g, b = (round(float(v)) for v in vals[:3])
        a = float(vals[3]) if len(vals) > 3 else 1
    return (r, g, b), a


def shot(page, name, full=False, clip=None):
    params = {"format": "png"}
    if full:
        h = page.eval("document.documentElement.scrollHeight")
        params.update(captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": page.width, "height": h, "scale": 1})
    if clip:
        params.update(captureBeyondViewport=True, clip={**clip, "scale": 1})
    data = base64.b64decode(page.cmd("Page.captureScreenshot", params)["data"])
    if name:
        (OUT / f"{name}.png").write_bytes(data)
    return data


def visible(page, sel):
    return page.eval(f"""(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!e) return null;
      const s = getComputedStyle(e); const r = e.getBoundingClientRect();
      return s.display !== 'none' && s.visibility === 'visible' && +s.opacity > 0.5 && r.width > 0; }})()""")


def text_contrast(page, label, sels):
    """Hide the words, screenshot each element's box, and take the worst contrast of its text colour
    against every background pixel under it (the field's lines included)."""
    boxes = page.eval("""(() => [%s].map((s) => { const e = document.querySelector(s); const r = e.getBoundingClientRect();
      return [s, r.left + scrollX, r.top + scrollY, r.width, r.height, getComputedStyle(e).color]; }))()""" % ",".join(json.dumps(s) for s in sels))
    hide = "[%s].forEach((s) => document.querySelectorAll(s + ', ' + s + ' *').forEach((e) => { e.style.setProperty('color', '%%s', 'important'); e.style.setProperty('-webkit-text-fill-color', '%%s', 'important'); }))" % ",".join(json.dumps(s) for s in sels)
    page.eval(hide % ("transparent", "transparent"))
    out = []
    for sel, x, y, w, h, color in boxes:
        data = shot(page, None, clip={"x": x, "y": y, "width": max(1, w), "height": max(1, h)})
        _, _, px = png_rgb(data)
        flat = [p for row in px for p in row]
        fg, alpha = parse_color(color)
        worst = None
        for bg in set(flat):
            eff = tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(fg, bg))
            c = contrast(eff, bg)
            worst = c if worst is None or c < worst else worst
        out.append((sel, worst))
    page.eval(hide % ("", ""))
    for sel, c in out:
        need = 3.0 if "large" in label else 4.5
        note(c >= need, f"{label}: {sel} text contrast, worst over its background pixels {c:.2f}:1 (≥ {need})")
    return out


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--origin")
    args = ap.parse_args()
    OUT = args.out
    OUT.mkdir(parents=True, exist_ok=True)
    srv = None
    if args.origin:
        origin = args.origin
    else:
        srv, origin = serve.make_server(serve.options(["--port", "0", "--mode", "direct", "--seallog", "--pay"]))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    with Browser() as b:
        # 1. screenshots: every page, 390 and 1440, light and dark; the whole page in the light
        for w, h, mobile in ((1440, 900, False), (390, 844, True)):
            for dark in (False, True):
                for path in PAGES:
                    p = b.page(w, h, mobile=mobile, dark=dark)
                    p.goto(origin + path, settle=1.5)
                    p.eval("document.fonts.ready.then(() => true)", True)
                    n = f"{NAME.get(path, path.strip('/'))}-{w}-{'dark' if dark else 'light'}"
                    shot(p, n)
                    if not dark and path != "/no-such-page":
                        shot(p, n + "-full", full=True)
                    p.close()
        # 2. 360 px: no horizontal scroll on any page; the phone hero is not cut
        for path in PAGES:
            p = b.page(360, 740, mobile=True)
            p.goto(origin + path, settle=1)
            sw = p.eval("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            note(sw[0] <= sw[1], f"360 px {path}: scrollWidth {sw[0]} ≤ clientWidth {sw[1]}")
            p.close()
        for w, h in ((360, 740), (390, 844)):
            p = b.page(w, h, mobile=True)
            p.goto(origin + "/", settle=1.5)
            r = p.eval("""(() => ['#hero-h', '.lede', '.cta-row', '.hero-note'].map((s) => { const e = document.querySelector(s);
              const r = e.getBoundingClientRect(); return [s, Math.round(r.left), Math.round(r.right), Math.round(r.bottom), e.scrollWidth > e.clientWidth + 1]; }))()""")
            for sel, left, right, bottom, over in r:
                note(left >= 0 and right <= w and not over, f"phone hero @{w}: {sel} inside the width ({left}..{right}), no overflow")
            cta = [x for x in r if x[0] == ".cta-row"][0]
            note(cta[3] <= h, f"phone hero @{w}x{h}: the buttons end at {cta[3]} px, in the first screen")
            shot(p, f"home-{w}-hero")
            p.close()
        # 3. the field: a ripple frame, the reduced-motion page, the page without JavaScript
        for w, h, mobile in ((1440, 900, False), (390, 844, True)):
            p = b.page(w, h, mobile=mobile)
            p.goto(origin + "/", settle=0.3)
            live = p.wait_for(f"{FIELD}.classList.contains('live') && !!{FIELD}.querySelector('canvas') && {FIELD}.dataset.ripples >= 1", 10)
            note(live, f"field @{w}: the canvas is live and a ripple ran ({p.eval(FIELD + '.dataset.ripples')})")
            b.pump(1.7)
            p.eval("document.querySelector('[data-testid=\"home-make\"]').dispatchEvent(new PointerEvent('pointerenter'))")
            b.pump(0.7)
            shot(p, f"field-{w}-ripple")
            text_contrast(p, f"hero @{w} light, mid-ripple", [".lede", ".hero-note"])
            b.pump(3)
            text_contrast(p, f"hero @{w} light, idle", [".lede", ".hero-note", ".slice-title"])
            text_contrast(p, f"hero @{w} light, idle (large text, 3:1)", [".h1-2"])
            p.close()
            p = b.page(w, h, mobile=mobile, dark=True)
            p.goto(origin + "/", settle=0.3)
            p.wait_for(f"{FIELD}.dataset.ripples >= 1", 10)
            b.pump(1.7)
            p.eval("document.querySelector('[data-testid=\"home-make\"]').dispatchEvent(new PointerEvent('pointerenter'))")
            b.pump(0.7)
            shot(p, f"field-{w}-dark-ripple")
            text_contrast(p, f"hero @{w} dark, mid-ripple", [".lede", ".hero-note"])
            p.close()
            p = b.page(w, h, mobile=mobile, reduce=True)
            p.goto(origin + "/", settle=3)
            asked = p.eval("performance.getEntriesByType('resource').some((e) => e.name.endsWith('/site/js/field.js'))")
            note(not asked and not p.eval(f"!!{FIELD}.querySelector('canvas')")
                 and p.eval(f"getComputedStyle({FIELD}, '::before').opacity") == "1",
                 f"reduced motion @{w}: no field.js, no canvas, the static grid shown")
            shot(p, f"field-{w}-reduced")
            p.close()
            p = b.page(w, h, mobile=mobile)
            p.cmd("Emulation.setScriptExecutionDisabled", {"value": True})
            p.goto(origin + "/", settle=1)
            try:
                grid = p.eval(f"[getComputedStyle({FIELD}, '::before').opacity, getComputedStyle({FIELD}, '::before').backgroundImage.slice(0, 40)]")
                note(grid[0] == "1" and "gradient" in grid[1], f"no JavaScript @{w}: the static grid ({grid})")
                note(visible(p, "[data-testid=home-make]"), f"no JavaScript @{w}: Make my drive visible in the hero")
                text_contrast(p, f"no JavaScript @{w}", [".lede", ".hero-note"])
                big = text_contrast(p, f"no JavaScript @{w} (large text, 3:1)", [".h1-2"])
            except RuntimeError as e:
                note(None, f"no JavaScript @{w}: could not evaluate ({e})")
            shot(p, f"home-{w}-nojs")
            p.close()
        # 4. the hero's keyboard order
        for w, h, mobile in ((1440, 900, False), (390, 844, True)):
            p = b.page(w, h, mobile=mobile)
            p.goto(origin + "/", settle=1.5)
            order = []
            for _ in range(9):
                p.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
                p.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
                b.pump(0.1)
                order.append(p.eval("(() => { const e = document.activeElement; return (e.dataset.testid || e.getAttribute('aria-label') || e.textContent.trim().slice(0, 24) || e.tagName); })()"))
            note(None, f"focus order @{w}: {' > '.join(order)}")
            hidden_focus = "head-make" in order[:order.index("home-make")] if "home-make" in order else True
            note("home-make" in order and not hidden_focus, f"focus @{w}: Make my drive reached, the hidden header button skipped")
            p.close()
        # 5. the header button on every page, with and without a drive
        make_drive = """new Promise((res) => { const r = indexedDB.open('mutis', 1);
          r.onupgradeneeded = () => r.result.createObjectStore('identity');
          r.onsuccess = () => { const db = r.result; const tx = db.transaction('identity', 'readwrite');
            tx.objectStore('identity').put({ v: 2 }, 'current'); tx.oncomplete = () => { db.close(); localStorage.setItem('mutis.drive', '1'); res(true); }; }; })"""
        first_paint = """addEventListener('DOMContentLoaded', () => { window.__hasDriveAtDCL = document.documentElement.hasAttribute('data-has-drive'); });"""
        for w, h, mobile in ((1440, 900, False), (390, 844, True)):
            p = b.page(w, h, mobile=mobile)
            p.goto(origin + "/how", settle=0.5)
            p.eval("new Promise((r) => { localStorage.clear(); const d = indexedDB.deleteDatabase('mutis'); d.onsuccess = d.onerror = d.onblocked = () => r(true); })", True)
            for path in PAGES:
                p.goto(origin + path, settle=1)
                if path == "/":
                    note(not visible(p, "[data-testid=head-make]"), f"header @{w} /: Make my drive hidden while the hero's is in view")
                    p.scroll_to(1400, settle=0.8)
                note(visible(p, "[data-testid=head-make]") and not visible(p, "[data-testid=head-open]"),
                     f"header @{w} {path}: Make my drive {'after the hero ' if path == '/' else ''}(no drive)")
            p.goto(origin + "/", settle=1)
            p.eval(make_drive, True)
            p.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": first_paint})
            for path in PAGES:
                p.goto(origin + path, settle=1.2)
                if path == "/":
                    note(p.eval("window.__hasDriveAtDCL"), f"drive @{w} /: Open my drive decided before the first paint")
                    order = p.eval("[...document.querySelectorAll('.hero .cta-row a')].sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left || a.getBoundingClientRect().top - b.getBoundingClientRect().top).map((a) => a.dataset.testid)")
                    note(order and order[0] == "home-open", f"drive @{w} /: the hero leads with Open my drive ({order})")
                    shot(p, f"home-{w}-with-drive")
                    p.scroll_to(1400, settle=0.8)
                note(visible(p, "[data-testid=head-open]") and not visible(p, "[data-testid=head-make]"),
                     f"header @{w} {path}: Open my drive (a drive in this browser)")
            p.close()
        # 6. the nav, Under the hood, tTARI, the cards, What to check
        p = b.page(1440, 900)
        p.goto(origin + "/", settle=1)
        nav = p.eval("[...document.querySelectorAll('.top-nav a')].map((a) => a.getAttribute('href'))")
        foot = p.eval("[...document.querySelectorAll('footer a')].filter((a) => a.getAttribute('href') === '/made').map((a) => a.textContent.trim())")
        note("/made" not in nav and foot == ["Under the hood"], f"nav {nav}; footer's /made link {foot}")
        for path in ("/", "/how", "/judges"):
            p.goto(origin + path, settle=1)
            first = p.eval("""(() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              let n; while ((n = w.nextNode())) { if (!n.textContent.includes('tTARI')) continue; const e = n.parentElement;
                if (e.closest('[hidden], [aria-hidden="true"], script, details:not([open])') || !e.getClientRects().length) continue;
                const a = e.closest('a'); const box = e.closest('p, li, td, div');
                return [e.closest('section, aside, header, footer')?.id || '', n.textContent.trim().slice(0, 60), a ? a.getAttribute('href') : null,
                  box && box.querySelector('a[href$="#ttari"]') ? 'link beside' : '']; } return null; })()""")
            note(None, f"first visible tTARI on {path}: {first}")
        p.goto(origin + "/judges", settle=1)
        info = p.eval("""(() => { const h = [...document.querySelectorAll('h2')].find((e) => /What to check/.test(e.textContent));
          const sec = h?.closest('section'); const r = (sec?.querySelector('table') || h)?.getBoundingClientRect();
          return { h2: h ? [Math.round(h.getBoundingClientRect().left + h.getBoundingClientRect().width / 2), getComputedStyle(h).textAlign] : null,
                   table: r ? Math.round(r.left + r.width / 2) : null, height: document.documentElement.scrollHeight,
                   tracks: document.querySelectorAll('#t1, #t2').length, made: !!document.querySelector('main a[href="/made"]') }; })()""")
        note(None, f"/judges @1440: {info} (viewport centre 720)")
        p.goto(origin + "/", settle=1)
        cards = p.eval("document.querySelectorAll('.sides > li').length")
        note(cards == 4, f"Who sees what on /: {cards} cards")
        p.close()
    if srv:
        srv.shutdown()
    (OUT / "devil-report.json").write_text(json.dumps(REPORT, indent=1, ensure_ascii=False))
    fails = [r for r in REPORT if r[0] == "FAIL"]
    print(f"devil: {len(REPORT)} lines, {len(fails)} FAIL")


if __name__ == "__main__":
    main()
