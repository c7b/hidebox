// SPDX-License-Identifier: MIT
// One vocabulary for a wait and its result (docs/review/ux-feedback-1.md). steps(): the real steps of a run,
// each lit as it happens (done, now, to do, failed), the time the step in progress has taken, a line under it
// that can change as it waits, and a bar that never stands still: it fills when the step knows how far it got
// and sweeps when it can't. done(): the moment a run worked: the open box takes the thing in and a check lands
// on it, one line in people's words, the chain's line and its receipt, then what to do next. The drop page,
// /send, the share dialog's Send by Tari and the pay page draw their steps with this; the styles are
// app/css/flow.css, which the link pages, the task pages and the drive all load. Lucide's sprite for the icons.
import { svg } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { h } from './lines.js';

const SPRITE = '/shared/ui/icons.svg';

export const glyph = (name, cls = 'fl-icon') => svg('svg', { class: cls, 'aria-hidden': 'true', focusable: 'false' },
  svg('use', { href: `${SPRITE}#i-${name}` }));

const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
const SHOW_TIME_S = 2;   // a step that ends sooner shows no clock: it would only flash

// list: [[id, label], …]. -> {el, at(id, {note, fraction}), note(text | (seconds) => text), fraction(f | null),
// fail(), finish(), stop(), now}. A note given as a function is asked again every second (a countdown, a hint
// that comes after a while); fraction null is the sweep, 0 to 1 fills the bar.
export function steps(list, { label, testid = null, live = null } = {}) {
  const items = list.map(([id, text]) => {
    const dot = h('span', { class: 'dot' });
    const time = h('span', { class: 'step-time', 'aria-hidden': 'true' });
    const note = h('span', { class: 'step-note' });
    const li = h('li', { 'data-step': id, 'data-state': 'todo' }, dot, h('span', { class: 'step-label' }, text), time, note);
    return { id, text, li, dot, time, note };
  });
  const fill = h('span', {});
  const bar = h('div', { class: 'flow-bar', role: 'progressbar', 'aria-label': label, 'data-mode': 'busy' }, fill);
  // A screen reader hears each step as it starts: in the page's live region, or in the run's own.
  const say = live ?? h('p', { class: 'sr-only', role: 'status', 'aria-live': 'polite' });
  const el = h('div', { class: 'flow', 'data-state': 'run', 'data-testid': testid },
    h('ol', { class: 'steps', 'aria-label': label }, items.map((x) => x.li)), bar, live ? null : say);
  let now = -1;
  let since = 0;
  let noteOf = null;
  let timer = null;
  let shown = false;   // once on the page, leaving it stops the clock
  let away = 0;        // ticks spent off the page: a wait never shown, or gone within its first second

  const paint = () => {
    const x = items[now];
    if (!x) return;
    const s = Math.floor((Date.now() - since) / 1000);
    x.time.textContent = s >= SHOW_TIME_S ? clock(s) : '';
    if (typeof noteOf === 'function') x.note.textContent = noteOf(s) ?? '';
  };
  const run = () => {
    clearInterval(timer);
    timer = setInterval(() => {
      if (el.isConnected) {
        shown = true;
        away = 0;
        paint();
      } else if (shown || ++away > 3) clearInterval(timer);
    }, 1000);
  };

  function mark(i, state) {
    const x = items[i];
    if (x.li.dataset.state === state && state !== 'now') return;   // a done step keeps its check (no replay)
    x.li.dataset.state = state;
    if (state === 'now') x.li.setAttribute('aria-current', 'step');
    else x.li.removeAttribute('aria-current');
    x.dot.replaceChildren(state === 'done' ? glyph('check') : state === 'failed' ? glyph('x') : state === 'now' ? glyph('loader-circle', 'fl-icon spinner') : '');
    if (state !== 'now') {
      x.time.textContent = '';
      x.note.textContent = '';
    }
  }

  const ctl = {
    el,
    get now() { return items[now]?.id ?? null; },
    // A new step starts with no note and the sweep; on the same step only what `opts` names changes.
    at(id, opts = {}) {
      const i = items.findIndex((x) => x.id === id);
      if (i < 0) return ctl;
      const moved = i !== now;
      if (moved) {
        items.forEach((x, j) => { if (j !== i) mark(j, j < i ? 'done' : 'todo'); });
        mark(i, 'now');
        now = i;
        since = Date.now();
        el.dataset.state = 'run';
        say.textContent = items[i].text;
        run();
      }
      if (moved || 'note' in opts) ctl.note(opts.note ?? null);
      if (moved || 'fraction' in opts) ctl.fraction(opts.fraction ?? null);
      return ctl;
    },
    note(text) {
      noteOf = text;
      if (items[now]) items[now].note.textContent = typeof text === 'function' ? (text(Math.floor((Date.now() - since) / 1000)) ?? '') : (text ?? '');
      return ctl;
    },
    fraction(f) {
      if (f === null || f === undefined) {
        bar.dataset.mode = 'busy';
        bar.removeAttribute('aria-valuenow');
      } else {
        const v = Math.max(0, Math.min(1, f));
        bar.dataset.mode = 'value';
        bar.setAttribute('aria-valuenow', String(Math.round(v * 100)));
        fill.style.setProperty('--value', String(v));
      }
      return ctl;
    },
    fail() {
      clearInterval(timer);
      if (now >= 0) mark(now, 'failed');
      el.dataset.state = 'failed';
      bar.dataset.mode = 'value';
      return ctl;
    },
    finish() {
      clearInterval(timer);
      items.forEach((_, j) => mark(j, 'done'));
      now = items.length;
      el.dataset.state = 'done';
      bar.dataset.mode = 'value';
      fill.style.setProperty('--value', '1');
      return ctl;
    },
    stop() {
      clearInterval(timer);
      return ctl;
    },
  };
  return ctl;
}

