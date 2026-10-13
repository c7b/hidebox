// SPDX-License-Identifier: MIT
// The ghost's few moves (14-ghost-design §3, §6), for the site and the app alike. Its markup is a
// static partial (web/shared/partials/ghost.svg): the build inlines it where a page shows a ghost and
// keeps a copy in <template id="ghost-tpl">, which cloneGhost() uses. No HTML is ever parsed from a
// string (Trusted Types). A state is `data-state` on the svg; ghost.css draws it.

export const STATES = ['ready', 'catch', 'busy', 'once', 'few', 'word', 'peek', 'courier', 'bag', 'keep', 'gone', 'oops'];

const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// The svg of `el` (the svg itself, or the element that holds it).
export const ghostOf = (el) => (el?.matches?.('svg.ghost') ? el : el?.querySelector?.('svg.ghost') ?? null);

// Shows `state` on the ghost in `el`; the parent's data-ghost follows, for pages without scripts.
export function setGhost(el, state) {
  const svg = ghostOf(el);
  if (!svg) return;
  svg.dataset.state = state;
  if (svg.parentElement?.hasAttribute('data-ghost')) svg.parentElement.dataset.ghost = state;
}

// A new ghost from the page's template, in `state`; null on a page without the template.
export function cloneGhost(state = 'ready', doc = document) {
  const tpl = doc.getElementById('ghost-tpl');
  const svg = tpl?.content.querySelector('svg.ghost')?.cloneNode(true) ?? null;
  if (svg) svg.dataset.state = state;
  return svg;
}

// The gulp of the wow: a quick squash and stretch on an ease-out curve (320 ms; none under reduced motion).
export function gulp(el) {
  const body = ghostOf(el)?.querySelector('.gf');
  if (!body || reduced()) return Promise.resolve();
  return body.animate(
    [{ transform: 'scale(1, 1)' }, { transform: 'scale(1.1, .86)' }, { transform: 'scale(.94, 1.08)' }, { transform: 'scale(1, 1)' }],
    { duration: 320, easing: 'cubic-bezier(.22, 1, .36, 1)' },
  ).finished.catch(() => undefined);
}

// The blank flying note, from <template id="flyer-tpl">; null when the page has none.
export function flyer(doc = document) {
  return doc.getElementById('flyer-tpl')?.content.firstElementChild?.cloneNode(true) ?? null;
}
