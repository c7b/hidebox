// SPDX-License-Identifier: MIT
// What the Tari side of the app shows: tTARI amounts, short addresses, the 12-emoji safety code and
// the testnet line (claim C19).
import { h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { phase } from '/shared/dates.js';

// µT (decimal string or bigint) -> "0.5", "0.001": tTARI with up to 3 decimals, never rounded up.
export function formatTari(ut) {
  const v = BigInt(ut);
  const whole = v / 1000000n;
  const milli = (v % 1000000n) / 1000n;
  const frac = milli ? '.' + String(milli).padStart(3, '0').replace(/0+$/, '') : '';
  return whole.toString() + frac;
}

// Tari addresses are shown the way wallets show them, first and last 6 characters, counted after the
// network prefix ("otl_esm_1"), which every testnet address shares.
export function shortAddress(address) {
  const a = String(address);
  const prefix = /^[a-z]+_[a-z]+_1/.exec(a)?.[0].length ?? 0;
  return a.length > prefix + 16 ? `${a.slice(0, prefix + 6)}…${a.slice(-6)}` : a;
}

// The 12-emoji safety code in a 3×4 grid; screen readers get the hex groups instead.
export function safetyGrid(code, props = {}) {
  return h('p', {
    class: ['a-safety', props.class], role: 'img', 'data-testid': props.testid,
    'aria-label': t('safety.aria', { hex: code.hex }),
  }, code.emoji.map((e) => h('span', { 'aria-hidden': 'true' }, e)));
}

// The testnet line every money screen carries (claim C19). It changes on its own when the Ootle
// mainnet starts, like the footer's (/shared/dates.js).
export function testnetLine(cfg) {
  const network = cfg.network.charAt(0).toUpperCase() + cfg.network.slice(1);
  if (phase() === 'mainnet') return h('p', { class: 'a-testnet' }, t('testnet_live', { network }));
  const date = new Intl.DateTimeFormat(document.documentElement.lang, { dateStyle: 'medium', timeZone: 'UTC' })
    .format(new Date(`${cfg.ootle.mainnet_date}T00:00:00Z`));
  return h('p', { class: 'a-testnet' }, t('testnet', { network, mainnet_date: date }));
}
