// SPDX-License-Identifier: MIT
// QR codes (ISO/IEC 18004) with our own encoder: byte mode, versions 1-10, the best of eight masks. A code carries the
// mark (the open box of web/shared/brand/symbol.svg) in its centre at level Q, where the codewords the mark covers stay
// well inside what Reed-Solomon corrects in every block (logoSpot); a text too long for that, or a code too small for
// the mark, is level M (L past version 10) without it. Loaded with import() on fine pointers only, after there is
// something to scan.
import { h, svg } from '../lib/dom.js';

// ISO/IEC 18004 Table 9, versions 1-10, levels L, M, Q, H: [EC codewords per block, [blocks, data codewords each], ...].
const EC = {
  1: [[7, [1, 19]], [10, [1, 16]], [13, [1, 13]], [17, [1, 9]]],
  2: [[10, [1, 34]], [16, [1, 28]], [22, [1, 22]], [28, [1, 16]]],
  3: [[15, [1, 55]], [26, [1, 44]], [18, [2, 17]], [22, [2, 13]]],
  4: [[20, [1, 80]], [18, [2, 32]], [26, [2, 24]], [16, [4, 9]]],
  5: [[26, [1, 108]], [24, [2, 43]], [18, [2, 15], [2, 16]], [22, [2, 11], [2, 12]]],
  6: [[18, [2, 68]], [16, [4, 27]], [24, [4, 19]], [28, [4, 15]]],
  7: [[20, [2, 78]], [18, [4, 31]], [18, [2, 14], [4, 15]], [26, [4, 13], [1, 14]]],
  8: [[24, [2, 97]], [22, [2, 38], [2, 39]], [22, [4, 18], [2, 19]], [26, [4, 14], [2, 15]]],
  9: [[30, [2, 116]], [22, [3, 36], [2, 37]], [20, [4, 16], [4, 17]], [24, [4, 12], [4, 13]]],
  10: [[18, [2, 68], [2, 69]], [26, [4, 43], [1, 44]], [24, [6, 19], [2, 20]], [28, [6, 15], [2, 16]]],
};
// A level's column in EC and its two format bits.
const LEVEL = { L: [0, 1], M: [1, 0], Q: [2, 3], H: [3, 2] };
const dataWords = (spec) => spec.slice(1).reduce((a, [n, d]) => a + n * d, 0);
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

// text -> {size, version, level, mask, ec, dark(x, y), fixed(x, y), word(x, y), blockOf}: `level` 'L', 'M', 'Q' or 'H'
// (by default M, then L). word(x, y) is the codeword a module carries (-1 for a function pattern or a remainder bit),
// blockOf[word] its Reed-Solomon block, ec the EC codewords of each block.
export function qr(text, { level = null } = {}) {
  const bytes = [...new TextEncoder().encode(text)];
  let ver = 0;
  let lv = null;
  let spec = null;
  for (const l of level ? [level] : ['M', 'L']) {
    for (let v = 1; v <= 10 && !ver; v++) {
      const s = EC[v][LEVEL[l][0]];
      if (4 + (v < 10 ? 8 : 16) + 8 * bytes.length <= dataWords(s) * 8) [ver, lv, spec] = [v, l, s];
    }
    if (ver) break;
  }
  if (!ver) throw new RangeError(`too long for a version 10 code${level ? ` at level ${level}` : ''}`);
  const ecl = LEVEL[lv][1];
  const size = ver * 4 + 17;
  const cap = dataWords(spec);
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
  const blockOf = [];
  for (let i = 0; i < Math.max(...blocks.map(([b]) => b.length)); i++) {
    blocks.forEach(([b], j) => { if (i < b.length) { words.push(b[i]); blockOf.push(j); } });
  }
  for (let i = 0; i < spec[0]; i++) blocks.forEach(([, e], j) => { words.push(e[i]); blockOf.push(j); });

  const mod = Array.from({ length: size }, () => new Array(size).fill(false));
  const fn = Array.from({ length: size }, () => new Array(size).fill(false));
  const word = Array.from({ length: size }, () => new Array(size).fill(-1));
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
        if (!fn[y][x] && i < words.length * 8) {
          mod[y][x] = ((words[i >>> 3] >>> (7 - (i & 7))) & 1) === 1;
          word[y][x] = i >>> 3;
          i++;
        }
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
  return {
    size, version: ver, level: lv, mask: best, ec: spec[0], blockOf,
    dark: (x, y) => mod[y][x], fixed: (x, y) => fn[y][x], word: (x, y) => word[y][x],
  };
}

// Where the mark goes: a pad of whole modules in the centre, the mark one module inside it at 15 to 20 % of the
// code's width. The pad covers no finder, separator, timing, format or version module; from version 7 on it covers
// the centre alignment pattern (it holds no data; readers find the bottom-right one). Every block keeps the codewords
// under the pad at least two below what it corrects (floor(ec / 2) errors), or there is no mark. -> {at, side} | null
export function logoSpot(code) {
  const { size, version } = code;
  let mark = Math.ceil(size * 0.15);
  if (mark % 2 === 0) mark++;
  if (mark > size * 0.2) return null;
  const side = mark + 2;
  const at = (size - side) / 2;
  const c = (size - 1) / 2;
  const hit = new Map();
  for (let y = at; y < at + side; y++) {
    for (let x = at; x < at + side; x++) {
      const w = code.word(x, y);
      if (code.fixed(x, y)) {
        if (version < 7 || Math.abs(x - c) > 2 || Math.abs(y - c) > 2) return null;
      } else if (w >= 0) {
        const b = code.blockOf[w];
        if (!hit.has(b)) hit.set(b, new Set());
        hit.get(b).add(w);
      }
    }
  }
  const limit = Math.floor(code.ec / 2) - 2;
  return [...hit.values()].every((s) => s.size <= limit) ? { at, side } : null;
}

