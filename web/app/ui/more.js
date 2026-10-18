// SPDX-License-Identifier: MIT
// The home page starts the drop widget with only what a first drop needs: a short dictionary
// (i18n/widget-en.json, a subset of the full one) and the widget's stylesheet. The rest of the
// strings and styles (the Change panel, the glass box, errors, the send step, recent drops) load the
// first time one of them is about to show. On app pages both are already there.
import { loadStrings, t, useStrings } from '../lib/i18n.js';

const PARTS = '/app/css/parts.css';
const FULL_ONLY = 'error.internal'; // a string only the full dictionary has
let pending = null;

// Adds a same-origin stylesheet once; resolves when it applies (or failed: the page still works).
export function stylesheet(href) {
  if (document.querySelector(`link[rel="stylesheet"][href="${href}"]`)) return Promise.resolve();
  return new Promise((resolve) => {
    const link = Object.assign(document.createElement('link'), { rel: 'stylesheet', href });
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener('error', resolve, { once: true });
    document.head.append(link);
  });
}

async function fetchJson(path) {
  const res = await fetch(path, { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error(`no strings at ${path}`);
  return res.json();
}

// The widget's first dictionary.
export async function widgetStrings() {
  useStrings(await fetchJson('/app/i18n/widget-en.json'));
}

export function more() {
  pending ??= Promise.all([
    t(FULL_ONLY) === FULL_ONLY ? loadStrings() : null,
    stylesheet(PARTS),
  ]);
  return pending;
}
