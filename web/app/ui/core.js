// SPDX-License-Identifier: MIT
// Small pieces every screen shares, the drop widget included: icons from the shared sprite, durations
// in words, copy buttons and toasts. Strings come from i18n; nothing here holds state.
import { announce, copyText, h, svg } from '../lib/dom.js';
import { t } from '../lib/i18n.js';

// replaceChildren() without the nulls that conditional children leave behind (the DOM would print them).
export function fill(el, ...children) {
  el.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

// The sprite's address as one string, so the build can give it its fingerprinted name (tools/assets.py).
const SPRITE = '/shared/icons.svg';

export function icon(name, cls = 'a-icon') {
  return svg('svg', { class: cls, 'aria-hidden': 'true', focusable: 'false' },
    svg('use', { href: `${SPRITE}#${name}` }));
}

// "10 minutes", "24 hours", "7 days" (11-brand §8.3): days from two days up, hours from one hour up.
export function formatDuration(seconds) {
  const [unit, size] = seconds >= 172800 ? ['day', 86400] : seconds >= 3600 ? ['hour', 3600] : ['minute', 60];
  return t(`dur.${unit}`, { count: Math.max(1, Math.round(seconds / size)) });
}

let toastTimer = null;

// One transient line at the bottom of the screen. `near` is any element of the caller: inside the drop
// widget the toast lives in the widget's own root (the only part of the home page the widget owns),
// is a picture only (aria-hidden), and the widget's one live region says the line; elsewhere the toast
// is a status region itself.
export function toast(text, near = null) {
  const host = near?.closest('.md-root') ?? document.body;
  const region = host === document.body ? null : host.querySelector(':scope > .md-live');
  let el = host.querySelector(':scope > .a-toast');
  if (!el) {
    el = h('p', { class: 'a-toast', role: region ? null : 'status', 'aria-hidden': region ? 'true' : null });
    host.append(el);
  }
  el.textContent = text;
  el.hidden = false;
  if (region) announce(region, text);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
}

// A button that copies `getText()`; on refusal it selects `fallback` (an element) for a manual copy.
export function copyButton({ label, testid, getText, fallback, done = t('toast.copied'), cls = 'a-btn' }) {
  const button = h('button', { type: 'button', class: cls, 'data-testid': testid }, icon('copy'), h('span', {}, label));
  button.addEventListener('click', async () => {
    try {
      await copyText(getText());
      toast(done, button);
    } catch {
      if (fallback) {
        const range = document.createRange();
        range.selectNodeContents(fallback);
        getSelection().removeAllRanges();
        getSelection().addRange(range);
      }
      toast(t('error.clipboard'), button);
    }
  });
  return button;
}
