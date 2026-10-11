// SPDX-License-Identifier: MIT
// "Try to read it": our hourly test file, exactly as our disk holds it (spec §6.3, §8.4). Without
// JavaScript the section still offers the download and the curl line; this adds the noise, its age,
// the delivery transaction and yesterday's key.
import { getJson, isTxId, locale, shortTx } from './site.js';
import { drawNoise } from './noise.js';

const NOISE_BYTES = 96 * 96;

export async function getBytes(path, range) {
  const res = await fetch(path, { headers: range ? { Range: range } : {}, signal: AbortSignal.timeout(10000), credentials: 'omit' });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return new Uint8Array(await res.arrayBuffer());
}

export async function loadCanary() {
  try {
    const meta = await getJson('/api/v1/canary');
    const bytes = await getBytes(meta.raw, `bytes=0-${NOISE_BYTES - 1}`);
    return { meta, bytes };
  } catch {
    return null;
  }
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
  const revealed = meta.revealed?.find((entry) => entry.fk);
  if (revealed) offerReveal(root.querySelector('[data-reveal]'), revealed);
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
