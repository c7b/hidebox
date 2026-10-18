// SPDX-License-Identifier: MIT
// Site v3 motion (docs/review/site-v3.md): the template's kinds of motion. Reveals as things scroll in, once
// (headings, paragraphs, cards, pictures, rows, badges; 60 ms apart); one statement a page out of the blur word
// by word; the hero picture's decode (hex noise resolving into its words, 1.1 s) and Who sees what's labels.
// Real words never leave the page (the noise is aria-hidden) and every element ends as served. Only what is
// below the fold when this runs is hidden; without it (no JavaScript, reduced motion, a failed load) all shows.
// The home's drop widget (.quick-body) is a tool: never hidden or moved by a reveal (a tap as it rose missed; E-19).
const root = document.documentElement;
const STEP = 60, MAX = 8, HEX = '0123456789abcdef';
const KINDS = [
  ['main h2, .more-try h3', 'head'],
  ['.share-pic, .still-frame', 'pic'],
  ['.sides > li, .track, .coin-box, .chain-rows, .hood', 'card'],
  ['.compare tr, .claim-table tr, .steps > li, .chain-rows > li, .rule-groups > div, .more-try li', 'row'],
  ['.rule-groups .badge', 'badge'],
  ['.sec-head > p, .quick-head > p, .closing > :not(h2), .still-copy > p, .track-top > p, .compare-note, .sides-foot, .outro', 'up'],
];
const WORDS = '#different .sec-head > p, #check .sec-head > p';

const noise = (text) => text.replace(/\S/g, () => HEX[Math.random() * 16 | 0]);
const below = (el) => el.getBoundingClientRect().top > innerHeight;
const after = (ms, f) => setTimeout(f, ms + 50);
// leaves an element as the page served it: no empty class or style attribute behind
const clean = (el, ...names) => {
  el.classList.remove(...names);
  el.style.transitionDelay = '';
  if (!el.classList.length) el.removeAttribute('class');
  if (!el.style.length) el.removeAttribute('style');
};

// A decode: cells = [{ units: elements shown when it resolves, node: its text node (optional), at, dur }].
// Each text node gets a twin in an aria-hidden layer over `box`, at the same place in the same type.
function decode(box, cells) {
  const layer = document.createElement('div');
  const b = box.getBoundingClientRect(), range = document.createRange();
  layer.className = 'dc-layer';
  layer.setAttribute('aria-hidden', 'true');
  for (const c of cells) {
    c.units.forEach((u) => u.classList.add('dc-c'));
    if (!c.node) continue;
    range.selectNodeContents(c.node);
    const r = range.getBoundingClientRect(), css = getComputedStyle(c.node.parentElement);
    if (!r.width) continue;
    const s = c.span = layer.appendChild(document.createElement('span'));
    c.text = c.node.data;
    Object.assign(s.style, {
      left: `${r.left - b.left - box.clientLeft}px`, top: `${r.top - b.top - box.clientTop}px`, width: `${r.width}px`,
      height: `${r.height}px`, lineHeight: `${r.height}px`, fontFamily: css.fontFamily, fontSize: css.fontSize,
      fontWeight: css.fontWeight, letterSpacing: css.letterSpacing,
    });
    s.textContent = noise(c.text);
  }
  box.classList.replace('dc-run', 'dc-box') || box.classList.add('dc-box');   // the units hide themselves now
  box.append(layer);
  const t0 = performance.now();
  let shuffled = 0;
  const tick = (now) => {
    const t = now - t0, fresh = t - shuffled > 50;
    if (fresh) shuffled = t;
    let left = 0;
    for (const c of cells) {
      if (c.done) continue;
      const p = (t - c.at) / c.dur;
      if (p >= 1) {
        c.done = true;
        c.units.forEach((u) => u.classList.add('dc-ok'));
        c.span?.classList.add('dc-ok');
      } else {
        left++;
        if (fresh && c.span) {
          const k = Math.max(0, p) * c.text.length | 0;
          c.span.textContent = c.text.slice(0, k) + noise(c.text.slice(k));
        }
      }
    }
    if (left) requestAnimationFrame(tick);
    else after(160, () => {
      layer.remove();
      clean(box, 'dc-box');
      for (const c of cells) c.units.forEach((u) => clean(u, 'dc-c', 'dc-ok'));
    });
  };
  requestAnimationFrame(tick);
}

