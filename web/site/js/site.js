// SPDX-License-Identifier: MIT
// Runs on every site page: the mainnet phase, live numbers and copy variants, the judge-pass chip,
// copy buttons, the header (the page it is on; Open your drive, always on, makes or opens the drive) and,
// after the load event: on the home the field behind the hero and the pixel field behind the closing, and
// on the home, /how and /judges the scroll motion (motion.js), and on /how the stills' loops (stills.js). Other
// page modules import `config`, `getJson`, `locale` and the tx helpers from here.
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
      const done = (answer) => { db.close(); resolve(answer); };
      db.onversionchange = () => done(null);   // the drive wants to upgrade: never stand in its way
      try {
        if (!db.objectStoreNames.contains('identity')) return done(false);
        const n = db.transaction('identity').objectStore('identity').count('current');
        n.onsuccess = () => done(n.result > 0);
        n.onerror = () => done(null);
      } catch {
        done(null);
      }
    };
  })).catch(() => null);
}
const checkDrive = () => driveHere().then((has) => {
  if (has === null) return;
  root.toggleAttribute('data-has-drive', has);
  try {
    if (has) localStorage.setItem('mutis.drive', '1');
    else localStorage.removeItem('mutis.drive');
  } catch {
    // blocked storage: this page still shows the right button
  }
});
checkDrive();
addEventListener('pageshow', (e) => e.persisted && checkDrive());   // back from the drive, from the cache

// The field behind the home's hero (17-site-brief §1). Its quiet zone, an ellipse over the lede, the
// buttons and the note, is measured here, so the static grid keeps grey text readable at every width
// (12 % lines under words) with or without the moving field.
const field = document.querySelector('[data-field]');
export function quietZone() {
  const box = field.getBoundingClientRect();
  const parts = [...field.parentElement.querySelectorAll('[data-quiet]')].map((e) => e.getBoundingClientRect()).filter((r) => r.width);
  const edge = (side, pick) => pick(...parts.map((r) => r[side])) - box[side === 'right' ? 'left' : side === 'bottom' ? 'top' : side];
  const [left, right, top, bottom] = [edge('left', Math.min), edge('right', Math.max), edge('top', Math.min), edge('bottom', Math.max)];
  // the words' box, corners included, fits inside 75 % of the ellipse, where the lines are fully quiet
  const zone = { x: (left + right) / 2, y: (top + bottom) / 2, rx: (right - left) / 2 * 1.9 + 16, ry: (bottom - top) / 2 * 1.9 + 16 };
  for (const [k, v] of Object.entries(zone)) field.style.setProperty(`--q-${k}`, `${Math.round(v)}px`);
  return zone;
}
// A-06h: the effects load after the load event, when the browser is idle, only where a page asks for them,
// only when motion is allowed (html.motion) and, for the two fields, without Data Saver and only when a WebGL2 context exists.
// Otherwise every word is already on screen and the static grid and pixels stay.
const motion = root.classList.contains('motion');
const saveData = Boolean(navigator.connection?.saveData);   // Data Saver: the static grid and pixels only
const afterLoad = (f, timeout) => {
  const idle = () => (globalThis.requestIdleCallback ?? ((g) => setTimeout(g, 1)))(f, { timeout });
  if (document.readyState === 'complete') idle();
  else addEventListener('load', idle, { once: true });
};
const webgl = (box, load) => {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false, powerPreference: 'low-power' });
  if (gl) load().then((m) => m.start(box, canvas, gl)).catch(() => {
    box.classList.remove('live');   // the static pattern comes back
    canvas.remove();
  });
};
if (field) {
  new ResizeObserver(quietZone).observe(field);
  field.parentElement.addEventListener('animationend', quietZone);   // the hero's words have settled
  if (motion && !saveData) afterLoad(() => webgl(field, () => import('./field.js')), 2000);
}
// Site v3: the scroll motion and the hero picture's decode. Until motion.js takes over (html.mo), the
// picture's words wait unseen for at most 3 s (home.css); if it can't load they show at once.
if (motion && document.body.hasAttribute('data-motion')) {
  afterLoad(() => import('./motion.js').then((m) => m.start(), () => root.classList.add('mo')), 300);
}
// /how's stills replay what they show (stills.js), with its Pause motion switch.
if (motion && document.querySelector('.still-frame[data-loop]')) {
  afterLoad(() => import('./stills.js').then((m) => m.start(), () => null), 2000);
}
// The pixel field behind the home's closing (pixel.js), asked for when that section comes near.
const pixels = document.querySelector('[data-pixel]');
if (pixels && motion && !saveData) {
  afterLoad(() => new IntersectionObserver((seen, io) => {
    if (!seen.some((e) => e.isIntersecting)) return;
    io.disconnect();
    webgl(pixels, () => import('./pixel.js'));
  }, { rootMargin: '50% 0px' }).observe(pixels), 2000);
}
