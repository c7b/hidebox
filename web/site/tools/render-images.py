# SPDX-License-Identifier: MIT
"""Renders the share cards in web/site/og/ and the app icons to PNGs in web/site/static/ with headless Chromium
(Debian package), over the DevTools pipe. Each card gets the public name from tools/build.py (BRAND) and Geist from
web/shared/fonts/geist/ (the pinned file, handed to the page as data, since a file:// page can't load a font file); a
card's pictures (the home's hero still on og.html, from web/site/media/) are decoded before the picture is taken.
The icons are SVGs drawn at their pixel size: static/favicon.svg (the open box on its rounded ink tile, the corners
transparent) as favicon-32.png, icon-192.png and icon-512.png, and at 16, 32 and 48 px into favicon.ico (an ICO may
hold PNG data; Bing, feed readers and some unfurlers ask for that path by name); og/icon.svg (the same box on a
full-bleed square, which iOS rounds) as apple-touch-icon.png; og/icon-maskable.svg (the box inside the safe zone) as
icon-maskable-512.png. Each PNG, and each one inside the ICO, is then shrunk without changing a pixel (png_shrink.py).
Name some of those files to render only them. Python standard library only; run as `build` on the server:
python3 -I web/site/tools/render-images.py [FILE ...]
"""
import base64
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I leaves the script's own directory out
from cdp import Browser  # noqa: E402
from png_shrink import shrink  # noqa: E402

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE.parents[1]
GEIST = ROOT / "web" / "shared" / "fonts" / "geist" / "Geist-Variable.woff2"


def brand() -> str:
    m = re.search(r'^BRAND = "([^"]+)"', (ROOT / "tools" / "build.py").read_text(), re.M)
    if not m:
        raise SystemExit("tools/build.py: no BRAND")
    return m.group(1)


# Geist as a data URL and the brand into every {{BRAND}} (text and the wordmark's label), before the fonts settle.
PREPARE = """((font, name) => {
  const face = new FontFace('Geist', `url(${font})`, { weight: '100 900' });
  document.fonts.add(face);
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walk.nextNode());) n.nodeValue = n.nodeValue.replaceAll('{{BRAND}}', name);
  for (const e of document.querySelectorAll('[aria-label*="{{BRAND}}"]')) e.setAttribute('aria-label', e.getAttribute('aria-label').replaceAll('{{BRAND}}', name));
  return face.load().then(() => document.fonts.ready)
    .then(() => Promise.all([...document.images].map((i) => i.decode()))).then(() => true);
})"""
OG_MAX_BYTES = 150 * 1024   # 11-brand §13.10
# The site's card and one per kind of link (viral-1): a secret (/s/), a paid link (/p/), a drop link (/d/).
CARDS = (("og.html", "og.png", 1200, 630), ("og-s.html", "og-s.png", 1200, 630), ("og-p.html", "og-p.png", 1200, 630),
         ("og-d.html", "og-d.png", 1200, 630))
ICONS = (("static/favicon.svg", "favicon-32.png", 32), ("static/favicon.svg", "icon-192.png", 192),
         ("static/favicon.svg", "icon-512.png", 512), ("og/icon.svg", "apple-touch-icon.png", 180),
         ("og/icon-maskable.svg", "icon-maskable-512.png", 512))
ICO = ("static/favicon.svg", "favicon.ico", (16, 32, 48))


def draw(browser, source: Path, size: int) -> bytes:
    """An SVG without width and height fills the page: drawn at size × size, transparent where it paints nothing."""
    page = browser.page(size, size)
    page.cmd("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
    page.goto(source.as_uri(), settle=0.5)
    data = base64.b64decode(page.cmd("Page.captureScreenshot", {"format": "png"})["data"])
    page.close()
    return shrink(data)


def write_ico(pngs: list[bytes], out: Path) -> None:
    """One ICO directory entry per PNG, each entry's image data the PNG as it is (32-bit)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    at, entries, images = len(header) + 16 * len(pngs), b"", b""
    for data in pngs:
        width, height = struct.unpack(">II", data[16:24])
        entries += struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32, len(data), at + len(images))
        images += data
    out.write_bytes(header + entries + images)


def main() -> int:
    wanted = set(sys.argv[1:])
    known = {c[1] for c in CARDS} | {i[1] for i in ICONS} | {ICO[1]}
    if wanted - known:
        raise SystemExit(f"render-images.py: unknown files {sorted(wanted - known)} (known: {sorted(known)})")
    pick = lambda target: not wanted or target in wanted   # noqa: E731
    failed = False
    font = "data:font/woff2;base64," + base64.b64encode(GEIST.read_bytes()).decode()
    name = brand()
    with Browser() as browser:
        for source, target, width, height in CARDS:
            if not pick(target):
                continue
            page = browser.page(width, height)
            page.goto((SITE / "og" / source).as_uri(), settle=1.0)
            page.eval(f"{PREPARE}({json.dumps(font)}, {json.dumps(name)})", await_promise=True)
            out = SITE / "static" / target
            page.screenshot(str(out))
            out.write_bytes(shrink(out.read_bytes()))
            size = out.stat().st_size
            print(f"{target}: {width}x{height}, {size} bytes")
            if size > OG_MAX_BYTES:
                print(f"  too large (limit {OG_MAX_BYTES})")
                failed = True
            for line in page.console():
                print("  console:", line)
                failed = failed or "OTS parsing error" in line
        for source, target, size in ICONS:
            if not pick(target):
                continue
            out = SITE / "static" / target
            out.write_bytes(draw(browser, SITE / source, size))
            print(f"{target}: {size}x{size}, {out.stat().st_size} bytes")
        source, target, sizes = ICO
        if pick(target):
            out = SITE / "static" / target
            write_ico([draw(browser, SITE / source, size) for size in sizes], out)
            print(f"{target}: {', '.join(f'{s}x{s}' for s in sizes)}, {out.stat().st_size} bytes")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
