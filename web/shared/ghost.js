// SPDX-License-Identifier: MIT
// The ghost's few moves (14-ghost-design §3, §6). Fifth pass: no page carries the ghost any more (its
// partials and ghost.css are gone; web/site/tests checks it), so cloneGhost() finds no template and returns
// null and every other move is a no-op. Kept so the widget and card modules keep their imports.

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

const EASE = 'cubic-bezier(.22, 1, .36, 1)';

// The wow, first half (14-ghost-design §6): a blank note (never the secret, never a file's name) arcs
// from `from` ({x, y} in the viewport; under the ghost when omitted) into the ghost's open mouth
// (380 ms), then the ghost gulps (320 ms). Resolves 240 ms into the gulp, when the result may start;
// under reduced motion, at once (a cut). The ghost is left busy, hugging the note.
export async function swallow(el, from = null) {
  const svg = ghostOf(el);
  if (!svg) return;
  setGhost(el, 'catch');
  const note = flyer();
  if (reduced() || !note) return setGhost(el, 'busy');
  const g = svg.getBoundingClientRect();
  const mouth = { x: g.left + g.width / 2, y: g.top + g.height * (71 / 120) };
  const start = from ?? { x: mouth.x, y: g.bottom + 60 };
  const at = (x, y, rest) => `translate(${x - 32}px, ${y - 39}px) ${rest}`;
  document.body.append(note);
  try {
    await note.animate([
      { transform: at(start.x, start.y, 'rotate(-8deg) scale(1)') },
      { transform: at((start.x + mouth.x) / 2, Math.min(start.y, mouth.y) - 110, 'rotate(6deg) scale(.8)'), offset: 0.55 },
      { transform: at(mouth.x, mouth.y, 'rotate(0) scale(.12)') },
    ], { duration: 380, easing: 'cubic-bezier(.5, 0, .3, 1)' }).finished;
  } catch {
    // cancelled: the note is removed below either way
  }
  note.remove();
  setGhost(el, 'busy');
  gulp(el);
  await new Promise((r) => setTimeout(r, 240));
}

// Takes away a flying note still in the air (an error interrupts the wow).
export function dropNotes() {
  for (const n of document.querySelectorAll('body > .flyer')) n.remove();
}

// The wow, second half: `el` glides from the box `from` (a DOMRect it had before the layout changed)
// into its place, one FLIP (320 ms); nothing under reduced motion.
export function glide(el, from) {
  if (!el || !from || reduced()) return;
  const to = el.getBoundingClientRect();
  if (!to.width) return;
  const dx = from.left + from.width / 2 - (to.left + to.width / 2);
  const dy = from.top + from.height / 2 - (to.top + to.height / 2);
  el.animate([{ transform: `translate(${dx}px, ${dy}px) scale(${from.width / to.width})` }, { transform: 'none' }],
    { duration: 320, easing: EASE });
}

// A panel unrolls from its top edge (320 ms) while the ghost glides; nothing under reduced motion.
export function unroll(el) {
  if (!el || reduced()) return;
  el.animate([{ clipPath: 'inset(0 0 100% 0 round 22px)', translate: '0 -12px' }, { clipPath: 'inset(0 0 0 0 round 22px)', translate: '0 0' }],
    { duration: 320, easing: EASE });
}
