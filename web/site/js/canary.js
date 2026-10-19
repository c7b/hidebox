// SPDX-License-Identifier: MIT
// "Try to read it": our hourly test file, exactly as our disk holds it (spec §6.3, §8.4). Without
// JavaScript the section still offers the download and the curl line; this adds the noise, its age,
// the delivery transaction and yesterday's key.
import { getJson, isTxId, locale, shortTx } from './site.js';
import { drawNoise } from './noise.js';

const NOISE_BYTES = 96 * 96;
const DAY_S = 86400;

export async function getBytes(path, range) {
  const res = await fetch(path, { headers: range ? { Range: range } : {}, signal: AbortSignal.timeout(10000), credentials: 'omit' });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return new Uint8Array(await res.arrayBuffer());
}

// One /api/v1/canary for the page: Try to read it shows it, and the status line counts its misses.
let meta = null;
export const canaryMeta = () => (meta ??= getJson('/api/v1/canary').catch(() => null));

export async function loadCanary() {
  try {
    const m = await canaryMeta();
    if (!m) return null;
    return { meta: m, bytes: await getBytes(m.raw, `bytes=0-${NOISE_BYTES - 1}`) };
  } catch {
    return null;
  }
}

// An hour whose key was lost (the verifier restarted and its delivery couldn't give the key back) is listed, never
// skipped; test files missed one after another are one line: "23 test files missed (#150 to #172): …".
export function missedLines(revealed) {
  const ns = (revealed ?? []).filter((entry) => entry.missed).map((entry) => entry.n).sort((a, b) => b - a);
  const runs = [];
  for (const n of ns) {
    const run = runs.at(-1);
    if (run && run.low === n + 1) run.low = n;
    else runs.push({ low: n, high: n });
  }
  return runs.map(({ low, high }) => (low === high ? `Test file #${low} missed: the verifier restarted.`
    : `${high - low + 1} test files missed (#${low} to #${high}): the verifier restarted.`));
}

// Misses whose key was due in the last 24 hours (a test file's key is due a day after it was locked).
export function recentMisses(revealed, now = Date.now() / 1000) {
  return (revealed ?? []).filter((entry) => entry.missed && entry.sealed_at + DAY_S > now - DAY_S).length;
}

function age(sealedAt) {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - sealedAt) / 60));
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  return minutes < 90 ? rtf.format(-minutes, 'minute') : rtf.format(-Math.round(minutes / 60), 'hour');
}

export function showCanary(root, canary) {
  if (!canary) {
    root.querySelector('[data-canary]').hidden = true;
    root.querySelector('[data-canary-missing]').hidden = false;
    return;
  }
  const { meta, bytes } = canary;
  drawNoise(root.querySelector('[data-canary-noise]'), bytes);
  root.querySelector('[data-canary-size]').textContent = new Intl.NumberFormat(locale).format(meta.size_stored);
  root.querySelector('[data-canary-figure]').hidden = false;
  root.querySelector('[data-canary-age]').textContent = age(meta.sealed_at);
  root.querySelector('[data-canary-aged]').hidden = false;
  root.querySelector('[data-canary-lede]').hidden = true;
  if (isTxId(meta.delivery_tx)) {
    root.querySelector('[data-canary-tx-link]').href = `/verify/tx/${meta.delivery_tx}`;
    root.querySelector('[data-canary-tx-short]').textContent = shortTx(meta.delivery_tx);
    root.querySelector('[data-canary-tx]').hidden = false;
  }
  const revealed = meta.revealed ?? [];
  const opens = revealed.find((entry) => entry.fk);
  if (opens) offerReveal(root.querySelector('[data-reveal]'), opens);
  const missed = missedLines(revealed);
  if (missed.length) {
    const line = root.querySelector('[data-reveal-missed]');
    line.replaceChildren(...missed.flatMap((text, i) => (i ? [' ', document.createElement('br'), text] : [text])));
    line.hidden = false;
  }
}

// The decryption code (reveal.js, then /app/lib) loads only when the visitor presses the button.
function offerReveal(box, entry) {
  box.querySelector('[data-reveal-n]').textContent = String(entry.n);
  const button = box.querySelector('[data-reveal-open]');
  button.addEventListener('click', async () => {
    button.disabled = true;
    const { openRevealed } = await import('./reveal.js');
    button.disabled = await openRevealed(box, entry); // stays off once it has opened
  });
  box.hidden = false;
}
