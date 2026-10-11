// SPDX-License-Identifier: MIT
// Strings for the app (§12.7): t(key, params) with {name} interpolation and Intl plurals. Dictionaries
// are flat JSON ({"viewer.ready.title": "…"}); a plural value is an object keyed by Intl plural
// categories and chosen by params.count. English is the source; missing keys fall back to it.
import { localGet, localSet } from './store.js';

export const LANGUAGES = ['en', 'es'];
const STORAGE_KEY = 'mutis.lang';

let lang = 'en';
let dict = {};
let english = {};

export function pickLanguage(available = LANGUAGES) {
  const stored = localGet(STORAGE_KEY);
  if (available.includes(stored)) return stored;
  for (const l of globalThis.navigator?.languages ?? []) {
    const base = l.toLowerCase().split('-')[0];
    if (available.includes(base)) return base;
  }
  return 'en';
}

async function fetchDict(l) {
  const res = await fetch(new URL(`../i18n/${l}.json`, import.meta.url), { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error(`no strings for ${l}`);
  return res.json();
}

export async function loadLanguage(l = pickLanguage(), { remember = false } = {}) {
  english = await fetchDict('en');
  dict = l === 'en' ? english : await fetchDict(l).catch(() => english);
  lang = dict === english ? 'en' : l;
  if (remember) localSet(STORAGE_KEY, lang);
  if (globalThis.document) document.documentElement.lang = lang;
  return lang;
}

// Installs dictionaries without fetching them (tests).
export function useStrings(l, strings, fallback = strings) {
  lang = l;
  dict = strings;
  english = fallback;
}

export function currentLanguage() {
  return lang;
}

const numberFormat = (n) => new Intl.NumberFormat(lang).format(n);

export function t(key, params = {}) {
  let v = dict[key] ?? english[key];
  if (v === undefined) return key;
  if (typeof v === 'object') {
    const cat = new Intl.PluralRules(lang).select(Number(params.count ?? 0));
    v = v[cat] ?? v.other;
  }
  return String(v).replace(/\{(\w+)\}/g, (m, name) => {
    const p = params[name];
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
  return `${new Intl.NumberFormat(lang, { maximumFractionDigits: v < 10 && i > 0 ? 1 : 0 }).format(v)} ${UNITS[i]}`;
}

export function formatDate(ms, options = { dateStyle: 'medium', timeStyle: 'short' }) {
  return new Intl.DateTimeFormat(lang, options).format(new Date(ms));
}

const STEPS = [['year', 31536000], ['month', 2592000], ['day', 86400], ['hour', 3600], ['minute', 60], ['second', 1]];

// "in 3 hours", "5 minutes ago"
export function formatRelative(ms, now = Date.now()) {
  const s = Math.round((ms - now) / 1000);
  const [unit, size] = STEPS.find(([, size]) => Math.abs(s) >= size) ?? STEPS[STEPS.length - 1];
  return new Intl.RelativeTimeFormat(lang, { numeric: 'auto' }).format(Math.round(s / size), unit);
}
