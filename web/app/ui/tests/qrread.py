# SPDX-License-Identifier: MIT
"""An independent QR read-back for the UI flows (14-ghost-design §17 step 7): it rebuilds the module
grid from the SVG path the app drew, reads the format bits (both copies), unmasks, walks the zigzag,
de-interleaves the blocks, checks every Reed-Solomon remainder and parses byte mode. Written from
ISO/IEC 18004 by the design critic, not from the app's encoder. Python stdlib only."""
import re

ECC = {'L': {'per': [7, 10, 15, 20, 26, 18, 20, 24, 30, 18], 'blocks': [1, 1, 1, 1, 1, 2, 2, 2, 2, 4]},
       'M': {'per': [10, 16, 26, 18, 24, 16, 18, 22, 22, 26], 'blocks': [1, 1, 1, 2, 2, 4, 4, 4, 5, 5]}}
FMT_ECL = {1: 'L', 0: 'M', 3: 'Q', 2: 'H'}


def grid_from_path(d, view):
    n = view - 8
    g = [[0] * n for _ in range(n)]
    for x, y in re.findall(r"M(\d+) (\d+)h1v1h-1z", d):
        g[int(y) - 4][int(x) - 4] = 1
    return g


def bch_format(data):
    r = data
    for _ in range(10): r = (r << 1) ^ ((r >> 9) * 0x537)
    return ((data << 10) | r) ^ 0x5412


def align_pos(ver, size):
    if ver == 1: return []
    num = ver // 7 + 2
    step = 26 if ver == 32 else (ver * 4 + num * 2 + 1) // (num * 2 - 2) * 2
    res, pos = [], size - 7
    for _ in range(num - 1): res.insert(0, pos); pos -= step
    return [6] + res


def function_map(ver, size):
    f = [[False] * size for _ in range(size)]
    def mark(x, y):
        if 0 <= x < size and 0 <= y < size: f[y][x] = True
    for i in range(size): mark(6, i); mark(i, 6)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5): mark(cx + dx, cy + dy)
    ap = align_pos(ver, size)
    for i, a in enumerate(ap):
        for j, b in enumerate(ap):
            if (i == 0 and j == 0) or (i == 0 and j == len(ap) - 1) or (i == len(ap) - 1 and j == 0): continue
            for dy in range(-2, 3):
                for dx in range(-2, 3): mark(a + dx, b + dy)
    for i in range(9): mark(8, i); mark(i, 8)
    for i in range(8): mark(size - 1 - i, 8)
    for i in range(8): mark(8, size - 1 - i)
    if ver >= 7:
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            mark(a, b); mark(b, a)
    return f


MASKS = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
         lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
         lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]


def gf_mul(a, b):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D); z ^= ((b >> i) & 1) * a
    return z


def rs_divisor(deg):
    res = [0] * (deg - 1) + [1]; root = 1
    for _ in range(deg):
        for j in range(deg):
            res[j] = gf_mul(res[j], root)
            if j + 1 < deg: res[j] ^= res[j + 1]
        root = gf_mul(root, 2)
    return res


def rs_rem(data, div):
    res = [0] * len(div)
    for b in data:
        f = b ^ res.pop(0); res.append(0)
        for i, c in enumerate(div): res[i] ^= gf_mul(c, f)
    return res


def decode(g):
    size = len(g); ver = (size - 17) // 4
    bits1 = [g[i][8] for i in range(6)] + [g[7][8], g[8][8], g[8][7]] + [g[8][14 - i] for i in range(9, 15)]
    raw1 = sum(b << i for i, b in enumerate(bits1))
    bits2 = [g[8][size - 1 - i] for i in range(8)] + [g[size - 15 + i][8] for i in range(8, 15)]
    raw2 = sum(b << i for i, b in enumerate(bits2))
    best = min(range(32), key=lambda d: bin(bch_format(d) ^ raw1).count('1'))
    fmt_ok = bch_format(best) == raw1 and raw1 == raw2
    ecl, mask = FMT_ECL[best >> 3], best & 7
    f = function_map(ver, size)
    bits = []
    right = size - 1
    while right >= 1:
        if right == 6: right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                up = ((right + 1) & 2) == 0
                y = size - 1 - vert if up else vert
                if not f[y][x]:
                    bits.append(g[y][x] ^ (1 if MASKS[mask](x, y) else 0))
        right -= 2
    ncw = len(bits) // 8
    cws = [int(''.join(map(str, bits[i * 8:i * 8 + 8])), 2) for i in range(ncw)]
    per, nb = ECC[ecl]['per'][ver - 1], ECC[ecl]['blocks'][ver - 1]
    nshort = nb - ncw % nb; slen = ncw // nb
    blocks = [[None] * (slen + 1) for _ in range(nb)]
    k = 0
    for i in range(slen + 1):
        for j in range(nb):
            if i == slen - per and j < nshort: continue
            if k < ncw: blocks[j][i] = cws[k]; k += 1
    data, rs_ok = [], True
    div = rs_divisor(per)
    for j, blk in enumerate(blocks):
        blk = [v for idx, v in enumerate(blk) if not (idx == slen - per and j < nshort)]
        d, e = blk[:-per], blk[-per:]
        rs_ok &= rs_rem(d, div) == e
        data += d
    bs = ''.join(f'{b:08b}' for b in data)
    mode = int(bs[:4], 2); cc = 8 if ver <= 9 else 16
    n = int(bs[4:4 + cc], 2)
    payload = bytes(int(bs[4 + cc + 8 * i:12 + cc + 8 * i], 2) for i in range(n))
    return {'version': ver, 'ecl': ecl, 'mask': mask, 'format_ok_both_copies': fmt_ok, 'rs_ok_all_blocks': rs_ok,
            'mode': mode, 'payload': payload.decode('utf-8', 'replace')}



def scan(d, view):
    """What a phone camera would read from the drawn code: {payload, version, ecl, format_ok_both_copies, rs_ok_all_blocks, ...}."""
    return decode(grid_from_path(d, int(view)))
