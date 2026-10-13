// SPDX-License-Identifier: MIT
// QR codes (ISO/IEC 18004) with our own encoder: byte mode, level M (L past version 10), versions 1-10,
// the best of eight masks. Loaded with import() on fine pointers only, after there is something to scan.
import { h, svg } from '../lib/dom.js';

const EC = {
  1: [[7, [1, 19]], [10, [1, 16]]], 2: [[10, [1, 34]], [16, [1, 28]]], 3: [[15, [1, 55]], [26, [1, 44]]],
  4: [[20, [1, 80]], [18, [2, 32]]], 5: [[26, [1, 108]], [24, [2, 43]]], 6: [[18, [2, 68]], [16, [4, 27]]],
  7: [[20, [2, 78]], [18, [4, 31]]], 8: [[24, [2, 97]], [22, [2, 38], [2, 39]]],
  9: [[30, [2, 116]], [22, [3, 36], [2, 37]]], 10: [[18, [2, 68], [2, 69]], [26, [4, 43], [1, 44]]],
};
const ALIGN = { 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50] };
const MASKS = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0];

const mul = (x, y) => {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
};

function rsRemainder(data, n) {
  const div = new Array(n).fill(0);
  div[n - 1] = 1;
  for (let i = 0, root = 1; i < n; i++, root = mul(root, 2)) {
    for (let j = 0; j < n; j++) div[j] = mul(div[j], root) ^ (j + 1 < n ? div[j + 1] : 0);
  }
  const r = new Array(n).fill(0);
  for (const b of data) {
    const f = b ^ r.shift();
    r.push(0);
    div.forEach((c, i) => { r[i] ^= mul(c, f); });
  }
  return r;
}

function bch(value, bits, poly, total) {
  let r = value;
  for (let i = 0; i < bits; i++) r = (r << 1) ^ ((r >>> (bits - 1)) * poly);
  return (value << bits) | (r & ((1 << bits) - 1)) & ((1 << total) - 1);
}

function penalty(m, n) {
  let s = 0;
  let dark = 0;
  const line = (get) => {
    for (let a = 0; a < n; a++) {
      let run = 1;
      let row = '';
      for (let b = 0; b < n; b++) {
        row += get(a, b) ? '1' : '0';
        if (b && get(a, b) === get(a, b - 1)) {
          run++;
          s += run === 5 ? 3 : run > 5 ? 1 : 0;
        } else run = 1;
      }
      for (const pat of ['10111010000', '00001011101']) for (let k = row.indexOf(pat); k !== -1; k = row.indexOf(pat, k + 1)) s += 40;
    }
  };
  line((y, x) => m[y][x]);
  line((x, y) => m[y][x]);
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      if (m[y][x]) dark++;
      if (y < n - 1 && x < n - 1 && m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) s += 3;
    }
  }
  return s + Math.floor(Math.abs(dark * 20 - n * n * 10) / (n * n)) * 10;
}

