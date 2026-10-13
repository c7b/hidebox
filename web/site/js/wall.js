// SPDX-License-Identifier: MIT
// The exit wall (11-brand §9.3 S1): the one pinned scene. Native scroll and a sticky stage; this
// module turns the scroll into one progress value p (0 → 1) and writes only what changes with it:
// --e (0 → 1) on the few lockers leaving at that moment, --p on the closing words, and the stage
// directions. CSS does every transform. Writing p on the whole stage instead would restyle every
// locker on every frame, which a slow phone can't afford.
// The scripted scene starts as soon as this runs. When /api/v1/stats/wall brings at least 8 items before
// the lockers come into view, each locker becomes one of them: its exit rule and its size class
// (the box's depth), never an id, a time or whether it has left. The centre locker is always ours.
// The words come from wall-en.js.
import { drawNoise } from './noise.js';

const EXIT = 0.06;                 // how much of the scroll one locker's exit takes
const BEATS = [0, 0.12, 0.30, 0.48, 0.64, 0.80];
const CLOSING = [0.79, 0.93];      // the closing words change only within this part of the scroll
const MIN_ITEMS = 8;
const RULES = ['once', 'views', 'time', 'kept'];

const clamp01 = (x) => Math.min(1, Math.max(0, x));
const setVar = (el, name, v) => el.style.setProperty(name, String(v));

// Phone slots (.m1 … .m9) first, so a phone shows the newest items too; the sort is stable.
const phoneSlot = (locker) => Number([...locker.classList].find((c) => /^m\d$/.test(c))?.slice(1) ?? 99);
const slotsInPhoneOrder = (lockers) => lockers.sort((a, b) => phoneSlot(a) - phoneSlot(b));

function setText(locker, label, fate) {
  locker.querySelector('.label').textContent = label;
  locker.querySelector('.fate').textContent = fate;
}

// Data mode: relabel the non-centre lockers from /stats/wall, phone slots first. Every item is drawn
// lit with its rule: the wall never says which files have already left.
function applyData(section, items, t) {
  const lockers = slotsInPhoneOrder([...section.querySelectorAll('.locker:not(.centre)')]);
  lockers.forEach((locker, i) => {
    const item = items[i];
    locker.dataset.cue = item ? item.exit : 'empty';
    locker.classList.toggle('lit', Boolean(item));
    if (item) setVar(locker, '--size', item.size);
    setText(locker, t.labels[item?.exit ?? 'empty'], t.fates[item?.exit ?? 'empty']);
  });
  section.querySelector('[data-wall-desc]').textContent = t.desc(items.length);
}

// -> {beats: [start, end, lockers that leave in it, direction, cue], exits: [{locker, t0, d, e}]}.
// Empty slots are gone from the start.
function plan(section, t, dataMode) {
  const lockers = [...section.querySelectorAll('.locker:not(.centre)')];
  const group = (cue) => lockers.filter((l) => l.dataset.cue === cue);
  const exits = [];
  group('empty').forEach((locker) => setVar(locker, '--e', 1));
  const order = dataMode ? RULES : ['once', 'views', 'midnight', 'rest'];
  const groups = order.map((cue) => [cue, group(cue)]).filter(([, members]) => members.length);
  const span = (BEATS[5] - BEATS[1]) / Math.max(1, groups.length);
  const beats = [[0, BEATS[1], [], dataMode ? t.data.intro : t.script[0]]];
  groups.forEach(([cue, members], i) => {
    const start = BEATS[1] + i * span;
    const text = dataMode ? t.data[cue] : t.script[order.indexOf(cue) + 1];
    beats.push([start, start + span, members, text, cue]);
    // Countdown and clock beats wait before the exits; the others start at once, staggered.
    const lead = !dataMode && (cue === 'views' || cue === 'midnight') ? span * 0.45 : span * 0.1;
    members.forEach((locker, k) => {
      exits.push({ locker, t0: start + lead + (k * (span - lead - EXIT)) / Math.max(1, members.length), d: EXIT, e: null });
    });
  });
  beats.push([BEATS[5], 1.01, [], dataMode ? t.data.end : t.script[5]]);
  return { beats, exits };
}

