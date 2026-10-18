// SPDX-License-Identifier: MIT
// Under the hood (/made, how it was made): the live parts of "Check us" (14-ghost-design §8). The status line from
// /status.json, our own test transactions from /evidence.json, and the hourly test file you can try
// to read (and, once it is a day old, open with its published key). Each loads when it comes near;
// a failed request leaves its block hidden. Numbers and copy variants come from site.js.
// And the contents (the docs layout): the part being read is marked in the contents and named in the breadcrumb, a
// link to something inside a closed disclosure opens it, and On this page closes after a tap. Without JavaScript
// the contents are plain links and every disclosure opens by hand.
import './site.js';

function whenNear(element, fn) {
  if (!element) return;
  new IntersectionObserver(([entry], observer) => {
    if (!entry.isIntersecting) return;
    observer.disconnect();
    fn();
  }, { rootMargin: '100% 0px' }).observe(element);
}

const check = document.getElementById('check');
whenNear(check, () => {
  import('./status.js').then((m) => m.showStatus(check.querySelector('[data-status-line]')));
  import('./evidence.js').then((m) => m.showEvidence(check.querySelector('[data-evidence]')));
});
const tryIt = document.getElementById('try');
whenNear(tryIt, () => import('./canary.js').then(async (m) => m.showCanary(tryIt, await m.loadCanary())));

// The part being read: the last part whose card crosses a line just under the header and the breadcrumb (112 px down,
// 24 px thick), so the part a contents link brings there is the one marked; the first while the page's head is in
// view; the last once half the footer is, since the page can't scroll it that high.
const parts = [...document.querySelectorAll('.doc > section[id]')];
const links = [...document.querySelectorAll('[data-toc] a[href^="#"]')];
const crumb = document.querySelector('[data-crumb]');
let current = null;
function mark(part) {
  if (!part || part === current) return;
  current = part;
  for (const a of links) {
    if (a.hash !== `#${part.id}`) {
      a.removeAttribute('aria-current');
      continue;
    }
    a.setAttribute('aria-current', 'location');
    const group = a.closest('.side-group');
    if (group) group.open = true;
  }
  const name = links.find((a) => a.hash === `#${part.id}`);
  if (crumb) {
    crumb.textContent = name ? name.textContent : '';
    crumb.hidden = !name;
  }
}
const TOP = 112;
const LINE = 24;
const crossing = new Set();
let atEnd = false;
const pick = () => mark(atEnd ? parts.at(-1) : parts.filter((p) => crossing.has(p)).at(-1)
  ?? (parts[0].getBoundingClientRect().top > TOP ? parts[0] : null));
let line = null;
let lineFor = 0;
function watch() {
  if (innerHeight === lineFor) return;
  lineFor = innerHeight;
  line?.disconnect();
  crossing.clear();
  line = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) crossing.add(e.target);
      else crossing.delete(e.target);
    }
    pick();
  }, { rootMargin: `-${TOP}px 0px ${Math.min(0, TOP + LINE - innerHeight)}px 0px` });
  for (const part of parts) line.observe(part);
}
if (parts.length) {
  watch();
  addEventListener('resize', watch);
  const footer = document.querySelector('.site-footer');
  if (footer) {
    new IntersectionObserver(([e]) => {
      atEnd = e.intersectionRatio >= 0.5;
      pick();
    }, { threshold: [0, 0.5] }).observe(footer);
  }
  mark(parts[0]);
}

// A link to something inside a closed disclosure (#free, #disclosure, #addresses…) opens it first, from the page
// or from another page; a tap in On this page closes the list before the page moves, so the part lands in place.
function openTo(hash) {
  let target = null;
  try {
    target = hash.length > 1 && document.getElementById(decodeURIComponent(hash.slice(1)));
  } catch {
    return null;   // a malformed fragment: nothing to open
  }
  if (!target) return null;
  let opened = false;
  for (let d = target.closest('details'); d; d = d.parentElement.closest('details')) {
    if (!d.open && !d.matches('.page-jump')) {
      d.open = true;
      opened = true;
    }
  }
  return opened ? target : null;
}
document.addEventListener('click', (e) => {
  const a = e.target.closest?.('a[href^="#"]');
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const jump = a.closest('.page-jump');
  if (jump) jump.open = false;
  openTo(a.hash);
});
addEventListener('hashchange', () => openTo(location.hash)?.scrollIntoView());
openTo(location.hash)?.scrollIntoView();
