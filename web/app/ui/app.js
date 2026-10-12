// SPDX-License-Identifier: MIT
// Entry of app.html: one page module per route (spec §3.2), loaded on demand. Links between app
// pages are ordinary links, so the back button, reloads and new tabs behave as everywhere else.
import { h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { current } from '../lib/router.js';
import { errorBanner } from './errors.js';
import { setTitle, startPage } from './shell.js';

const PAGES = {
  locker: () => import('./locker.js').then((m) => m.render),
  inbox: () => import('./inbox.js').then((m) => m.render),
  send: () => import('./send.js').then((m) => m.render),
  watch: () => import('./watch.js').then((m) => m.render),
  upgrade: () => import('./upgrade.js').then((m) => m.render),
  drop: () => import('./droppage.js').then((m) => m.render),
  'verify-tx': () => import('./verify.js').then((m) => m.renderTx),
  verify: () => import('./verify.js').then((m) => m.renderVerify),
};
const TABBED = new Set(['locker', 'inbox', 'send', 'watch', 'upgrade', 'verify', 'verify-tx']);

const route = current();
await startPage({ bottomBar: TABBED.has(route.name), current: route.name });
const main = document.getElementById('main');
const page = PAGES[route.name];
if (!page) {
  setTitle('notfound.h');
  main.replaceChildren(h('div', { class: 'a-notfound' },
    h('p', { class: 'a-scene' }, t('notfound.scene')),
    h('h1', { class: 'a-h1' }, t('notfound.h')),
    h('p', { class: 'a-lede' }, t('notfound.body')),
    h('a', { class: 'a-btn a-btn--primary', href: '/#drop' }, t('notfound.back'))));
} else {
  try {
    await (await page())(main, route.params);
  } catch (e) {
    main.append(errorBanner(e, { action: { label: t('viewer.retry'), onClick: () => location.reload() } }));
  }
}
