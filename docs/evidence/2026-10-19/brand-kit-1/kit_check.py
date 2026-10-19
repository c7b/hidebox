# SPDX-License-Identifier: MIT
"""What this pass shipped, held against the owner's brand kit (docs/review/brand-kit-1.md). The kit is kept outside
this repository; point the script at its folder:

  python3 -I docs/evidence/2026-10-19/brand-kit-1/kit_check.py KIT_DIR

1. Shapes: the path data of the kit's icon, wordmark and lockup against the sprite's i-hidebox and i-wordmark, the
   favicon and docs/media's lockups (re-encoded as relative, two-decimal commands): every end and control point, the
   largest distance in SVG units. Only M, L, H, V, Q and Z occur in the kit.
2. Rasters: each PNG icon in web/site/static against the kit's file of the same name, as lime coverage (the green
   channel over the #0A0A0A tile, alpha applied, since the two limes differ on purpose: the site's #BCFE00, the kit's
   #ACFF00): the mean difference per pixel, the covered area and the shift of its centre.
Python stdlib only.
"""
import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TOK = re.compile(r"[MLHVQZmlhvqz]|-?(?:\d+\.?\d*|\.\d+)")
ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "Z": 0}


def points(d: str) -> list[tuple[float, float]]:
    """Every absolute end and control point of a path, in order."""
    pts, x, y, sx, sy, cmd, toks, i = [], 0.0, 0.0, 0.0, 0.0, None, TOK.findall(d), 0
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                x, y = sx, sy
                continue
        rel, c = cmd.islower(), cmd.upper()
        a = [float(v) for v in toks[i:i + ARGS[c]]]
        i += ARGS[c]
        if c == "M":
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            sx, sy = x, y
            pts.append((x, y))
            cmd = "l" if rel else "L"
        elif c == "L":
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            pts.append((x, y))
        elif c == "H":
            x = x + a[0] if rel else a[0]
            pts.append((x, y))
        elif c == "V":
            y = y + a[0] if rel else a[0]
            pts.append((x, y))
        elif c == "Q":
            pts.append((x + a[0], y + a[1]) if rel else (a[0], a[1]))
            x, y = (x + a[2], y + a[3]) if rel else (a[2], a[3])
            pts.append((x, y))
    return pts


def paths(svg: str) -> list[str]:
    return re.findall(r' d="([^"]+)"', svg)


def symbol(sprite: str, name: str) -> str:
    return re.search(rf'<symbol id="{name}"[^>]*>(.*?)</symbol>', sprite, re.S).group(1)


def compare(what: str, kit_d: str, ours_d: str) -> str:
    a, b = points(kit_d), points(ours_d)
    if len(a) != len(b):
        return f"{what}: {len(a)} points in the kit, {len(b)} here: NOT THE SAME SHAPE"
    err = max(max(abs(p[0] - q[0]), abs(p[1] - q[1])) for p, q in zip(a, b))
    return f"{what}: {len(a)} points, largest distance {err:.4f} units; {len(kit_d):,} characters in the kit, {len(ours_d):,} here"


def png(path: Path):
    """(width, height, rows of RGBA tuples) of an 8-bit RGB or RGBA PNG, not interlaced."""
    data = path.read_bytes()
    w, h, _, kind = struct.unpack(">IIBB", data[16:26])
    pos, idat = 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        if data[pos + 4:pos + 8] == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    raw, bpp = zlib.decompress(idat), {2: 3, 6: 4}[kind]
    stride, rows, prev, i = w * bpp, [], bytearray(w * bpp), 0
    for _ in range(h):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a, b, c = line[x - bpp] if x >= bpp else 0, prev[x], prev[x - bpp] if x >= bpp else 0
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
        rows.append([tuple(line[x * bpp:x * bpp + bpp]) + ((255,) if bpp == 3 else ()) for x in range(w)])
        prev = line
    return w, h, rows


def coverage(p) -> float:
    alpha = p[3] / 255
    return max(0.0, min(1.0, (p[1] - 10) * alpha / 244))


def raster(name: str, kit: Path) -> str:
    w, h, a = png(kit / name)
    _, _, b = png(ROOT / "web/site/static" / name)
    diff = area_a = area_b = xa = ya = xb = yb = 0.0
    for y in range(h):
        for x in range(w):
            u, v = coverage(a[y][x]), coverage(b[y][x])
            diff += abs(u - v)
            area_a, area_b = area_a + u, area_b + v
            xa, ya, xb, yb = xa + u * x, ya + u * y, xb + v * x, yb + v * y
    return (f"{name} ({w} x {h}): {100 * diff / (w * h):.2f} % mean difference per pixel; area {100 * (area_b - area_a) / area_a:+.2f} %; "
            f"centre shifted ({xb / area_b - xa / area_a:+.2f}, {yb / area_b - ya / area_a:+.2f}) px")


def main() -> int:
    kit = Path(sys.argv[1])
    sprite = (ROOT / "web/shared/ui/icons.svg").read_text()
    icon = paths((kit / "hidebox-icon.svg").read_text())[0]
    word, dot = paths((kit / "hidebox-wordmark-dark.svg").read_text())
    lock = paths((kit / "hidebox-lockup-dark.svg").read_text())
    lines = ["Shapes (SVG units; the icon's grid is 32, the wordmark's 148 x 34):",
             compare("i-hidebox", icon, paths(symbol(sprite, "i-hidebox"))[0]),
             compare("i-wordmark, letters", word, paths(symbol(sprite, "i-wordmark"))[0]),
             compare("i-wordmark, rhombus", dot, paths(symbol(sprite, "i-wordmark"))[1])]
    for rel in ("web/site/static/favicon.svg", "web/shared/brand/symbol.svg", "docs/media/hidebox-mark.svg"):
        lines.append(compare(rel, icon, paths((ROOT / rel).read_text())[0]))
    for rel in ("docs/media/hidebox-lockup-dark.svg", "docs/media/hidebox-lockup-light.svg"):
        ours = paths((ROOT / rel).read_text())
        lines += [compare(f"{rel}, {part}", k, o) for part, k, o in zip(("box", "letters", "rhombus"), lock, ours)]
    lines.append("Rasters (lime coverage, the kit's file against this repository's):")
    lines += [raster(n, kit) for n in ("icon-512.png", "icon-192.png", "apple-touch-icon.png", "icon-maskable-512.png", "favicon-32.png")]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