// Writes --e only where it changed: at any moment, at most a few lockers are on their way out.
function stage(exits) {
  return (p) => {
    for (const exit of exits) {
      const e = Math.round(clamp01((p - exit.t0) / exit.d) * 1000) / 1000;
      if (e !== exit.e) {
        exit.e = e;
        setVar(exit.locker, '--e', e);
      }
    }
  };
}

function narrate(section, { beats }, t, dataMode) {
  const direction = section.querySelector('[data-wall-direction]');
  const clock = section.querySelector('[data-wall-clock]');
  const views = dataMode ? null : beats.find((b) => b[4] === 'views');
  let last = '';
  return (p) => {
    const [start, end, , text, cue] = beats.find(([s, e]) => p >= s && p < e) ?? beats[beats.length - 1];
    const local = clamp01((p - start) / (end - start));
    const clockText = !dataMode && cue === 'midnight' ? (local < 0.3 ? '23:59' : '00:00') : '';
    // (3 views) → (2 views) → (1 view) during their beat, and back again when scrolling up.
    const count = views ? Math.min(2, Math.floor(clamp01((p - views[0]) / (views[1] - views[0])) / 0.15)) : 0;
    const state = `${text}|${clockText}|${count}`;
    if (state === last) return;
    last = state;
    direction.textContent = text;
    clock.textContent = clockText;
    views?.[2].forEach((l) => { l.querySelector('.label').textContent = t.views[count]; });
  };
}

const validItem = (item) => RULES.includes(item?.exit) && Number.isInteger(item.size) && item.size >= 0 && item.size <= 4;

// -> { door(bytes), yours(bytes), useData(wall) } for home.js to call as data arrives.
// The stage is laid out for motion from the first paint (html.motion, set by /shared/theme.js), so
// starting the scene here moves nothing on the page.
export function initWall(section, t) {
  const motion = document.documentElement.classList.contains('motion');
  const door = section.querySelector('.noise-door');
  const lockers = section.querySelector('.wall');
  const closing = section.querySelectorAll('.wall-end, .wall-direction');
  let scene = () => {};
  let update = () => {};
  let mine = false;
  let closed = null;
  const start = (dataMode) => {
    const timing = plan(section, t, dataMode);
    const move = stage(timing.exits);
    const tell = narrate(section, timing, t, dataMode);
    scene = (p) => { move(p); tell(p); };
  };

  if (motion) {
    start(false);
    let raf = 0;
    let near = false;
    update = () => {
      raf = 0;
      const r = section.getBoundingClientRect();
      const p = clamp01(-r.top / Math.max(1, r.height - innerHeight));
      const q = Math.min(CLOSING[1], Math.max(CLOSING[0], p)).toFixed(4);
      if (q !== closed) {
        closed = q;
        for (const el of closing) setVar(el, '--p', q);
      }
      scene(p);
    };
    const tick = () => { if (near && !raf) raf = requestAnimationFrame(update); };
    new IntersectionObserver(([entry]) => {
      near = entry.isIntersecting;
      section.classList.toggle('active', near);
      tick();
    }, { rootMargin: '50% 0px' }).observe(section);
    addEventListener('scroll', tick, { passive: true });
    addEventListener('resize', tick);
    update();
  }

  return {
    // Our door: the hourly test file's ciphertext, unless the visitor's own file is already there.
    door(bytes) {
      if (!mine) drawNoise(door, bytes);
    },
    yours(bytes) {
      mine = true;
      section.querySelector('.locker.centre .label').textContent = t.yours;
      drawNoise(door, bytes);
    },
    // Relabel only while the lockers are out of sight, so nothing changes under the visitor's eyes.
    useData(wall) {
      const items = (wall?.lockers ?? []).filter(validItem);
      if (items.length < MIN_ITEMS || lockers.getBoundingClientRect().top < innerHeight) return;
      applyData(section, items, t);
      if (motion) start(true);
      update();
    },
  };
}
