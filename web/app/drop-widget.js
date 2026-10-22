// SPDX-License-Identifier: MIT
// The home page's drop widget (spec §3.4.4; 16-drive-design §11, "Just share one thing"): mounts into
// #mutis-drop, and shows where to start when the page is reached at #share. A page with a figure (#drop) hands
// it over: the figure picks a file, the whole window takes a drop, and the page's phase (body[data-phase])
// follows the widget. The widget owns its stylesheet, strings, live region and events.
import { setJudgePass } from './lib/pow.js';
import { savedJudgePass } from './lib/store.js';
import { stylesheet, widgetStrings } from './ui/more.js';
import { mountWidget } from './ui/widget.js';

const root = document.getElementById('mutis-drop');
if (root) {
  await Promise.all([stylesheet('/app/css/widget.css'), widgetStrings()]);
  try {
    setJudgePass(savedJudgePass());
  } catch {
    // A malformed stored pass: the anti-bot check stays on.
  }
  // A page with a figure (#drop) lets the whole window take a drop; the drive's home seats the zone in a card.
  const figure = document.getElementById('drop');
  await mountWidget(root, { variant: root.dataset.variant || 'hero', windowDrops: Boolean(figure), figure });
  // share-simple: arriving at #share (a link from another page, the link page's Make your own secret, a link on
  // this one), the box shows where to start: it comes fully under the sticky header, its ring breathes in lime
  // (home.css .share-glow) and settles, and its first button takes the focus. The first use of the box ends it.
  const arrive = () => {
    root.classList.remove('share-glow');
    if (location.hash !== '#share') return;
    void root.offsetWidth;   // a second arrival breathes again
    root.classList.add('share-glow');
    const box = root.querySelector('.md-zone, .md-card') ?? root;
    const r = box.getBoundingClientRect();
    const room = r.top - (document.querySelector('.site-header')?.getBoundingClientRect().bottom ?? 0) - 16;
    const over = r.bottom - (innerHeight - 16);
    if (room < 0 || over > 0) scrollBy({ top: room < 0 ? room : Math.min(over, room), behavior: 'instant' });
    const first = root.querySelector('.md-stage .a-btn--primary');
    (first?.querySelector('input') ?? first)?.focus({ preventScroll: true });
  };
  arrive();
  addEventListener('hashchange', arrive);
  document.addEventListener('click', (e) => {   // #share again while it is the fragment: no hashchange
    if (location.hash === '#share' && e.target.closest?.('a[href="#share"], a[href="/#share"]')) requestAnimationFrame(arrive);
  });
  document.addEventListener('mutis:state', (e) => e.detail?.state !== 'idle' && root.classList.remove('share-glow'));
}
