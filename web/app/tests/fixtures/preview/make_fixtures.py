#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the hostile preview fixtures (docs/review/preview-1.md). Python stdlib only:

  python3 -I web/app/tests/fixtures/preview/make_fixtures.py

Every file tries to run code or to be taken for something it isn't. A script that ran would set the global canary
`top.__pwned`, write `__pwned` to localStorage and ask for /__canary/<which>; the tests check none of that happens.

  script.svg     an SVG with <script>, onload, a javascript: link, a foreignObject with an <img onerror>, and an
                 <image> asking for /__canary/svg-image (the drawing: an open box in lime on gunmetal)
  svg-named.png  the same SVG under a picture's name: the bytes say SVG
  png-named.svg  a real PNG under an SVG's name: the bytes say PNG
  notes.md       Markdown with <script>, an <img onerror>, a javascript: link and an autolink to one
  page.txt       a whole HTML page under a text file's name
  polyglot.htm  a valid GIF89a, then an HTML page after the GIF's trailer
  big.txt        300 KB of text (the preview shows the first 256 KB)
  empty.txt      zero bytes
  utf16.txt      text in UTF-16 (NUL bytes: not UTF-8, so no preview)
  tiny.pdf       a PDF (download only)
"""
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

CANARY = "top.__pwned='{w}';try{{localStorage.setItem('__pwned','{w}')}}catch(e){{}};fetch('/__canary/{w}')"

SVG = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="480" height="320" viewBox="0 0 480 320"
     onload="{CANARY.format(w='svg-onload')}">
  <script>{CANARY.format(w='svg-script')}</script>
  <rect width="480" height="320" rx="24" fill="#17191C"/>
  <path d="M150 140 L240 110 L330 140 L240 170 Z" fill="#BCFE00"/>
  <path d="M150 140 L240 170 L240 250 L150 220 Z" fill="#9BD000"/>
  <path d="M330 140 L240 170 L240 250 L330 220 Z" fill="#7FAE00"/>
  <a xlink:href="javascript:{CANARY.format(w='svg-link')}"><text x="24" y="296" fill="#F5F5F5" font-family="sans-serif" font-size="18">hostile.svg</text></a>
  <image href="/__canary/svg-image.png" x="0" y="0" width="8" height="8"/>
  <foreignObject x="0" y="0" width="480" height="40">
    <div xmlns="http://www.w3.org/1999/xhtml"><img src="x" onerror="{CANARY.format(w='svg-foreign')}"/></div>
  </foreignObject>
</svg>
"""

MD = f"""# Trip notes

Pack the **charger**. The code is in the [shared doc](javascript:{CANARY.format(w='md-link')}).

<script>{CANARY.format(w='md-script')}</script>

<img src="x" onerror="{CANARY.format(w='md-img')}">

<javascript:{CANARY.format(w='md-autolink')}>

- [ ] tickets
- [x] passports
"""

HTML = f"""<!doctype html>
<html><head><title>Invoice</title></head>
<body><h1>Invoice</h1>
<script>{CANARY.format(w='txt-html')}</script>
<img src="x" onerror="{CANARY.format(w='txt-img')}">
</body></html>
"""


def png(width, height):
    """An RGB PNG: the gunmetal stage with a lime band and a darker square, so a preview is easy to recognise."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if height * 0.42 < y < height * 0.58:
                px = (0xBC, 0xFE, 0x00)
            elif width * 0.3 < x < width * 0.7 and height * 0.2 < y < height * 0.8:
                px = (0x0A, 0x0A, 0x0A)
            else:
                px = (0x2B, 0x2F, 0x35)
            row += bytes(px)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


# A 1 x 1 GIF89a (one lime pixel), complete up to its trailer (0x3B).
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xbc\xfe\x00\x00\x00\x00"
       b"!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")


def big_text():
    line = "The quick brown fox jumps over the lazy dog, then naps in the sun. "
    out, n = [], 0
    while n < 300 * 1024:
        s = f"{len(out) + 1:05d} {line}\n"
        out.append(s)
        n += len(s)
    return "".join(out).encode()[:300 * 1024]


FILES = {
    "script.svg": SVG.encode(),
    "svg-named.png": SVG.encode(),
    "png-named.svg": png(480, 320),
    "notes.md": MD.encode(),
    "page.txt": HTML.encode(),
    "polyglot.htm": GIF + HTML.encode(),
    "big.txt": big_text(),
    "empty.txt": b"",
    "utf16.txt": "Hello in UTF-16.\n".encode("utf-16"),
    "tiny.pdf": PDF,
}


def main():
    for name, data in FILES.items():
        with open(os.path.join(HERE, name), "wb") as f:
            f.write(data)
        print(f"{name}: {len(data)} bytes")


if __name__ == "__main__":
    main()