// The words under a step while our relay holds a delivery and then while the chain takes it. The relay sends
// at not_before (unix seconds, a moment it picks): until then the bar fills toward it; a clock far off ours (more
// than a minute out) gets the words without the count. -> {sending()}: the job says it is on its way.
export function relayWait(run, notBefore) {
  const queued = Date.now();
  const until = Number(notBefore) * 1000;
  const left = () => Math.ceil((until - Date.now()) / 1000);
  const counts = Number.isFinite(until) && left() > 0 && left() <= 60;
  run.fraction(counts ? 0 : null).note(() => {
    const n = left();
    if (counts && n > 0) run.fraction((Date.now() - queued) / (until - queued));
    if (!counts) return t('relay.soon');
    return n > 0 ? t('relay.in', { count: n }) : t('relay.now');
  });
  let since = 0;
  return {
    sending() {
      if (since) return;
      since = Date.now();
      run.fraction(null).note(() => t(Date.now() - since > 40000 ? 'relay.slow' : 'relay.chain'));
    },
  };
}

// One line with the turning dot and the time it has taken: a wait with a single step (reading a transaction
// from the indexer). -> {el, note(text | fn), stop()}
export function waiting(text, { testid = null } = {}) {
  const run = steps([['wait', text]], { label: text, testid });
  run.el.classList.add('flow--one');
  run.at('wait');
  return run;
}

// The moment it worked. art: the glyph of what went in ('file-image', 'file-text', 'file'), or null for the box
// alone; tone 'bad' lands a red cross instead of the check (a transaction the chain refused); title: the one
// line (an h1 by default); say: what happened, in people's words; chain: the Tari chain's line, with receipt:
// {href, tx, label, testid, txTestid} under it; more: nodes beside them (a photo's chip); actions: buttons;
// foot: a closing note. -> the element (its heading focusable, id `${id}-h`).
export function done({ id = 'done', art = 'file', tone = 'ok', title, say = null, chain = null, receipt = null, more = [], actions = [],
  foot = null, heading = 'h1', testid = null } = {}) {
  const box = h('div', { class: 'done-art', 'aria-hidden': 'true', 'data-tone': tone },
    art ? h('span', { class: 'done-file' }, glyph(art)) : null,
    h('span', { class: 'done-box' }, glyph('hidebox')),
    h('span', { class: 'done-check' }, glyph(tone === 'ok' ? 'check' : 'x')));
  const tx = receipt?.tx ?? '';
  return h('section', { class: 'done', id, 'aria-labelledby': `${id}-h`, 'data-testid': testid },
    box,
    h(heading, { class: 'done-title', id: `${id}-h`, tabindex: '-1' }, title),
    say ? h('p', { class: 'done-say' }, say) : null,
    chain || receipt ? h('div', { class: 'done-chain', 'data-tari': '' },   // Tari's violet: a Tari receipt
      chain ? h('p', { class: 'done-chain-line' }, glyph('shield-check'), h('span', {}, chain)) : null,
      receipt ? h('a', { class: 'done-receipt', href: receipt.href, 'data-testid': receipt.testid ?? null, 'data-tx': tx || null },
        glyph('receipt-text'), h('span', {}, receipt.label),
        tx ? h('span', { class: 'mono', 'data-testid': receipt.txTestid ?? null, 'data-tx': tx }, `${tx.slice(0, 8)}…${tx.slice(-8)}`) : null,
        glyph('arrow-right')) : null) : null,
    ...more,
    actions.length ? h('div', { class: 'done-actions' }, actions) : null,
    foot);
}