// The code a page draws for `text`: level Q with the mark when it fits there, else level M (L) without it.
export function qrCode(text, { logo = true } = {}) {
  if (logo) {
    try {
      const code = qr(text, { level: 'Q' });
      const spot = logoSpot(code);
      if (spot) return { code, spot };
    } catch {
      // too long for level Q at version 10: no mark
    }
  }
  return { code: qr(text), spot: null };
}

// One SVG path, one unit per module, with the four-module quiet zone; nothing under the mark's pad.
export function qrPath(code, spot = null) {
  const under = (x, y) => spot && x >= spot.at && x < spot.at + spot.side && y >= spot.at && y < spot.at + spot.side;
  let d = '';
  for (let y = 0; y < code.size; y++) for (let x = 0; x < code.size; x++) if (code.dark(x, y) && !under(x, y)) d += `M${x + 4} ${y + 4}h1v1h-1z`;
  return { d, view: code.size + 8 };
}

// The mark as web/shared/brand/symbol.svg draws it (the ink tile, the open box in the kit's lime), on a white pad.
export const MARK = 'm4.38 7.98-.1.06-.05.04-.08.08-.04.04-.08.09-.06.1-.06.1-.04.11-.02.05-.03.12-.01.05v.06l-.01.12.01.12.01.11.01.06.04.11.04.11.03.05.06.1.07.1.04.04.08.08.09.08.05.03.09.06 11.01 6 .1.06.12.04.11.03.12.01.06.01h.12l.06-.01.12-.01.11-.03.06-.02.11-.05.05-.03 11.05-6.03.05-.03.1-.07.08-.08.04-.04.08-.09.06-.1.06-.1.02-.05.04-.11.03-.12.01-.11.01-.06v-.12l-.01-.06-.01-.11-.02-.06-.03-.11-.04-.11-.03-.05-.06-.1-.03-.05-.08-.09-.04-.04-.08-.08-.05-.04-.1-.06-11.05-6.03-.05-.03-.11-.05-.11-.03-.12-.03-.12-.01h-.12l-.06.01-.12.01-.11.03-.06.02-.11.05-.05.03zm11.62 5.65-8.49-4.63 8.49-4.63 8.49 4.63zm-12.18 1.12-.41.2-.1.07-.09.07-.04.03-.08.09-.07.09-.03.05-.04.04-.05.11-.04.1-.02.06-.03.11-.01.11-.01.06v7.12l.01.06.01.12.02.06.03.11.05.11.02.05.07.1.03.05.08.09.08.09.1.07.1.07 11.99 7 .11.05.1.04.11.04.12.02h.05l.12.01.11-.01.12-.01.11-.03.11-.04.05-.02.11-.05 12-7 .09-.07.1-.07.08-.09.08-.09.06-.1.06-.1.03-.06.04-.11.03-.11.01-.06.01-.12v-.06-7l-.01-.12v-.05l-.03-.12-.03-.11-.04-.1-.05-.11-.07-.09-.07-.09-.08-.09-.09-.07-.04-.03-.05-.04-.1-.05-1.51-.76-.07-.03-.08-.02h-.09-.08l-.08.02-.09.03-.07.04-.06.05-.06.06-.03.05-.03.05-.77 1.55-.03.05-.05.06-.04.04-.07.05-9.33 5.44-9.31-5.43-.05-.03-.04-.03-.05-.06-.04-.04-.02-.05-.8-1.58-.04-.07-.05-.05-.06-.05-.07-.04-.05-.03-.06-.02-.05-.01h-.06-.05-.07l-.05.01-.05.02-.06.02-1.15.58-.01.03zm13.38 8.94 9.6-5.6v4.22l-9.6 5.6zm-12-5.6 9.6 5.6v4.22l-9.6-5.6z';

function markOf({ at, side }) {
  const o = at + 4;
  return svg('g', { class: 'md-qr-mark', 'data-testid': 'qr-mark' },
    svg('rect', { x: o, y: o, width: side, height: side, fill: '#FFFFFF' }),
    svg('g', { transform: `translate(${o + 1} ${o + 1}) scale(${(side - 2) / 32})` },
      svg('rect', { width: 32, height: 32, rx: 7, fill: '#0A0A0A' }),
      svg('path', { fill: '#ACFF00', transform: 'translate(2.24 1.81) scale(.86)', d: MARK })));
}

// A <figure> with the code (ink on white, in both themes; the mark in its centre when it fits) and its caption.
export function qrFigure(text, { label, caption, testid = null, logo = true }) {
  const { code, spot } = qrCode(text, { logo });
  const { d, view } = qrPath(code, spot);
  return h('figure', { class: 'md-qr', 'data-testid': testid, 'data-level': code.level },
    svg('svg', { viewBox: `0 0 ${view} ${view}`, role: 'img', 'aria-label': label }, svg('path', { d }), spot ? markOf(spot) : null),
    h('figcaption', {}, caption));
}
