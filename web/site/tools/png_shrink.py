# SPDX-License-Identifier: MIT
"""Lossless PNG shrinking for the cards and icons render-images.py writes (og.png, og-s.png, the app icons and the
PNGs inside favicon.ico). Python standard library only.

  python3 -I web/site/tools/png_shrink.py FILE.png|FILE.ico ...

Chromium's screenshots are 8-bit RGB or RGBA with one filter and zlib's default effort. This decodes every pixel and
writes the same pixels in the smallest of: the same colour type, RGB when every alpha is opaque, a palette when there
are 256 colours or fewer (with tRNS for any alpha), and grey when every pixel is grey; each with the five PNG filters
for every row and a per-row choice (the minimum sum of absolute differences), compressed by zlib at level 9 with
the default and the filtered strategy. Only the critical chunks are written (Chromium writes no colour chunk; bKGD,
a viewer's background, is dropped). The result is decoded again and compared pixel for pixel with the source before it
replaces it, and only when it is smaller: the look can't change.
"""
import struct
import sys
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def chunks(data: bytes):
    if data[:8] != SIGNATURE:
        raise ValueError("not a PNG")
    at = 8
    while at < len(data):
        size, kind = struct.unpack(">I4s", data[at:at + 8])
        yield kind, data[at + 8:at + 8 + size]
        at += 12 + size


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def unfilter(raw: bytes, width: int, height: int, bpp: int, row_bytes: int) -> list[bytes]:
    rows, prev, at = [], bytes(row_bytes), 0
    for _ in range(height):
        kind, line = raw[at], bytearray(raw[at + 1:at + 1 + row_bytes])
        at += 1 + row_bytes
        for i in range(row_bytes):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif kind == 4:
                line[i] = (line[i] + paeth(a, b, c)) & 255
            elif kind != 0:
                raise ValueError(f"unknown filter {kind}")
        rows.append(bytes(line))
        prev = line
    return rows


