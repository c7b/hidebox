// SPDX-License-Identifier: MIT
// DOM helpers. Elements are built with createElement and text nodes only: there is no way through
// here to parse a string as HTML, set an inline handler or style string, or navigate to script.
// Nothing runs at import time, so protocol modules (and the PoW Worker) may import scriptUrl().

let policy = null;

// The only script-URL sink policy (Trusted Types, Chromium): same-origin scripts under /app/.
export function scriptUrl(url) {
  const tt = globalThis.trustedTypes;
  if (!tt) return url;
  policy ??= tt.createPolicy('mutis-url', {
    createScriptURL: (u) => {
      const x = new URL(u, globalThis.location.origin);
      if (x.origin !== globalThis.location.origin || !x.pathname.startsWith('/app/')) throw new TypeError('blocked');
      return x.href;
    },
  });
  return policy.createScriptURL(url);
}

const BLOCKED = new Set(['innerhtml', 'outerhtml', 'srcdoc', 'style']);
const URL_ATTRS = new Set(['href', 'src', 'action', 'formaction', 'xlink:href']);
const UNSAFE_URL = /^\s*(javascript|vbscript|data):/i;

function apply(el, props) {
  for (const [key, value] of Object.entries(props)) {
    const k = key.toLowerCase();
    if (value === null || value === undefined || value === false) continue;
    if (k.startsWith('on')) {
      if (typeof value !== 'function') throw new TypeError(`${key} must be a function`);
      el.addEventListener(k.slice(2), value);
    } else if (BLOCKED.has(k)) {
      throw new TypeError(`${key} is not allowed`);
    } else if (k === 'class') {
      el.setAttribute('class', Array.isArray(value) ? value.filter(Boolean).join(' ') : value);
    } else if (k === 'text') {
      el.textContent = String(value);
    } else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'hidden') {
      el[k] = value;
    } else {
      if (URL_ATTRS.has(k) && UNSAFE_URL.test(String(value))) throw new TypeError(`unsafe ${key}`);
      el.setAttribute(key, value === true ? '' : String(value));
    }
  }
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

// h('button', {class: 'a-btn', 'data-testid': 'copy-link', onclick}, 'Copy link')
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  apply(el, props);
  append(el, children);
  return el;
}

export function svg(tag, props = {}, ...children) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  apply(el, props);
  append(el, children);
  return el;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

// Dynamic values reach CSS only through custom properties set with CSSOM (no style="" attributes).
export function setVar(el, name, value) {
  el.style.setProperty(name, String(value));
}

// Polite live-region update; clearing first makes screen readers announce a repeated message.
export function announce(region, text) {
  region.textContent = '';
  requestAnimationFrame(() => { region.textContent = text; });
}

export async function copyText(text) {
  await navigator.clipboard.writeText(text);
}
