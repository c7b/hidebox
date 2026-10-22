#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The mark in the middle of the app's QR codes (ui/qr.js, share-simple), checked without a phone:

  python3 -I web/app/ui/tests/qr_logo.py

Node draws each code with the app's own encoder; qrread.py (written from ISO/IEC 18004, not from the encoder)
reads it back. Checked:
1. The levels. Every version 1 to 10 at L, M, Q and H holds exactly the bytes of ISO's capacity table (one more
   byte takes the next version) and reads back at that level, both format copies and every block's RS remainder
   right. Reed-Solomon itself against the published 1-Q codewords of "HELLO WORLD".
2. The mark, for a /s/ link with its 43-character key (and 40 more with random ids and keys), a /p/ link, a /d/
   link, a Tari address as the pay page shows it and the Settings code (/#to=<address>): level Q; the mark 15 to
   20 % of the width with a one-module margin of pad; no finder, separator, timing, format or version module under
   the pad, and no alignment pattern but the centre one (versions 7 and up; it holds no data). Every module under
   the pad is mapped to its codeword and RS block; in each block the codewords it touches stay at most
   floor(ec / 2) - 2, two under what the block corrects.
3. That it still reads: the code as drawn (the pad light) and the worst case (every module under the pad
   inverted) both correct back to the payload. A text too long for level Q is drawn at M or L without the mark.
4. The mark the code draws is web/shared/brand/symbol.svg's.
Python stdlib and node. Prints one line per payload and exits 1 on any failure."""
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
import qrread  # noqa: E402

# ISO/IEC 18004 Table 7: byte mode capacity of versions 1-10.
CAPACITY = {"L": [17, 32, 53, 78, 106, 134, 154, 192, 230, 271], "M": [14, 26, 42, 62, 84, 106, 122, 152, 180, 213],
            "Q": [11, 20, 32, 46, 60, 74, 86, 108, 130, 151], "H": [7, 14, 24, 34, 44, 58, 64, 84, 98, 119]}
# Thonky's QR tutorial, "HELLO WORLD" at 1-Q: the data codewords and the 13 EC codewords.
HELLO = ([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236], [168, 72, 22, 82, 217, 54, 156, 0, 46, 15, 180, 122, 16])
B64U = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
ORIGIN = "https://hidebox.app"
MARGIN = 2

NODE = r"""
import * as q from './web/app/ui/qr.js';
const out = { mark: q.MARK, levels: [], codes: [] };
const { inputs, capacity } = JSON.parse(process.argv[1]);
const text = (n) => Array.from({ length: n }, (_, i) => String.fromCharCode(33 + ((i * 37 + n) % 94))).join('');
for (const [level, caps] of Object.entries(capacity)) {
  caps.forEach((n, v) => {
    const at = q.qr(text(n), { level });
    let next = null;
    try { next = q.qr(text(n + 1), { level }).version; } catch (e) { next = e instanceof RangeError ? 'too long' : String(e); }
    const grid = Array.from({ length: at.size }, (_, y) => Array.from({ length: at.size }, (_, x) => (at.dark(x, y) ? '1' : '0')).join(''));
    out.levels.push({ level, version: v + 1, n, text: text(n), got: at.version, gotLevel: at.level, next, grid });
  });
}
for (const [name, t] of inputs) {
  const { code, spot } = q.qrCode(t);
  const grid = Array.from({ length: code.size }, (_, y) => Array.from({ length: code.size }, (_, x) => (code.dark(x, y) ? '1' : '0')).join(''));
  out.codes.push({ name, text: t, version: code.version, level: code.level, size: code.size, spot, grid, ...q.qrPath(code, spot) });
}
console.log(JSON.stringify(out));
"""


def rand(rnd, alphabet, n):
    return "".join(rnd.choice(alphabet) for _ in range(n))


def inputs():
    rnd = random.Random(20261021)
    address = "otl_esm_1" + rand(rnd, BECH32, 109)                        # a 64-byte testnet address, 118 characters
    long_address = "otl_esm_1" + rand(rnd, BECH32, 211)                   # a 128-byte one, the longest Ootle allows
    out = [("/s/ link", f"{ORIGIN}/s/{rand(rnd, B64U, 22)}#1{rand(rnd, B64U, 43)}"),
           ("/p/ link", f"{ORIGIN}/p/{rand(rnd, B64U, 22)}#5{rand(rnd, B64U, 43)}"),
           ("/d/ link", f"{ORIGIN}/d/{rand(rnd, CROCKFORD, 10)}"),
           ("Tari address (pay page)", address),
           ("Settings code (/#to=)", f"{ORIGIN}/#to={address}"),
           ("Settings code, a 128-byte address", f"{ORIGIN}/#to={long_address}")]
    out += [(f"/s/ link #{i + 2}", f"{ORIGIN}/s/{rand(rnd, B64U, 22)}#1{rand(rnd, B64U, 43)}") for i in range(40)]
    return out


def function_parts(ver, size):
    """(modules no mark may cover, the alignment patterns' modules by centre): finders with their separators, both
    timing lines, both format copies with the dark module, the version blocks."""
    never = set()
    for ox, oy in ((0, 0), (size - 8, 0), (0, size - 8)):
        never |= {(ox + x, oy + y) for x in range(8) for y in range(8)}
    never |= {(6, i) for i in range(size)} | {(i, 6) for i in range(size)}
    never |= {(8, i) for i in range(9)} | {(i, 8) for i in range(9)}
    never |= {(size - 1 - i, 8) for i in range(8)} | {(8, size - 1 - i) for i in range(8)}
    if ver >= 7:
        never |= {(size - 11 + i % 3, i // 3) for i in range(18)} | {(i // 3, size - 11 + i % 3) for i in range(18)}
    centres = qrread.align_pos(ver, size)
    align = {}
    for i, a in enumerate(centres):
        for j, b in enumerate(centres):
            last = len(centres) - 1
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            align[(a, b)] = {(a + dx, b + dy) for dx in range(-2, 3) for dy in range(-2, 3)}
    return never, align


def check_code(c, fails):
    name, text, size, ver = c["name"], c["text"], c["size"], c["version"]
    grid = [[int(ch) for ch in row] for row in c["grid"]]
    clean = qrread.decode(grid)
    if not (clean["payload"] == text and clean["clean"] and clean["format_ok_both_copies"] and clean["ecl"] == c["level"]):
        fails.append(f"{name}: the code itself doesn't read back cleanly ({clean['ecl']}, {clean['payload'][:40]!r})")
    spot = c["spot"]
    if spot is None:
        drawn = qrread.scan(c["d"], c["view"])
        ok = drawn["payload"] == text and drawn["clean"]
        if not ok:
            fails.append(f"{name}: drawn without the mark, it doesn't read back")
        return f"{name}: {len(text.encode())} B, version {ver}-{c['level']}, no mark (too long for level Q), reads back {'ok' if ok else 'NO'}", 0
    at, side = spot["at"], spot["side"]
    mark = side - 2
    if c["level"] != "Q":
        fails.append(f"{name}: a code with the mark is level {c['level']}, not Q")
    if not (0.15 <= mark / size <= 0.20 and at * 2 + side == size):
        fails.append(f"{name}: the mark is {mark}/{size} = {mark / size:.1%} of the width, off centre or outside 15-20 %")
    pad = {(x, y) for x in range(at, at + side) for y in range(at, at + side)}
    never, align = function_parts(ver, size)
    centre = ((size - 1) // 2, (size - 1) // 2)
    if pad & never:
        fails.append(f"{name}: the pad covers finder, timing, format or version modules {sorted(pad & never)[:4]}")
    covered = [a for a, mods in align.items() if mods & pad]
    if any(a != centre for a in covered) or (covered and ver < 7):
        fails.append(f"{name}: the pad covers alignment patterns {covered}")
    # Every module under the pad -> its codeword (8 modules each, in zigzag order) -> its block.
    order = qrread.placement(ver, size)
    ncw = len(order) // 8
    index = {xy: k // 8 for k, xy in enumerate(order) if k // 8 < ncw}
    where, lengths = qrread.interleave(ver, c["level"], ncw)
    per = qrread.ECC[c["level"]]["per"][ver - 1]
    damaged = [set() for _ in lengths]
    for xy in pad:
        if xy in index:
            damaged[where[index[xy]][0]].add(index[xy])
    worst = [len(s) for s in damaged]
    limit = per // 2 - MARGIN
    if max(worst) > limit:
        fails.append(f"{name}: a block has {max(worst)} codewords under the pad; at most {limit} (floor({per} / 2) - {MARGIN})")
    # As drawn (nothing under the pad), and every module under the pad inverted: both correct back to the text.
    drawn = qrread.scan(c["d"], c["view"])
    if any(f"M{x + 4} {y + 4}h" in c["d"] for x, y in pad):
        fails.append(f"{name}: the drawn path has modules under the pad")
    flipped = [row[:] for row in grid]
    for x, y in pad:
        flipped[y][x] ^= 1
    worst_read = qrread.decode(flipped)
    for what, got in (("as drawn", drawn), ("with every module under the pad inverted", worst_read)):
        if not (got["payload"] == text and got["rs_ok_all_blocks"] and got["format_ok_both_copies"]):
            fails.append(f"{name}: {what}, it doesn't correct back to the text (errors per block {got['errors_per_block']})")
    return (f"{name}: {len(text.encode())} B, version {ver}-Q ({size} modules), mark {mark}/{size} = {mark / size:.0%} on a "
            f"{side}-module pad{', over the centre alignment pattern' if covered else ''}; codewords under the pad per block "
            f"{worst} of {per} EC (limit {limit}); inverted, corrected {worst_read['errors_per_block']}"), max(worst)


def main():
    fails = []
    if qrread.rs_rem(HELLO[0], qrread.rs_divisor(13)) != HELLO[1]:
        fails.append("Reed-Solomon: the 1-Q HELLO WORLD codewords differ from the published ones")
    res = subprocess.run(["node", "--input-type=module", "-e", NODE, json.dumps({"inputs": inputs(), "capacity": CAPACITY})],
                         cwd=ROOT, capture_output=True, text=True, timeout=300)
    if res.returncode:
        print(res.stderr[-2000:])
        print("qr-logo: FAIL (node)")
        return 1
    out = json.loads(res.stdout)
    for r in out["levels"]:
        grid = [[int(ch) for ch in row] for row in r["grid"]]
        got = qrread.decode(grid)
        want_next = r["version"] + 1 if r["version"] < 10 else "too long"
        if not (r["got"] == r["version"] and r["gotLevel"] == r["level"] and r["next"] == want_next and got["clean"]
                and got["payload"] == r["text"] and got["ecl"] == r["level"] and got["format_ok_both_copies"]):
            fails.append(f"level {r['level']} version {r['version']}: {r['n']} bytes took version {r['got']}-{r['gotLevel']}, one more "
                         f"took {r['next']}; read back {got['ecl']} {got['payload'] == r['text']} clean {got['clean']}")
    print(f"levels: {len(out['levels'])} codes, L, M, Q and H at versions 1-10, at ISO's capacity and one byte past it")
    symbol = open(os.path.join(ROOT, "web", "shared", "brand", "symbol.svg"), encoding="utf-8").read()
    if re.search(r'<path fill="#ACFF00" transform="translate\(2\.24 1\.81\) scale\(\.86\)" d="([^"]+)"', symbol).group(1) != out["mark"]:
        fails.append("the mark in ui/qr.js is not web/shared/brand/symbol.svg's")
    more = []
    for c in out["codes"]:
        line, worst = check_code(c, fails)
        if c["name"].startswith("/s/ link #"):
            more.append(worst)
        else:
            print(line)
    print(f"and {len(more)} more /s/ links with random ids and keys: at most {max(more)} codewords under the pad in any block")
    for f in fails:
        print("FAIL", f)
    print(f"qr-logo: {'FAIL' if fails else 'PASS'} ({len(out['levels'])} level codes, {len(out['codes'])} codes with or without the mark, "
          f"{len(fails)} problems)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
