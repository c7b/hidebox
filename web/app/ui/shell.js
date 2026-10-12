// SPDX-License-Identifier: MIT
// What every app and viewer page does first: its language, the judge pass carried from /judges, the
// footer's language switch (which here changes the app's language in place), the page title, and on
// app pages the bottom bar of phones (spec §12.2: Locker · Inbox · Send).
import { h } from '../lib/dom.js';
import { LANGUAGES, loadLanguage, pickLanguage, t } from '../lib/i18n.js';
import { setJudgePass } from '../lib/pow.js';
import { idbGet } from '../lib/idb.js';
import { localSet, savedJudgePass } from '../lib/store.js';
import { icon } from './core.js';

const TABS = [['locker', '/locker', 'lock'], ['inbox', '/inbox', 'drop'], ['send', '/send', 'send']];

export async function startPage({ bottomBar = false, current = null } = {}) {
  await loadLanguage(pickLanguage());
  try {
    setJudgePass(savedJudgePass());
  } catch {
    // A malformed stored pass: the anti-bot check stays on.
  }
  for (const a of document.querySelectorAll('a[data-lang]')) {
    a.toggleAttribute('aria-current', a.dataset.lang === document.documentElement.lang);
    a.addEventListener('click', (e) => {
      if (!LANGUAGES.includes(a.dataset.lang)) return;
      e.preventDefault();
      localSet('mutis.lang', a.dataset.lang);
      location.reload();
    });
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
