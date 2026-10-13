// SPDX-License-Identifier: MIT
// The head of an app screen (14-ghost-design §3, DESIGN.md "one centered column for every task
// screen"): the ghost in the pose that says the screen's rule, the screen's one line, and the
// ghost's sentence under it. The ghost comes from the page's <template id="ghost-tpl"> (no HTML is
// parsed from strings); "Tari™" words are set in Tari purple, the one thing purple may mean.
import { h } from '../lib/dom.js';
import { cloneGhost, setGhost } from '/shared/ghost.js';

const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// The ghost in `state`, in a holder that keeps its size while it loads; decorative (the words say it).
export function figure(state, cls = null) {
  const holder = h('div', { class: ['a-figure', cls], 'data-ghost': state, 'aria-hidden': 'true' });
  const svg = cloneGhost(state);
  if (svg) holder.append(svg);
  return holder;
}

// The ghost leaves: it shows `from` for a moment, then fades to its dashed outline and waves (the
// pose change is ghost.css's own 340 ms transition). Under reduced motion it is a cut.
export function goodbye(holder, from = 'keep') {
  if (reduced()) return setGhost(holder, 'gone');
  setGhost(holder, from);
  setTimeout(() => setGhost(holder, 'gone'), 650);
}

// "Tari™ chain" and "Tari™" inside a sentence, in Tari purple.
export function tariText(text) {
  // split() with a group puts every match at an odd index
  return String(text).split(/(Tari™ chain|Tari™)/).map((p, i) => (i % 2 ? h('span', { class: 'chain-word' }, p) : p)).filter((p) => p !== '');
}

// The screen's head: the ghost, the one line (h1) and the ghost's sentence (a string, or nodes).
// `small`: inside another page (an inbox row), with an h2 and a smaller ghost.
export function scene({ state, title, say = null, id = null, cls = null, small = false }) {
  const ghost = figure(state);
  const head = h('header', { class: ['a-scene', small ? 'a-scene--small' : null, cls] },
    ghost,
    h(small ? 'h2' : 'h1', { class: 'a-scene-h', id, tabindex: '-1' }, title),
    say == null ? null : h('p', { class: 'a-say' }, typeof say === 'string' ? tariText(say) : say));
  return { head, ghost };
}