def decode(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """(width, height, every pixel as RGBA) of an 8-bit, non-interlaced PNG."""
    ihdr, idat, palette, trns = None, b"", None, None
    for kind, body in chunks(data):
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            trns = body
    width, height, depth, ctype, _, _, interlace = ihdr
    if interlace or ctype not in CHANNELS or (depth != 8 and ctype != 3):
        raise ValueError(f"unsupported PNG (bit depth {depth}, colour type {ctype}, interlace {interlace})")
    if ctype == 3 and depth not in (1, 2, 4, 8):
        raise ValueError(f"unsupported palette depth {depth}")
    channels = CHANNELS[ctype]
    row_bytes = (width * channels * depth + 7) // 8
    rows = unfilter(zlib.decompress(idat), width, height, max(1, channels * depth // 8), row_bytes)
    pixels = []
    for row in rows:
        if ctype == 3:
            per = 8 // depth
            for x in range(width):
                index = (row[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1)
                r, g, b = palette[index]
                pixels.append((r, g, b, trns[index] if trns and index < len(trns) else 255))
        elif ctype == 2:
            pixels += [(row[i], row[i + 1], row[i + 2], 255) for i in range(0, len(row), 3)]
        elif ctype == 6:
            pixels += [tuple(row[i:i + 4]) for i in range(0, len(row), 4)]
        elif ctype == 0:
            pixels += [(v, v, v, 255) for v in row]
        else:
            pixels += [(row[i], row[i], row[i], row[i + 1]) for i in range(0, len(row), 2)]
    return width, height, pixels


def filtered(rows: list[bytes], bpp: int, choice: int | None) -> bytes:
    """Rows filtered with one filter type for all (`choice`), or per row by the minimum sum of absolute values."""
    out, prev = bytearray(), bytes(len(rows[0]))
    for row in rows:
        n = len(row)
        left = bytes(bpp) + row[:n - bpp]
        upleft = bytes(bpp) + prev[:n - bpp]
        options = {0: row}
        if choice in (None, 1):
            options[1] = bytes((row[i] - left[i]) & 255 for i in range(n))
        if choice in (None, 2):
            options[2] = bytes((row[i] - prev[i]) & 255 for i in range(n))
        if choice in (None, 3):
            options[3] = bytes((row[i] - ((left[i] + prev[i]) >> 1)) & 255 for i in range(n))
        if choice in (None, 4):
            options[4] = bytes((row[i] - paeth(left[i], prev[i], upleft[i])) & 255 for i in range(n))
        if choice is None:
            kind = min(options, key=lambda k: sum(v if v < 128 else 256 - v for v in options[k]))
        else:
            kind = choice
        out.append(kind)
        out += options[kind]
        prev = row
    return bytes(out)


def candidates(width: int, height: int, pixels: list) -> list[tuple[int, int, list[bytes], bytes, bytes]]:
    """(colour type, bit depth, unfiltered rows, PLTE, tRNS) for every lossless way to write these pixels."""
    opaque = all(p[3] == 255 for p in pixels)
    grey = all(p[0] == p[1] == p[2] for p in pixels)
    rows_of = lambda per_pixel: [b"".join(per_pixel(p) for p in pixels[y * width:(y + 1) * width]) for y in range(height)]  # noqa: E731
    out = [(2, 8, rows_of(lambda p: bytes(p[:3])), b"", b"")] if opaque else [(6, 8, rows_of(bytes), b"", b"")]
    if grey:
        out.append((0, 8, rows_of(lambda p: bytes(p[:1])), b"", b"") if opaque else (4, 8, rows_of(lambda p: bytes((p[0], p[3]))), b"", b""))
    colours = sorted(set(pixels), key=lambda p: (p[3] == 255, p))   # the translucent ones first: a shorter tRNS
    if len(colours) <= 256:
        index = {c: i for i, c in enumerate(colours)}
        depth = 1 if len(colours) <= 2 else 2 if len(colours) <= 4 else 4 if len(colours) <= 16 else 8
        per = 8 // depth
        rows = []
        for y in range(height):
            row = bytearray((width + per - 1) // per)
            for x in range(width):
                row[x // per] |= index[pixels[y * width + x]] << (8 - depth * (x % per + 1))
            rows.append(bytes(row))
        alphas = bytes(c[3] for c in colours if c[3] != 255)
        out.append((3, depth, rows, b"".join(bytes(c[:3]) for c in colours), alphas))
    return out


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def encode(width: int, height: int, ctype: int, depth: int, rows: list[bytes], plte: bytes, trns: bytes) -> bytes:
    bpp = max(1, CHANNELS[ctype] * depth // 8)
    best = None
    for choice in (0, 1, 2, 3, 4, None):
        data = filtered(rows, bpp, choice)
        for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED):
            z = zlib.compressobj(9, zlib.DEFLATED, 15, 9, strategy)
            packed = z.compress(data) + z.flush()
            if best is None or len(packed) < len(best):
                best = packed
    head = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, 0))
    extra = (chunk(b"PLTE", plte) + (chunk(b"tRNS", trns) if trns else b"")) if ctype == 3 else b""
    return SIGNATURE + head + extra + chunk(b"IDAT", best) + chunk(b"IEND", b"")


def shrink(data: bytes) -> bytes:
    """The smallest lossless encoding of a PNG's pixels, or the PNG itself when nothing is smaller."""
    width, height, pixels = decode(data)
    best = data
    for ctype, depth, rows, plte, trns in candidates(width, height, pixels):
        out = encode(width, height, ctype, depth, rows, plte, trns)
        if len(out) < len(best):
            best = out
    if best is not data and decode(best) != (width, height, pixels):
        raise ValueError("the smaller PNG has other pixels")
    return best


def shrink_ico(data: bytes) -> bytes:
    """An ICO whose images are PNGs (render-images.py's write_ico), each image shrunk, the directory rewritten."""
    _, kind, count = struct.unpack("<HHH", data[:6])
    if kind != 1:
        raise ValueError("not an icon file")
    entries = [struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i]) for i in range(count)]
    images = [shrink(data[e[7]:e[7] + e[6]]) for e in entries]
    at, table, body = 6 + 16 * count, b"", b""
    for e, image in zip(entries, images):
        table += struct.pack("<BBBBHHII", *e[:6], len(image), at + len(body))
        body += image
    return data[:6] + table + body


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: png_shrink.py FILE.png|FILE.ico ...", file=sys.stderr)
        return 2
    for name in sys.argv[1:]:
        path = Path(name)
        before = path.read_bytes()
        after = shrink_ico(before) if path.suffix == ".ico" else shrink(before)
        if len(after) < len(before):
            path.write_bytes(after)
        print(f"{path.name}: {len(before):,} → {len(after):,} B (same pixels)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
