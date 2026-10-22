// SPDX-License-Identifier: MIT
// The home reached at #share (share-simple; drop-widget.js loads this only for that fragment): the share box comes
// fully under the sticky header, takes .share-glow (home.css: a lime ring that breathes three times and settles,
// still with reduced motion) and its first button (Choose a file) takes the focus. Writing or dropping ends it; #share
// again, even from a link on the page while it is the fragment, breathes again.
let wired = false;

export function arrive(root) {
  if (!wired) {
    wired = true;
    document.addEventListener('click', (e) => {   // the same fragment again: no hashchange
      if (location.hash === '#share' && e.target.closest?.('a[href$="#share"]')) requestAnimationFrame(() => arrive(root));
    });
    document.addEventListener('mutis:state', (e) => e.detail?.state !== 'idle' && root.classList.remove('share-glow'));
  }
  root.classList.remove('share-glow');
  if (location.hash !== '#share') return;
  void root.offsetWidth;   // a second arrival breathes again
  root.classList.add('share-glow');
  const r = (root.querySelector('.md-zone, .md-card') ?? root).getBoundingClientRect();
  const room = r.top - (document.querySelector('.site-header')?.getBoundingClientRect().bottom ?? 0) - 16;
  const over = r.bottom - innerHeight + 16;
  if (room < 0 || over > 0) scrollBy({ top: room < 0 ? room : Math.min(over, room), behavior: 'instant' });
  const first = root.querySelector('.md-stage .a-btn--primary');
  (first?.querySelector('input') ?? first)?.focus({ preventScroll: true });
}
