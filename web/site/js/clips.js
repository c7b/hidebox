// SPDX-License-Identifier: MIT
// /v2 only: the product loops (docs/review/home-v2.md). Every <video data-clip> is served without a source: its
// files wait in data-src and, below the fold, its poster in data-poster, so the page fetches nothing for a loop
// until it comes within 40 % of a screen. Then its poster arrives and, when the visitor allows motion (html.motion,
// set by theme.js) and has not paused it, its sources: it plays while a fifth of it or more is on screen and
// pauses when less is, or when the tab hides. With reduced motion only the poster arrives and nothing plays.
// WebKit (Safari, and every browser on iOS) plays the WebM without its alpha, so it gets the MP4, made on black, and
// its stage gives up its light (.is-opaque): a black card in light mode, nothing behind it in dark mode, where the
// frame's black fades into the page through the stage's edge mask.
// The Pause motion switch (WCAG 2.2.2) stops every loop on the page and is remembered on this device.
const KEY = 'mutis.loops';
const motion = document.documentElement.classList.contains('motion');
const ua = navigator.userAgent;
const webkit = /AppleWebKit/.test(ua) && !/(Chrome|Chromium|Edg|OPR)\//.test(ua);
const clips = [...document.querySelectorAll('video[data-clip]')];
const toggle = document.querySelector('[data-loops]');

const stored = () => {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
};
let paused = stored() === 'off';

const play = (v) => {
  if (motion && !paused && v.dataset.live && v.seen && !document.hidden) v.play().catch(() => null);   // refused: the poster stays
};

function load(v) {
  if (v.dataset.poster && !v.hasAttribute('poster')) v.poster = v.dataset.poster;
  if (!motion || paused || v.dataset.live) return;
  v.dataset.live = 'on';
  for (const s of v.querySelectorAll('source')) {
    if (webkit && s.type.startsWith('video/webm')) s.remove();
    else s.src = s.dataset.src;
  }
  if (webkit) v.parentElement.classList.add('is-opaque');
  v.load();
}

const near = new IntersectionObserver((seen) => {
  for (const e of seen) {
    if (!e.isIntersecting) continue;
    near.unobserve(e.target);
    e.target.near = true;
    load(e.target);
  }
}, { rootMargin: '40% 0px' });
const view = new IntersectionObserver((seen) => {
  for (const e of seen) {
    e.target.seen = e.isIntersecting && e.intersectionRatio >= 0.19;
    if (e.target.seen) play(e.target);
    else e.target.pause();
  }
}, { threshold: [0, 0.2] });

for (const v of clips) {
  // autoplay starts a loop as soon as it can; one off screen, in a hidden tab or paused by the visitor waits
  v.addEventListener('play', () => { if (!v.seen || document.hidden || paused) v.pause(); });
  near.observe(v);
  view.observe(v);
}
document.addEventListener('visibilitychange', () => {
  for (const v of clips) {
    if (document.hidden) v.pause();
    else play(v);
  }
});

if (toggle && motion) {
  const paint = () => toggle.setAttribute('aria-pressed', String(paused));
  paint();
  toggle.hidden = false;
  toggle.addEventListener('click', () => {
    paused = !paused;
    try {
      if (paused) localStorage.setItem(KEY, 'off');
      else localStorage.removeItem(KEY);
    } catch {
      // blocked storage: the choice lasts for this page
    }
    paint();
    for (const v of clips) {
      if (paused) v.pause();
      else if (v.near) {
        load(v);
        play(v);
      }
    }
  });
}
