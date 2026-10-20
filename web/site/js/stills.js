// SPDX-License-Identifier: MIT
// /how only: the stills replay what they show. Each .still-frame[data-loop] is a loop of that many ms; its parts name
// their beats, data-beats="lock@300 send@650 ok@2100" (a state, and when in the loop it starts). This sets each part's
// data-beat as its time comes (empty before the first) and --next, how long that beat lasts; css/how.css draws every
// state with the app's own words. A loop plays while a fifth of it or more is on screen and the tab shows; it opens on
// its settled still and starts over a moment later. Off screen, in a hidden tab, paused or once reduced motion is
// turned on, every part rests at once on its last beat: the settled still, which reduced motion shows too (how.css);
// without JavaScript the stills stay as served. The pictures stay aria-hidden, so nothing here is read out; each
// still's words say what it shows.
// Pause motion (WCAG 2.2.2) stops every loop on the page and is remembered on this device (mutis.loops).
// site.js loads this after the load event, only when motion is allowed (html.motion).
const KEY = 'mutis.loops', FIRST = 1500;

const stored = () => {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
};
let paused = stored() === 'off';

function loop(frame) {
  const length = +frame.dataset.loop;
  const parts = [...frame.querySelectorAll('[data-beats]')].map((el) => {
    const beats = el.dataset.beats.split(' ').map((b) => b.split('@')).map(([name, at]) => ({ name, at: +at }));
    beats.forEach((b, i) => { b.lasts = (beats[i + 1]?.at ?? length) - b.at; });
    return { el, beats };
  });
  const last = Math.max(...parts.map((p) => p.beats.at(-1).at));
  let t0 = 0, timer = 0;
  // every part as it is t ms into the loop; -> ms to the next beat (or to the loop's end)
  const paint = (t) => {
    let next = length;
    for (const { el, beats } of parts) {
      const now = beats.findLast((b) => b.at <= t), name = now?.name ?? '';
      if (el.dataset.beat !== name) {
        el.dataset.beat = name;
        if (now) el.style.setProperty('--next', `${now.lasts}ms`);
      }
      next = Math.min(next, beats.find((b) => b.at > t)?.at ?? length);
    }
    return next - t;
  };
  const tick = () => {
    timer = setTimeout(tick, paint((performance.now() - t0) % length) + 1);
  };
  return {
    play() {
      if (frame.classList.contains('playing')) return;
      frame.classList.add('playing');
      t0 = performance.now() - Math.max(last, length - FIRST);
      tick();
    },
    stop() {
      clearTimeout(timer);
      frame.classList.remove('playing');
      paint(last);
      for (const { el } of parts) {
        el.style.removeProperty('--next');
        if (!el.style.length) el.removeAttribute('style');
      }
    },
  };
}

export function start() {
  const frames = [...document.querySelectorAll('.still-frame[data-loop]')];
  const toggle = document.querySelector('[data-loops]');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');   // turned on while the page is open: all rest
  const run = (f) => (f.seen && !paused && !reduce.matches && !document.hidden ? f.loop.play() : f.loop.stop());
  const view = new IntersectionObserver((seen) => {
    for (const e of seen) {
      e.target.seen = e.isIntersecting && e.intersectionRatio >= 0.19;
      run(e.target);
    }
  }, { threshold: [0, 0.2] });
  for (const f of frames) {
    f.loop = loop(f);
    view.observe(f);
  }
  document.addEventListener('visibilitychange', () => frames.forEach(run));
  reduce.addEventListener('change', () => {
    if (toggle) toggle.hidden = reduce.matches;
    frames.forEach(run);
  });
  if (!toggle) return;
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
    frames.forEach(run);
  });
}
