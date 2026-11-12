// SPDX-License-Identifier: MIT
// A shop's page (/shop/<id>#6…, served by shop.html, view.html's twin with the shop's own preview card; docs/shop.md).
// No drive needed and no session sent. In order: the shop's name and bio as its owner wrote them, that its owner
// wrote them, then what sells now, each with its title and line, file or folder, about how big, its price and Buy and
// open, which is the pay link itself (/p/<id>#5…): the shop's key, after this page's #, opens each listing's half of
// its pay link's key here. Then the network line and Report this shop. The owner's words are text, never markup or a
// link, and keep their own line breaks.
import { BRAND, formatBytes, t } from '../lib/i18n.js';
import { ApiError } from '../lib/api.js';
import { h, icon } from './behaviors.js';
import { errorAlert, formatTari } from './drive-parts.js';
import { driveLook, ownDrive } from './folder-view.js';
import { testnetLine } from './marks.js';
import { abuseHref } from './shell.js';

// The currency's name as our server says it (/config pricing.unit), else the copy deck's.
const unitOf = (cfg) => cfg.pricing?.unit || t('earn.unit');

function foot(cfg, shopId) {
  return h('footer', { class: 'shop-foot', 'data-testid': 'shop-foot' }, testnetLine(cfg),
    h('a', { class: 'link-plain small', href: abuseHref(`${location.origin}/shop/${shopId}`), 'data-testid': 'shop-report' }, t('shop.report')));
}

function item(cfg, it, { sizeBucket }) {
  const kind = it.kind === 'folder' ? t('shop.kind_folder') : t('shop.kind_file');
  const price = t('shop.price', { price: formatTari(it.price_ut), unit: unitOf(cfg) });
  return h('li', { class: 'card shop-item', 'data-testid': 'shop-item', 'data-share': it.share_id },
    h('div', { class: 'shop-item-main' },
      h('span', { class: 'shop-item-icon', 'aria-hidden': 'true' }, icon(it.kind === 'folder' ? 'folder' : 'file-lock')),
      h('div', { class: 'shop-item-text' },
        h('h3', { class: 'shop-item-title shop-own-text', 'data-testid': 'shop-item-title' }, it.title),
        it.description ? h('div', { class: 'shop-item-desc shop-own-text', 'data-testid': 'shop-item-desc' }, it.description) : null,
        h('div', { class: 'shop-item-meta', 'data-testid': 'shop-item-meta' }, `${kind} · ${t('buy.about', { size: formatBytes(sizeBucket(it.size_stored)) })}`))),
    h('div', { class: 'shop-item-buy' },
      h('span', { class: 'shop-price', 'data-testid': 'shop-item-price' }, price),
      it.buy
        ? h('a', { class: 'btn', href: it.buy, 'data-testid': 'shop-buy', 'aria-label': t('shop.buy_aria', { title: it.title }) }, icon('coins'), t('shop.buy'))
        : h('p', { class: 'small muted', 'data-testid': 'shop-no-key' }, t('shop.no_key'))));
}

export async function shopPage(root, cfg, shopId) {
  root.setAttribute('data-testid', 'shop-page');
  root.dataset.state = 'loading';
  const [shop, pay] = await Promise.all([import('../lib/shop.js'), import('../lib/pay.js')]);
  const key = shop.parseShopFragment(location.hash);
  const look = async () => {
    await driveLook();
    root.classList.add('shop-main');
  };
  const fatal = async (state, title, body) => {
    await look();
    root.dataset.state = state;
    root.replaceChildren(h('div', { class: 'card fv-card' }, h('div', { class: 'card-header' },
      h('h1', { class: 'card-title h3', tabindex: '-1' }, title), body ? h('p', { class: 'card-description' }, body) : null),
    h('div', { class: 'card-footer' }, ownDrive())));
  };
  if (!key) return fatal('incomplete', t('gone.nokey'), t('gone.nokey_body'));
  let page;
  try {
    page = await shop.openShopPage(shopId, key, location.origin);   // each Buy link on this page's own origin
  } catch (e) {
    if (e instanceof ApiError && e.code === 'not_found') return fatal('closed', t('shop.closed'), t('shop.closed_d'));
    if (e instanceof ApiError && e.code === 'gone') return fatal('removed', t('shop.removed'), t('shop.removed_d'));
    await look();
    root.dataset.state = 'error';
    return root.replaceChildren(errorAlert(e, { action: { label: t('viewer.retry'), onClick: () => location.reload() } }));
  }
  await look();
  document.title = `${page.title} · ${BRAND}`;
  const items = page.items ?? [];
  const head = h('header', { class: 'shop-head' },
    h('span', { class: 'badge', 'data-variant': 'secondary' }, icon('store'), t('shop.label')),
    h('h1', { class: 'h1 shop-own-text', tabindex: '-1', 'data-testid': 'shop-title' }, page.title),
    page.bio ? h('div', { class: 'shop-bio shop-own-text', 'data-testid': 'shop-bio' }, page.bio) : null,
    h('p', { class: 'small muted', 'data-testid': 'shop-owner-note' }, t('shop.owner_wrote')));
  const list = items.length
    ? h('section', { class: 'shop-list', 'aria-labelledby': 'shop-list-h' },
      h('h2', { class: 'h4', id: 'shop-list-h' }, t('shop.count', { count: items.length })),
      h('p', { class: 'small muted' }, t('shop.how')),
      h('ul', { class: 'shop-items', role: 'list' }, items.map((it) => item(cfg, it, pay))))
    : h('div', { class: 'empty', 'data-testid': 'shop-empty' }, h('div', { class: 'empty-header' },
      h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('store')),
      h('h2', { class: 'empty-title' }, t('shop.empty')), h('p', { class: 'empty-description' }, t('shop.empty_d'))));
  root.dataset.state = items.length ? 'ready' : 'empty';
  root.replaceChildren(h('div', { class: 'shop' }, head, list, foot(cfg, shopId)));
}