// text -> {size, version, level, mask, dark(x, y)}
export function qr(text) {
  const bytes = [...new TextEncoder().encode(text)];
  let ver = 0;
  let ecl = 0; // format bits: 0 = M, 1 = L
  let spec = null;
  for (const [l, li] of [[0, 1], [1, 0]]) {
    for (let v = 1; v <= 10 && !ver; v++) {
      const s = EC[v][li];
      if (4 + (v < 10 ? 8 : 16) + 8 * bytes.length <= s.slice(1).reduce((a, [k, d]) => a + k * d, 0) * 8) [ver, ecl, spec] = [v, l, s];
    }
    if (ver) break;
  }
  if (!ver) throw new RangeError('too long for a version 10 code');
  const size = ver * 4 + 17;
  const cap = spec.slice(1).reduce((a, [k, d]) => a + k * d, 0);
  const bits = [];
  const put = (v, n) => { for (let i = n - 1; i >= 0; i--) bits.push((v >>> i) & 1); };
  put(4, 4);
  put(bytes.length, ver < 10 ? 8 : 16);
  bytes.forEach((b) => put(b, 8));
  put(0, Math.min(4, cap * 8 - bits.length));
  while (bits.length % 8) bits.push(0);
  const data = [];
  for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  for (let p = 0xec; data.length < cap; p ^= 0xec ^ 0x11) data.push(p);
  const blocks = [];
  let k = 0;
  for (const [n, d] of spec.slice(1)) for (let i = 0; i < n; i++) { const b = data.slice(k, k += d); blocks.push([b, rsRemainder(b, spec[0])]); }
  const words = [];
  for (let i = 0; i < Math.max(...blocks.map(([b]) => b.length)); i++) for (const [b] of blocks) if (i < b.length) words.push(b[i]);
  for (let i = 0; i < spec[0]; i++) for (const [, e] of blocks) words.push(e[i]);

  const mod = Array.from({ length: size }, () => new Array(size).fill(false));
  const fn = Array.from({ length: size }, () => new Array(size).fill(false));
  const set = (x, y, d) => { mod[y][x] = d; fn[y][x] = true; };
  for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
  for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx;
        const y = cy + dy;
        const dist = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, dist !== 2 && dist !== 4);
      }
    }
  }
  const al = ALIGN[ver] ?? [];
  const last = al.length - 1;
  al.forEach((ax, i) => al.forEach((ay, j) => {
    if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
  }));
  const drawFormat = (mask) => {
    const f = bch((ecl << 3) | mask, 10, 0x537, 15) ^ 0x5412;
    const bit = (i) => ((f >>> i) & 1) === 1;
    for (let i = 0; i <= 5; i++) set(8, i, bit(i));
    set(8, 7, bit(6));
    set(8, 8, bit(7));
    set(7, 8, bit(8));
    for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(i));
    set(8, size - 8, true);
  };
  drawFormat(0);
  if (ver >= 7) {
    const vb = bch(ver, 12, 0x1f25, 18);
    for (let i = 0; i < 18; i++) {
      const d = ((vb >>> i) & 1) === 1;
      set(size - 11 + (i % 3), Math.floor(i / 3), d);
      set(Math.floor(i / 3), size - 11 + (i % 3), d);
    }
  }
  let i = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const y = ((right + 1) & 2) === 0 ? size - 1 - vert : vert;
        if (!fn[y][x] && i < words.length * 8) { mod[y][x] = ((words[i >>> 3] >>> (7 - (i & 7))) & 1) === 1; i++; }
      }
    }
  }
  const flip = (m) => { for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fn[y][x] && MASKS[m](x, y)) mod[y][x] = !mod[y][x]; };
  let best = 0;
  let bestScore = Infinity;
  for (let m = 0; m < 8; m++) {
    flip(m);
    drawFormat(m);
    const s = penalty(mod, size);
    if (s < bestScore) [best, bestScore] = [m, s];
    flip(m);
  }
  flip(best);
  drawFormat(best);
  return { size, version: ver, level: ecl ? 'L' : 'M', mask: best, dark: (x, y) => mod[y][x] };
}

// One SVG path, one unit per module, with the four-module quiet zone.
export function qrPath(code) {
  let d = '';
  for (let y = 0; y < code.size; y++) for (let x = 0; x < code.size; x++) if (code.dark(x, y)) d += `M${x + 4} ${y + 4}h1v1h-1z`;
  return { d, view: code.size + 8 };
}

// A <figure> with the code (ink on white, in both themes) and its caption.
export function qrFigure(text, { label, caption, testid = null }) {
  const { d, view } = qrPath(qr(text));
  return h('figure', { class: 'md-qr', 'data-testid': testid },
    svg('svg', { viewBox: `0 0 ${view} ${view}`, role: 'img', 'aria-label': label }, svg('path', { d })),
    h('figcaption', {}, caption));
}
