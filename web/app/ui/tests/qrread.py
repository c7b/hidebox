# SPDX-License-Identifier: MIT
"""An independent QR read-back for the UI flows (14-ghost-design §17 step 7): it rebuilds the module
grid from the SVG path the app drew, reads the format bits (both copies), unmasks, walks the zigzag,
de-interleaves the blocks, checks every Reed-Solomon remainder, corrects what a block's EC codewords can
(Berlekamp-Massey, Chien, Forney: what a phone does with the modules under the mark) and parses byte mode.
Written from ISO/IEC 18004 by the design critic, not from the app's encoder; levels Q and H and the correction
were added for the mark (share-simple). Python stdlib only."""
import re

# ISO/IEC 18004 Table 9, versions 1-10: EC codewords per block and the number of blocks.
ECC = {'L': {'per': [7, 10, 15, 20, 26, 18, 20, 24, 30, 18], 'blocks': [1, 1, 1, 1, 1, 2, 2, 2, 2, 4]},
       'M': {'per': [10, 16, 26, 18, 24, 16, 18, 22, 22, 26], 'blocks': [1, 1, 1, 2, 2, 4, 4, 4, 5, 5]},
       'Q': {'per': [13, 22, 18, 26, 18, 24, 18, 22, 20, 24], 'blocks': [1, 1, 2, 2, 4, 4, 6, 6, 8, 8]},
       'H': {'per': [17, 28, 22, 16, 22, 28, 26, 26, 24, 28], 'blocks': [1, 1, 2, 4, 4, 4, 5, 6, 8, 8]}}
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


EXP, LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    EXP[_i], LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100: _x ^= 0x11D
for _i in range(255, 512): EXP[_i] = EXP[_i - 255]


def gf_div(a, b):
    return 0 if a == 0 else EXP[(LOG[a] - LOG[b]) % 255]


def poly_eval(p, x):
    """p[0] is the highest degree."""
    y = 0
    for c in p: y = gf_mul(y, x) ^ c
    return y


def correct(block, per):
    """A block (data then EC codewords) with up to per // 2 wrong codewords put right: (block, errors), or None
    when it is past what its EC codewords correct. The generator's roots are alpha^0 .. alpha^(per-1)."""
    n = len(block)
    synd = [poly_eval(block, EXP[i]) for i in range(per)]
    if not any(synd): return list(block), 0
    lam, prev, size, m, b = [1], [1], 0, 1, 1           # Berlekamp-Massey: the error locator, lowest degree first
    for k in range(per):
        d = synd[k]
        for i in range(1, min(size, len(lam) - 1) + 1): d ^= gf_mul(lam[i], synd[k - i])
        if d == 0:
            m += 1
            continue
        old = lam[:]
        shifted = [0] * m + [gf_mul(gf_div(d, b), c) for c in prev]
        lam = [(lam[i] if i < len(lam) else 0) ^ (shifted[i] if i < len(shifted) else 0) for i in range(max(len(lam), len(shifted)))]
        if 2 * size <= k: size, prev, b, m = k + 1 - size, old, d, 1
        else: m += 1
    lam = lam[:size + 1]
    if 2 * size > per: return None
    where = [j for j in range(n) if poly_eval(lam[::-1], EXP[(255 - j) % 255]) == 0]   # Chien: power j is wrong
    if len(where) != size: return None
    omega = [0] * per                                    # Forney: e = X * Omega(X^-1) / Lambda'(X^-1)
    for i in range(per):
        for j in range(len(lam)):
            if i + j < per: omega[i + j] ^= gf_mul(synd[i], lam[j])
    deriv = [lam[i] if i % 2 else 0 for i in range(1, len(lam))]
    out = list(block)
    for j in where:
        xinv = EXP[(255 - j) % 255]
        den = poly_eval(deriv[::-1], xinv)
        if den == 0: return None
        out[n - 1 - j] ^= gf_mul(EXP[j], gf_div(poly_eval(omega[::-1], xinv), den))
    return (out, size) if not any(poly_eval(out, EXP[i]) for i in range(per)) else None


