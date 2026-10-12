// SPDX-License-Identifier: MIT
// Runs on every site page: the mainnet phase, live numbers and copy variants, the language switch
// (and one line offering the page's translation when the browser prefers the other language), the
// judge-pass chip, and copy buttons. Other page modules import `config`, `getJson`, `lang`, `locale`
// and the tx helpers from here.
import { applyPhase } from '/shared/dates.js';
import { applyConditions, fillVariables } from './stats.js';

export const lang = document.documentElement.lang === 'es' ? 'es' : 'en';
export const locale = lang === 'es' ? 'es-MX' : 'en-US';

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

// The footer's EN · ES links point at this page's own translation.
for (const a of document.querySelectorAll('a[data-lang]')) {
  const alt = document.querySelector(`link[rel="alternate"][hreflang="${a.dataset.lang}"]`);
  if (alt) a.href = new URL(alt.href).pathname;
}

// A browser that prefers the other language, with no choice made here yet, is offered the
// translation once per device.
const OFFER = { en: 'Read this in English', es: 'Leer en español' };
const DISMISS = { en: 'No, thanks', es: 'No, gracias' };
const storage = (key, value) => {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch {
    // Blocked storage: the offer shows again next time, nothing else.
  }
  return null;
};
const other = lang === 'en' ? 'es' : 'en';
const preferred = (navigator.languages || []).map((l) => l.toLowerCase().split('-')[0]).find((l) => l === 'en' || l === 'es');
const translation = document.querySelector(`link[rel="alternate"][hreflang="${other}"]`);
if (translation && preferred === other && !storage('mutis.lang') && !storage('mutis.lang.offer')) {
  const offer = document.createElement('div');
  offer.className = 'lang-offer';
  offer.lang = other;
  const go = document.createElement('a');
  go.href = new URL(translation.href).pathname;
  go.textContent = OFFER[other];
  go.addEventListener('click', () => storage('mutis.lang', JSON.stringify(other)));
  const no = document.createElement('button');
  no.type = 'button';
  no.className = 'a-linkbtn';
  no.textContent = DISMISS[other];
  no.addEventListener('click', () => { storage('mutis.lang.offer', 'no'); offer.remove(); });
  offer.append(go, no);
  document.body.prepend(offer);
}

// The header's chip while a judge pass is saved on this device (judges.js, the app's pow.js).
import('/app/lib/store.js').then(({ savedJudgePass }) => {
  if (savedJudgePass()) for (const chip of document.querySelectorAll('[data-judge-active]')) chip.hidden = false;
}, () => null);

const COPIED = { en: 'Copied.', es: 'Copiado.' };
if (navigator.clipboard) {
  for (const button of document.querySelectorAll('button[data-copy]')) {
    const source = document.getElementById(button.dataset.copy);
    const label = button.textContent;
    button.hidden = false;
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(source.textContent.trim());
        button.textContent = COPIED[lang];
        setTimeout(() => { button.textContent = label; }, 2000);
      } catch {
        getSelection().selectAllChildren(source); // copying was refused: select it for the visitor
      }
    });
  }
}