// The hero's picture: the head, the column names, then each row; within a row the name, its badge, its state.
function slice(fig) {
  const cells = [];
  const text = (el) => [...el.childNodes].find((n) => n.nodeType === 3 && n.data.trim());
  const add = (units, node, at) => cells.push({ units, node, at, dur: Math.min(600, 240 + 15 * (node?.data.length || 0)) });
  const head = fig.querySelector('.slice-head');
  add([head.querySelector('.slice-tile'), head.querySelector('.slice-title')], text(head.querySelector('.slice-title')), 0);
  const lock = head.querySelector('.badge');
  add([lock], text(lock), 40);
  fig.querySelectorAll('.slice-cols span').forEach((s, i) => s.textContent && add([s], text(s), 55 + i * 20));
  [...fig.querySelectorAll('.slice-rows li:not([hidden])')].forEach((li, i) => {
    const at = 110 + 55 * i, name = li.querySelector('.name'), badge = li.querySelector('.badge'), state = li.querySelector('.state');
    add([li.querySelector(':scope > .icon'), name], text(name), at);
    add([badge], text(badge), at + 40);
    if (state.textContent) add([state], text(state), at + 80);
  });
  decode(fig, cells);
}

function words(p) {
  const old = [...p.childNodes];
  const parts = old.flatMap((n) => n.nodeType === 3
    ? n.data.split(/(\s+)/).map((w) => (/\S/.test(w) ? Object.assign(document.createElement('span'), { textContent: w }) : document.createTextNode(w)))
    : [n]);
  const units = parts.filter((n) => n.nodeType === 1);
  const step = Math.min(STEP, 700 / units.length);
  units.forEach((w, i) => {
    w.classList.add('mo-w');
    w.style.transitionDelay = `${Math.round(i * step)}ms`;
  });
  p.replaceChildren(...parts);
  p.classList.add('mo-ws');
  return () => after(500 + units.length * step, () => {
    units.forEach((w) => clean(w, 'mo-w'));
    p.replaceChildren(...old);
    clean(p, 'mo-ws', 'mo-in');
  });
}

export function start() {
  const fig = document.querySelector('.hero .slice');
  const late = performance.now() > 2900;   // home.css already showed the picture's words
  const waiting = [];
  const hide = (el, kind) => {
    el.classList.add('mo-h', `mo-${kind}`);
    waiting.push(el);
  };
  const seen = new Set();
  for (const p of document.querySelectorAll(WORDS)) if (below(p)) { seen.add(p); p.mo = words(p); waiting.push(p); }
  for (const [sel, kind] of KINDS) {
    for (const el of document.querySelectorAll(sel)) {
      if (seen.has(el) || el.closest('[hidden], .hero') || !below(el)) continue;
      seen.add(el);
      hide(el, kind);
    }
  }
  if (fig && !(late && !below(fig))) {
    fig.classList.add('dc-run');
    new IntersectionObserver((e, io) => { if (e[0].isIntersecting) { io.disconnect(); slice(fig); } }, { threshold: 0.3 }).observe(fig);
  }
  root.classList.add('mo');   // from here motion.js shows the picture's words, not home.css

  const io = new IntersectionObserver((entries) => {
    const now = entries.filter((e) => e.isIntersecting).map((e) => e.target)
      .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    now.forEach((el, i) => {
      io.unobserve(el);
      const delay = Math.min(i, MAX - 1) * STEP;
      if (!el.mo) el.style.transitionDelay = `${delay}ms`;
      el.classList.add('mo-in');
      if (el.mo) return el.mo();
      after(delay + 700, () => clean(el, ...[...el.classList].filter((c) => c.startsWith('mo-'))));
      const dts = el.matches('.sides > li') && el.querySelectorAll('.seen dt');
      if (dts?.length) {
        const text = (dt) => [...dt.childNodes].find((n) => n.nodeType === 3 && n.data.trim());
        decode(el, [...dts].map((dt, k) => ({ units: [dt], node: text(dt), at: delay + 150 + k * 60, dur: 360 })));
      }
    });
  }, { rootMargin: '0px 0px -8% 0px' });
  waiting.forEach((el) => io.observe(el));
}
