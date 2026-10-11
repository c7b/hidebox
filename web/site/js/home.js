// SPDX-License-Identifier: MIT
// The home page around the drop widget. Only what the first screen needs loads with the page; each
// section below the fold brings its own code and requests when it comes near: the exit wall, the
// chain card, "What we store" and "Try to read it". The widget (/app/drop-widget.js) is the app's;
// we only listen to its events.
import { getJson, lang, locale } from './site.js';

const PADDED = 1024; // mutis pads every file to at least 1 KB before encrypting (Padmé)
const AFTER_DROP = {
  en: '(Below: your file, and the same file as our server stores it.)',
  es: '(Abajo: tu archivo, y el mismo archivo como lo guarda nuestro servidor.)',
}[lang];
const YOUR_FILE = { en: '(your file, only in this tab)', es: '(tu archivo, solo en esta pestaña)' }[lang];
const bytesText = (n) => `${new Intl.NumberFormat(locale).format(n)} bytes`;

const once = (fn) => {
  let result;
  return () => (result ??= fn());
};

function whenNear(element, rootMargin, fn) {
  new IntersectionObserver(([entry], observer) => {
    if (!entry.isIntersecting) return;
    observer.disconnect();
    fn();
  }, { rootMargin }).observe(element);
}

const section = (id) => document.getElementById(id);
const glass = section('what-we-store');
const DEMO = glass.querySelector('[data-glass="contents"]').textContent.trim(); // "Only you. Once." in this page's language

// The wall's data is small and must arrive before its lockers come into view, so it is asked for at once.
const wallData = getJson('/api/v1/stats/wall').catch(() => null); // null: the scripted scene stays
const noise = once(() => import('./noise.js'));
const demoCiphertext = once(() => noise().then((m) => m.localCiphertext(DEMO, PADDED)));
const canary = once(() => import('./canary.js').then(async (m) => ({ show: m.showCanary, data: await m.loadCanary() })));
const wall = once(() => Promise.all([import('./wall.js'), import(`./wall-${lang}.js`)])
  .then(([m, words]) => m.initWall(section('exit-wall'), words.default)));

// The wall wakes when its top edge comes into view (it starts exactly at the fold, hence the -1px), so
// its code and data usually arrive while its lockers are still below the fold. Its door is our
// canary's ciphertext, or bytes encrypted right here when our canary can't be reached.
whenNear(section('exit-wall'), '0px 0px -1px 0px', () => wall().then((w) => {
  wallData.then((data) => w.useData(data));
  canary().then(({ data }) => data?.bytes ?? demoCiphertext()).then((bytes) => w.door(bytes));
}));

whenNear(section('send'), '100% 0px', () => import('./evidence.js').then(async ({ loadEvidence, showChainCard }) => {
  const evidence = await loadEvidence();
  if (evidence) showChainCard(document.querySelector('[data-chain-card]'), evidence);
}));

// "What we store": the demo sentence encrypted the way mutis stores a note (padded to 1 KB, AES-GCM).
glass.querySelector('[data-glass="size"]').textContent = bytesText(new TextEncoder().encode(DEMO).length);
whenNear(glass, '100% 0px', () => Promise.all([noise(), demoCiphertext()]).then(([{ drawNoise }, ct]) => {
  if (glass.dataset.yours !== undefined) return;
  drawNoise(glass.querySelector('[data-glass-noise]'), ct);
  glass.querySelector('[data-glass="stored"]').textContent = bytesText(ct.length);
}));

whenNear(section('try'), '100% 0px', () => canary().then(({ show, data }) => show(section('try'), data)));

// The widget's states. While its card shows, the card is the result and the heading stands alone;
// line 2 comes back with the empty zone. 'sealed' may carry {name, size, sizeStored, noise}: the
// visitor's own file, which never leaves this tab.
const line2 = document.querySelector('.hero-line2');
document.addEventListener('mutis:state', ({ detail }) => {
  if (detail?.state === 'idle') line2.hidden = false;
  if (detail?.state !== 'sealed') return;
  line2.hidden = true;
  const { preview } = detail;
  if (!preview?.noise) return;
  glass.dataset.yours = '';
  glass.querySelector('[data-glass-caption]').textContent = AFTER_DROP;
  if (preview.name) glass.querySelector('[data-glass="name"]').textContent = preview.name; // '' for a note: "(a note: no name)" stays
  glass.querySelector('[data-glass="contents"]').textContent = YOUR_FILE;
  glass.querySelector('[data-glass="size"]').textContent = bytesText(preview.size);
  glass.querySelector('[data-glass="stored"]').textContent = bytesText(preview.sizeStored);
  noise().then(({ drawNoise }) => drawNoise(glass.querySelector('[data-glass-noise]'), preview.noise));
  wall().then((w) => w.yours(preview.noise));
});

// "Drop a file" at the end of the page: back to the zone, and open the picker when the widget has one.
for (const link of document.querySelectorAll('[data-pick-file]')) {
  link.addEventListener('click', (event) => {
    const input = document.querySelector('#mutis-drop input[type="file"]');
    if (!input) return;
    event.preventDefault();
    section('drop').scrollIntoView({ block: 'start' });
    input.click();
  });
}
