// SPDX-License-Identifier: MIT
// How it works (14-ghost-design §7): the caption in the middle of the screen sets the scene; each
// scene's pose is CSS (how.css), and a short WAAPI flourish acts it out. Reduced motion: the poses
// alone, as stills. The ghost is the static partial the build inlined into the stage.
import './site.js';
import { setGhost } from '/shared/ghost.js';

const story = document.getElementById('story');
const ghost = story.querySelector('#gh svg.ghost');
const $ = (s) => story.querySelector(s);
const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const GHOST_FOR = { 1: 'once', 2: 'keep', 6: 'gone', 7: 'gone', 8: 'courier' };

const ease = 'cubic-bezier(.22,1,.36,1)';
const FLOURISH = {
  1: async () => {
    setGhost(ghost, 'catch');
    const n = $('#noteA'); n.style.opacity = 1;
    await n.animate([{ transform: 'translate(-120px, 30px) rotate(-10deg)' }, { transform: 'translate(40px, -60px) rotate(8deg)', offset: .55 }, { transform: 'translate(113px, 38px) scale(.15)' }],
      { duration: 700, easing: 'cubic-bezier(.5,0,.3,1)' }).finished;
    n.style.opacity = '';
    if (current !== 1) return;
    setGhost(ghost, 'busy');
    await new Promise((r) => setTimeout(r, 650));
    if (current === 1) setGhost(ghost, 'once');
  },
  2: () => $('#lock').animate([{ transform: 'translateY(-70px)', opacity: 0 }, { transform: 'translateY(4px)', opacity: 1, offset: .8 }, { transform: 'none' }], { duration: 700, easing: ease }),
  3: () => [...$('#fly').children].forEach((r, i) => {
    $('#fly').style.opacity = 1;
    r.animate([{ transform: 'none', opacity: 1 }, { transform: 'translate(206px, -64px) scale(.8)', opacity: 1, offset: .85 }, { transform: 'translate(212px, -60px) scale(.6)', opacity: 0 }],
      { duration: 900, delay: i * 110, easing: 'cubic-bezier(.5,0,.3,1)', fill: 'backwards' }).finished.then(() => { if (i === 5) $('#fly').style.opacity = ''; });
  }),
  4: () => $('#key').animate([{ transform: 'translate(-176px, -52px)' }, { transform: 'translate(-88px, -110px) rotate(20deg)', offset: .5 }, { transform: 'none' }], { duration: 900, easing: ease }),
  5: () => {
    $('#openB').style.opacity = 1;
    $('#openB').animate([{ transform: 'scale(1)' }, { transform: 'scale(.92)', offset: .4 }, { transform: 'scale(1)', offset: .5 }, { opacity: 0 }], { duration: 900, easing: ease, fill: 'forwards' })
      .finished.then(() => { $('#openB').style.opacity = ''; });
    $('#noteB').animate([{ opacity: 0, transform: 'scale(.6)' }, { opacity: 0, offset: .55 }, { opacity: 1, transform: 'none' }], { duration: 1100, easing: ease });
  },
  6: () => {
    const n = $('#noteB'); n.style.opacity = 1;
    n.animate([{ transform: 'none', opacity: 1 }, { transform: 'translate(0, -30px) scale(1.3)', opacity: 0 }], { duration: 700, easing: ease }).finished.then(() => { n.style.opacity = ''; });
  },
  7: () => $('#receipt').animate([{ transform: 'translateY(-120px)', opacity: 0 }, { transform: 'translateY(6px)', opacity: 1, offset: .75 }, { transform: 'none' }], { duration: 800, easing: ease }),
  8: () => $('#env').animate([{ transform: 'translate(-262px, 84px)' }, { transform: 'translate(-130px, 30px)', offset: .5 }, { transform: 'none' }], { duration: 1200, easing: 'cubic-bezier(.45,0,.2,1)', composite: 'add' }),
};

let current = 0;
function scene(n) {
  if (n === current) return;
  current = n;
  story.dataset.scene = String(n);
  setGhost(ghost, GHOST_FOR[n] || 'ready');
  for (const li of document.querySelectorAll('.captions li')) li.classList.toggle('on', li.dataset.scene === String(n));
  if (!reduce()) FLOURISH[n]?.();
}

const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) scene(Number(e.target.dataset.scene));
}, { rootMargin: '-48% 0px -48% 0px' });
for (const li of document.querySelectorAll('.captions li')) io.observe(li);
scene(1);
