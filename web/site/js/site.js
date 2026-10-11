// SPDX-License-Identifier: MIT
// Runs on every site page: the mainnet phase, live numbers and copy variants, the language switch,
// and copy buttons. Other page modules import `config`, `getJson`, `lang`, `locale` and the tx helpers from here.
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
