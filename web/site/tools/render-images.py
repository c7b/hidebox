# SPDX-License-Identifier: MIT
"""Renders the OG cards and app icons in web/site/og/ to PNGs in web/site/static/ with headless
Chromium (Debian package), over the DevTools pipe, and wraps the 192 px icon as favicon.ico (an ICO
may hold PNG data; Bing, feed readers and some unfurlers ask for that path by name). Python standard
library only; run as `build` on the server: python3 -I web/site/tools/render-images.py
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I leaves the script's own directory out
from cdp import Browser  # noqa: E402

SITE = Path(__file__).resolve().parents[1]
OG_MAX_BYTES = 150 * 1024   # 11-brand §13.10
JOBS = (("og.html", "og.png", 1200, 630), ("og-s.html", "og-s.png", 1200, 630),
        ("icon.html", "icon-512.png", 512, 512), ("icon.html", "icon-192.png", 192, 192),
        ("icon.html", "apple-touch-icon.png", 180, 180))


def write_ico(png: Path, out: Path) -> None:
    """One ICO directory entry whose image data is the PNG as it is (192 px, 32-bit)."""
    data = png.read_bytes()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 192, 192, 0, 0, 1, 32, len(data), len(header) + 16)
    out.write_bytes(header + entry + data)


def main() -> int:
    failed = False
    with Browser() as browser:
        for source, target, width, height in JOBS:
            page = browser.page(width, height)
            page.goto((SITE / "og" / source).as_uri(), settle=1.0)
            page.eval("document.fonts.ready.then(() => true)", await_promise=True)
            out = SITE / "static" / target
            page.screenshot(str(out))
            size = out.stat().st_size
            print(f"{target}: {width}x{height}, {size} bytes")
            if target.startswith("og") and size > OG_MAX_BYTES:
                print(f"  too large (limit {OG_MAX_BYTES})")
                failed = True
            for line in page.console():
                print("  console:", line)
                failed = failed or "OTS parsing error" in line
    write_ico(SITE / "static" / "icon-192.png", SITE / "static" / "favicon.ico")
    print(f"favicon.ico: {(SITE / 'static' / 'favicon.ico').stat().st_size} bytes")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
