// SPDX-License-Identifier: MIT
// Strings for the app (§12.7): t(key, params) with {name} interpolation and Intl plurals. The
// dictionary is flat JSON ({"viewer.ready.title": "…"}); a plural value is an object keyed by Intl
// plural categories and chosen by params.count. The app is in English and formats for en-US.
const LOCALE = 'en-US';
// The public name (tools/build.py BRAND, which the build checks against this line). {brand} in any
// string is this, unless the caller passes its own.
export const BRAND = 'hidebox';
const plurals = new Intl.PluralRules(LOCALE);
const numberFormat = (n) => new Intl.NumberFormat(LOCALE).format(n);

let dict = {};

export async function loadStrings() {
  const res = await fetch(new URL('../i18n/en.json', import.meta.url), { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error('no strings');
  dict = await res.json();
}

// Installs a dictionary fetched elsewhere: the home widget's first, smaller one
// (i18n/widget-en.json, ui/more.js), and the tests'.
export function useStrings(strings) {
  dict = strings;
}

export function t(key, params = {}) {
  let v = dict[key];
  if (v === undefined) return key;
  if (typeof v === 'object') v = v[plurals.select(Number(params.count ?? 0))] ?? v.other;
  return String(v).replace(/\{(\w+)\}/g, (m, name) => {
    const p = name === 'brand' ? params.brand ?? BRAND : params[name];
    if (p === undefined) return m;
    return typeof p === 'number' ? numberFormat(p) : String(p);
  });
}

const UNITS = ['B', 'KB', 'MB', 'GB'];

// Binary sizes the way the copy deck writes them: "2.4 MB", "512 B".
export function formatBytes(n) {
  let i = 0;
  let v = n;
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024;
    i++;
  }
  return `${new Intl.NumberFormat(LOCALE, { maximumFractionDigits: v < 10 && i > 0 ? 1 : 0 }).format(v)} ${UNITS[i]}`;
}

export function formatDate(ms, options = { dateStyle: 'medium', timeStyle: 'short' }) {
  return new Intl.DateTimeFormat(LOCALE, options).format(new Date(ms));
}

const STEPS = [['year', 31536000], ['month', 2592000], ['day', 86400], ['hour', 3600], ['minute', 60], ['second', 1]];

// "in 3 hours", "5 minutes ago"
export function formatRelative(ms, now = Date.now()) {
  const s = Math.round((ms - now) / 1000);
  const [unit, size] = STEPS.find(([, size]) => Math.abs(s) >= size) ?? STEPS[STEPS.length - 1];
  return new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' }).format(Math.round(s / size), unit);
}
