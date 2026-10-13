// SPDX-License-Identifier: MIT
// Ciphertext drawn as noise (11-brand §13.6): each byte is one grey pixel, so what you see is the
// actual bytes, not a texture. Up to 96 × 96 bytes; smaller inputs get a smaller, chunkier square.

const MAX_SIDE = 96;
const drawn = new Map(); // canvas → bytes, to redraw when the theme changes

function palette(canvas) {
  // Light text means a dark background: use the night range, otherwise the ceiling range.
  const [r, g, b] = getComputedStyle(canvas).color.match(/\d+/g).map(Number);
  const dark = r + g + b > 382;
  return dark ? { lo: 20, hi: 205, empty: 7 } : { lo: 40, hi: 215, empty: 231 };
}

export function drawNoise(canvas, bytes) {
  const n = Math.min(bytes.length, MAX_SIDE * MAX_SIDE);
  const side = Math.max(1, Math.ceil(Math.sqrt(n)));
  canvas.width = side;
  canvas.height = side;
  const { lo, hi, empty } = palette(canvas);
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(side, side);
  const px = image.data;
  for (let i = 0; i < side * side; i++) {
    const v = i < n ? lo + Math.round((bytes[i] * (hi - lo)) / 255) : empty;
    px.set([v, v, v, 255], i * 4);
  }
  ctx.putImageData(image, 0, 0);
  canvas.hidden = false;
  drawn.set(canvas, bytes);
}

function redrawAll() {
  for (const [canvas, bytes] of drawn) drawNoise(canvas, bytes);
}
new MutationObserver(redrawAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawAll);

