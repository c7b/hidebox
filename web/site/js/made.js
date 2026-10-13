// SPDX-License-Identifier: MIT
// How it was made: the live parts of "Check us" (14-ghost-design §8). The status line from
// /status.json, our own test transactions from /evidence.json, and the hourly test file you can try
// to read (and, once it is a day old, open with its published key). Each loads when it comes near;
// a failed request leaves its block hidden. Numbers and copy variants come from site.js.
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
