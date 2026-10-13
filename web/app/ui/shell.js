// SPDX-License-Identifier: MIT
// What every app and viewer page does first: its strings, the judge pass carried from /judges, the
// page title, and on app pages the bottom bar of phones (spec §12.2: Locker · Inbox · Send).
import { h } from '../lib/dom.js';
import { loadStrings, t } from '../lib/i18n.js';
import { setJudgePass } from '../lib/pow.js';
import { idbGet } from '../lib/idb.js';
import { savedJudgePass } from '../lib/store.js';
import { icon } from './core.js';

const TABS = [['locker', '/locker', 'lock'], ['inbox', '/inbox', 'drop'], ['send', '/send', 'send']];

export async function startPage({ bottomBar = false, current = null } = {}) {
  await loadStrings();
  try {
    setJudgePass(savedJudgePass());
  } catch {
    // A malformed stored pass: the anti-bot check stays on.
  }
  const skip = document.querySelector('.skip-link');
  if (skip) skip.textContent = t('nav.skip');
  // A browser that holds a locker is offered its locker, not a new one.
  idbGet('identity', 'current').then((rec) => {
    if (rec) for (const a of document.querySelectorAll('.nav-cta')) a.textContent = t('nav.my_locker');
  }, () => null);
  if (bottomBar) {
    document.body.append(h('nav', { class: 'a-bottom', 'aria-label': t('nav.app') },
      TABS.map(([name, href, glyph]) => h('a', { href, 'aria-current': name === current ? 'page' : null },
        icon(glyph, 'a-bottom-icon'), h('span', {}, t(`nav.${name}`))))));
  }
}

// The report form, filled in with a link (never its key) when the page has one.
export const abuseHref = (link) => (link ? `/abuse#link=${encodeURIComponent(link)}` : '/abuse');

export function setTitle(key, params) {
  document.title = `${t(key, params)} · mutis`;
}
