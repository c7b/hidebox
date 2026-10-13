// SPDX-License-Identifier: MIT
// Ciphertext drawn as noise (11-brand §13.6): each byte of the file's real stored ciphertext is one
// grey pixel, in a softened range so it reads as static, not as a code. Beside it, the visitor's own
// file, drawn locally: a raster image through createImageBitmap (no blob: URL), a note's text, or the
// file's extension. Neither leaves the tab.
import { h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';

const SIDE = 96;
const RASTER = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif']);
const LIGHT = [[40, 40, 40], [215, 215, 215]];
const DARK = [[7, 6, 5], [238, 233, 222]]; // near black … near white (the noise strip has its own fixed ramp)
const drawn = new Map(); // canvas -> bytes, redrawn when the theme changes

function dark() {
  const theme = document.documentElement.dataset.theme;
  return theme ? theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
}

function paint(canvas, bytes) {
  const [lo, hi] = dark() ? DARK : LIGHT;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(SIDE, SIDE);
  for (let i = 0; i < SIDE * SIDE; i++) {
    const v = bytes[i % bytes.length] / 255;
    for (let c = 0; c < 3; c++) img.data[i * 4 + c] = Math.round(lo[c] + (hi[c] - lo[c]) * v);
    img.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}

let watching = false;
function watchTheme() {
  if (watching) return;
  watching = true;
  const repaint = () => {
    for (const [canvas, bytes] of drawn) {
      if (canvas.isConnected) paint(canvas, bytes);
      else drawn.delete(canvas);
    }
  };
  new MutationObserver(repaint).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', repaint);
}

// A <figure> with the noise canvas and its text alternative.
export function noiseFigure(bytes) {
  const canvas = h('canvas', { class: 'md-noise', width: SIDE, height: SIDE, 'aria-hidden': 'true', 'data-testid': 'noise-canvas' });
  if (bytes?.length) {
    paint(canvas, bytes);
    drawn.set(canvas, bytes);
    watchTheme();
  }
  return h('figure', { class: 'md-tile' }, canvas, h('figcaption', { class: 'sr-only' }, t('noise.alt')));
}

// The visitor's own file, as only this tab has it: its pixels for raster images, the opening of a
// note, otherwise its extension. The card's heading already names the file and its size.
export function ownFigure(source, meta) {
  const dot = meta.name.lastIndexOf('.');
  const card = source.text !== undefined
    ? h('p', { class: 'md-own md-own-text', 'aria-hidden': 'true' }, source.text.slice(0, 400))
    : h('p', { class: 'md-own md-own-ext', 'aria-hidden': 'true' }, dot > 0 ? meta.name.slice(dot) : meta.name);
  const fig = h('figure', { class: 'md-tile' }, card);
  if (source.file && RASTER.has(source.type)) {
    createImageBitmap(source.file).then((bitmap) => {
      const canvas = h('canvas', { class: 'md-own-img', width: 384, height: 384, role: 'img', 'aria-label': meta.name });
      const scale = Math.max(384 / bitmap.width, 384 / bitmap.height);
      const w = bitmap.width * scale;
      const hgt = bitmap.height * scale;
      canvas.getContext('2d').drawImage(bitmap, (384 - w) / 2, (384 - hgt) / 2, w, hgt);
      bitmap.close();
      card.replaceWith(canvas);
    }, () => null); // undecodable: the extension stays
  }
  return fig;
}
