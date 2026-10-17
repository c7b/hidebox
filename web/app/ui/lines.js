// SPDX-License-Identifier: MIT
// One sentence a line (site v4, the owner's rule): in a paragraph, every sentence after the first starts on
// its own line. A <br> follows each sentence's end and the space before it stays, so the words read the same
// to screen readers, search and textContent. The drive's modules get it through behaviors.js's h(); the link
// and task pages import it from here. Paragraphs: <p>, <dd>, and the alert titles, choice, item and toast
// descriptions that hold their text directly. The home's drop widget keeps lib/dom.js (A-06).
import { h as el } from '../lib/dom.js';

const END = /([.!?][”’")]?) (?=[“‘"(]?[A-Z])/;   // a sentence's end, kept by split (no lookbehind: older Safari)
const BOX = /(^|\s)(alert-title|choice-desc|item-description|toast-description)(\s|$)/;

export function lines(text) {
  const part = String(text).split(END);   // sentence, its end, sentence, its end, …, the last sentence
  const out = [];
  let now = part[0];
  for (let i = 1; i < part.length; i += 2) {
    out.push(`${now}${part[i]} `, el('br'));
    now = part[i + 1];
  }
  out.push(now);
  return out;
}

export function h(tag, props, ...children) {
  const cls = [props?.class ?? ''].flat().join(' ');
  const prose = (tag === 'p' || tag === 'dd' || BOX.test(cls)) && !/(^|\s)mono(\s|$)/.test(cls);
  return el(tag, props ?? {}, ...(prose ? children.flat(Infinity).map((c) => (typeof c === 'string' ? lines(c) : c)) : children));
}
