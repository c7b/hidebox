// SPDX-License-Identifier: MIT
// Runs on every site page: the mainnet phase, live numbers and copy variants, the judge-pass chip,
// copy buttons, the header (the page it is on, Make my drive or Open my drive, stepping aside on the
// home) and, on the home, the field behind the hero. Other page modules import `config`, `getJson`,
// `locale` and the tx helpers from here.
import { applyPhase } from '/shared/dates.js';
import { applyConditions, fillVariables } from './stats.js';

export const locale = 'en-US';

export async function getJson(path, timeoutMs = 8000) {
  const res = await fetch(path, { signal: AbortSignal.timeout(timeoutMs), credentials: 'omit' });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

// Our own test transactions are linked by id; anything that isn't 64 hex characters is never used.
export const isTxId = (id) => /^[0-9a-f]{64}$/.test(id ?? '');
export const shortTx = (hex) => `${hex.slice(0, 8)}…${hex.slice(-8)}`;

const settle = (promise) => promise.catch(() => null);
export const config = settle(getJson('/api/v1/config'));
const stats = document.querySelector('[data-needs~="stats"]') ? settle(getJson('/api/v1/stats')) : Promise.resolve(null);

applyPhase();

Promise.all([config, stats]).then(([c, s]) => {
  if (c) applyConditions(document, c);
  fillVariables(document, { config: c, stats: s }, locale);
});

// The header's chip while a judge pass is saved on this device (judges.js, the app's pow.js).
import('/app/lib/store.js').then(({ savedJudgePass }) => {
  if (savedJudgePass()) for (const chip of document.querySelectorAll('[data-judge-active]')) chip.hidden = false;
}, () => null);

const COPIED = 'Copied.';
if (navigator.clipboard) {
  for (const button of document.querySelectorAll('button[data-copy]')) {
    const source = document.getElementById(button.dataset.copy);
    const label = button.textContent;
    button.hidden = false;
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(source.textContent.trim());
        button.textContent = COPIED;
        setTimeout(() => { button.textContent = label; }, 2000);
      } catch {
        getSelection().selectAllChildren(source); // copying was refused: select it for the visitor
      }
    });
  }
}

const root = document.documentElement;
for (const a of document.querySelectorAll('.top-nav a')) if (a.pathname === location.pathname) a.setAttribute('aria-current', 'page');

// Does this browser hold a drive? The drive keeps its key in IndexedDB "mutis", store "identity", record
// "current": we count that record (never read it) and never create the database. theme.js paints from
// the cached flag; this keeps the flag true.
function driveHere() {
  if (!globalThis.indexedDB?.databases) return Promise.resolve(null);
  return indexedDB.databases().then((list) => !list.some((d) => d.name === 'mutis') ? false : new Promise((resolve) => {
    const req = indexedDB.open('mutis');
    req.onupgradeneeded = () => req.transaction.abort();
    req.onerror = req.onblocked = () => resolve(null);
    req.onsuccess = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('identity')) return resolve(false, db.close());
      const n = db.transaction('identity').objectStore('identity').count('current');
      n.onsuccess = () => resolve(n.result > 0, db.close());
      n.onerror = () => resolve(null, db.close());
    };
  }), () => null);
}
driveHere().then((has) => {
  if (has === null) return;
  root.toggleAttribute('data-has-drive', has);
  try {
    if (has) localStorage.setItem('mutis.drive', '1');
    else localStorage.removeItem('mutis.drive');
  } catch {
    // blocked storage: this page still shows the right button
  }
});

// The home: the header's button steps aside while one of the page's own ([data-cta]) is on screen
// below the sticky header.
const head = document.querySelector('[data-head]');
const ctas = document.querySelectorAll('[data-cta]');
if (head && ctas.length) {
  const seen = new Set();
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) e.isIntersecting ? seen.add(e.target) : seen.delete(e.target);
    head.toggleAttribute('data-cta-out', !seen.size);
  }, { rootMargin: '-61px 0px 0px 0px' });
  ctas.forEach((c) => io.observe(c));
}

// The field behind the home's hero (17-site-brief §1). Its quiet zone, an ellipse over the lede, the
// buttons and the note, is measured here, so the static grid keeps grey text readable at every width
// (12 % lines under words) with or without the moving field.
const field = document.querySelector('[data-field]');
export function quietZone() {
  const box = field.getBoundingClientRect();
  const parts = [...field.parentElement.querySelectorAll('[data-quiet]')].map((e) => e.getBoundingClientRect());
  const edge = (side, pick) => pick(...parts.map((r) => r[side])) - box[side === 'right' ? 'left' : side === 'bottom' ? 'top' : side];
  const [left, right, top, bottom] = [edge('left', Math.min), edge('right', Math.max), edge('top', Math.min), edge('bottom', Math.max)];
  // the words' box, corners included, fits inside 75 % of the ellipse, where the lines are fully quiet
  const zone = { x: (left + right) / 2, y: (top + bottom) / 2, rx: (right - left) / 2 * 1.9 + 16, ry: (bottom - top) / 2 * 1.9 + 16 };
  for (const [k, v] of Object.entries(zone)) field.style.setProperty(`--q-${k}`, `${Math.round(v)}px`);
  return zone;
}
if (field) {
  new ResizeObserver(quietZone).observe(field);
  // A-06h: field.js loads after the load event, when the browser is idle, only on the home, only when
  // motion is allowed and a WebGL2 context exists. Otherwise the static grid stays.
  const begin = () => {
    if (!root.classList.contains('motion')) return;
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false, powerPreference: 'low-power' });
    if (gl) import('./field.js').then((m) => m.start(field, canvas, gl), () => null);
  };
  const idle = () => (globalThis.requestIdleCallback ?? ((f) => setTimeout(f, 1)))(begin, { timeout: 2000 });
  if (document.readyState === 'complete') idle();
  else addEventListener('load', idle, { once: true });
}