def placement(ver, size):
    """The data modules in the order the zigzag reads them (two columns at a time from the right, up then down,
    skipping the vertical timing column): codeword k is modules 8k .. 8k+7 of this list."""
    f = function_map(ver, size)
    order = []
    right = size - 1
    while right >= 1:
        if right == 6: right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                up = ((right + 1) & 2) == 0
                y = size - 1 - vert if up else vert
                if not f[y][x]: order.append((x, y))
        right -= 2
    return order


def interleave(ver, ecl, ncw):
    """[(block, index in the block)] for each codeword in the order it is placed, and the block lengths: data
    codewords block by block, the short blocks first, then the EC codewords the same way."""
    per, nb = ECC[ecl]['per'][ver - 1], ECC[ecl]['blocks'][ver - 1]
    nshort = nb - ncw % nb; slen = ncw // nb
    out, k = [], 0
    for i in range(slen + 1):
        for j in range(nb):
            if i == slen - per and j < nshort: continue
            if k < ncw:
                out.append((j, i - (1 if j < nshort and i > slen - per else 0)))
                k += 1
    return out, [slen if j < nshort else slen + 1 for j in range(nb)]


def decode(g):
    size = len(g); ver = (size - 17) // 4
    bits1 = [g[i][8] for i in range(6)] + [g[7][8], g[8][8], g[8][7]] + [g[8][14 - i] for i in range(9, 15)]
    raw1 = sum(b << i for i, b in enumerate(bits1))
    bits2 = [g[8][size - 1 - i] for i in range(8)] + [g[size - 15 + i][8] for i in range(8, 15)]
    raw2 = sum(b << i for i, b in enumerate(bits2))
    best = min(range(32), key=lambda d: bin(bch_format(d) ^ raw1).count('1'))
    fmt_ok = bch_format(best) == raw1 and raw1 == raw2
    ecl, mask = FMT_ECL[best >> 3], best & 7
    bits = [g[y][x] ^ (1 if MASKS[mask](x, y) else 0) for x, y in placement(ver, size)]
    ncw = len(bits) // 8
    cws = [int(''.join(map(str, bits[i * 8:i * 8 + 8])), 2) for i in range(ncw)]
    per = ECC[ecl]['per'][ver - 1]
    where, lengths = interleave(ver, ecl, ncw)
    blocks = [[0] * n for n in lengths]
    for k, (j, i) in enumerate(where): blocks[j][i] = cws[k]
    data, rs_ok, clean, errors = [], True, True, []
    div = rs_divisor(per)
    for blk in blocks:
        if rs_rem(blk[:-per], div) != blk[-per:]:
            clean = False
            fixed = correct(blk, per)
            if fixed is None:
                rs_ok = False
                errors.append(None)
            else:
                blk = fixed[0]
                errors.append(fixed[1])
        else:
            errors.append(0)
        data += blk[:-per]
    bs = ''.join(f'{b:08b}' for b in data)
    mode = int(bs[:4], 2); cc = 8 if ver <= 9 else 16
    n = int(bs[4:4 + cc], 2)
    payload = bytes(int(bs[4 + cc + 8 * i:12 + cc + 8 * i], 2) for i in range(n) if 12 + cc + 8 * i <= len(bs))
    return {'version': ver, 'ecl': ecl, 'mask': mask, 'format_ok_both_copies': fmt_ok, 'rs_ok_all_blocks': rs_ok,
            'clean': clean, 'errors_per_block': errors, 'mode': mode, 'payload': payload.decode('utf-8', 'replace')}


def scan(d, view):
    """What a phone camera would read from the drawn code: {payload, version, ecl, format_ok_both_copies, rs_ok_all_blocks
    (every block checks out, after correcting what it can), clean (nothing to correct), errors_per_block, ...}."""
    return decode(grid_from_path(d, int(view)))
