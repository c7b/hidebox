// SPDX-License-Identifier: MIT
// The head of an app screen (DESIGN.md "one centered column for every task screen"): an icon tile that
// says the screen's state, the screen's one line, and its sentence under it. No mascot
// (16-drive-design §0): the tile is the drive's empty-state tile with a Lucide icon from
// /shared/ui/icons.svg. "Tari™" words are set in Tari purple, the one thing purple may mean.
import { svg } from '../lib/dom.js';
import { h } from './lines.js';

// What each old pose now shows: a plain Lucide glyph.
const GLYPH = {
  ready: 'lock', catch: 'inbox', busy: 'loader-circle', once: 'eye', few: 'eye', word: 'key-round', peek: 'eye',
  courier: 'send', bag: 'wallet', keep: 'file-lock', gone: 'circle-check', oops: 'triangle-alert',
};

const tile = (state) => svg('svg', { class: 'a-tile-icon', 'aria-hidden': 'true', focusable: 'false' },
  svg('use', { href: `/shared/ui/icons.svg#i-${GLYPH[state] ?? 'lock'}` }));

// The tile for `state`; decorative (the words say it).
export function figure(state, cls = null) {
  return h('div', { class: ['a-figure', cls], 'data-pose': state, 'aria-hidden': 'true' }, tile(state));
}

// An ended link: the tile turns to its ended state (no animation).
export function goodbye(holder) {
  if (!holder) return;
  holder.dataset.pose = 'gone';
  holder.replaceChildren(tile('gone'));
}

// "Tari™ chain" and "Tari™" inside a sentence, in Tari purple.
export function tariText(text) {
  // split() with a group puts every match at an odd index
  return String(text).split(/(Tari™ chain|Tari™)/).map((p, i) => (i % 2 ? h('span', { class: 'chain-word' }, p) : p)).filter((p) => p !== '');
}

// The screen's head: the tile, the one line (h1) and the sentence (a string, or nodes).
// `small`: inside another page (an inbox row), with an h2 and a smaller tile.
export function scene({ state, title, say = null, id = null, cls = null, small = false }) {
  const ghost = figure(state);
  const head = h('header', { class: ['a-scene', small ? 'a-scene--small' : null, cls] },
    ghost,
    h(small ? 'h2' : 'h1', { class: 'a-scene-h', id, tabindex: '-1' }, title),
    say == null ? null : h('p', { class: 'a-say' }, typeof say === 'string' ? tariText(say) : say));
  return { head, ghost };
}
