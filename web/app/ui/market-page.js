// SPDX-License-Identifier: MIT
// The market (/market, served by shop.html with the market's own title and description filled in by our server;
// docs/market.md): what public shops sell, newest first, searchable by words, files or folders. Each listing has its
// title and line as its seller wrote them, file or folder, about how big, its price, its shop, and Ask for it
// (ui/market-ask.js). This browser's open asks come first; a link with an ask's secret after the # (#8…) brings that
// ask back on any device. No drive and no session needed. Sellers' words are text, never markup or a link.
import { BRAND, formatBytes, t } from '../lib/i18n.js';
import { h, icon } from './behaviors.js';
import { errorAlert, formatTari } from './drive-parts.js';
import { driveLook } from './folder-view.js';
import { testnetLine } from './marks.js';
import { askSlot, askStatus } from './market-ask.js';

const unitOf = (cfg) => cfg.pricing?.unit || t('earn.unit');

function card(cfg, it, sizeBucket) {
  const kind = it.kind === 'folder' ? t('shop.kind_folder') : t('shop.kind_file');
  const price = t('shop.price', { price: formatTari(it.price_ut), unit: unitOf(cfg) });
  return h('li', { class: 'card shop-item market-item', 'data-testid': 'market-item', 'data-share': it.share_id },
    h('div', { class: 'shop-item-main' },
      h('span', { class: 'shop-item-icon', 'aria-hidden': 'true' }, icon(it.kind === 'folder' ? 'folder' : 'file-lock')),
      h('div', { class: 'shop-item-text' },
        h('h3', { class: 'shop-item-title shop-own-text', 'data-testid': 'market-item-title' }, it.title),
        it.description ? h('div', { class: 'shop-item-desc shop-own-text' }, it.description) : null,
        h('div', { class: 'shop-item-meta' }, `${kind} · ${t('buy.about', { size: formatBytes(sizeBucket(it.size_stored)) })} · `,
          h('a', { class: 'link-plain shop-own-text', href: it.shop.path, 'data-testid': 'market-item-shop' }, t('market.by', { shop: it.shop.title }))))),
    h('div', { class: 'shop-item-buy market-item-buy' },
      h('span', { class: 'shop-price', 'data-testid': 'market-item-price' }, price), askSlot(cfg, it)));
}

function searchForm(onSearch) {
  const input = h('input', { class: 'input', id: 'market-q', type: 'search', name: 'q', maxlength: '60', autocomplete: 'off',
    'aria-label': t('market.search_label'), 'data-testid': 'market-q' });
  const kinds = [['', 'market.kind_all'], ['file', 'market.kind_file'], ['folder', 'market.kind_folder']];
  const select = h('select', { class: 'input market-kind', 'aria-label': t('market.kind_all'), 'data-testid': 'market-kind' },
    kinds.map(([v, k]) => h('option', { value: v }, t(k))));
  const form = h('form', { class: 'market-search', role: 'search', 'data-testid': 'market-search' }, input, select,
    h('button', { class: 'btn', type: 'submit', 'data-testid': 'market-search-go' }, icon('search'), t('market.search')));
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    onSearch({ q: input.value.trim(), kind: select.value });
  });
  select.addEventListener('change', () => onSearch({ q: input.value.trim(), kind: select.value }));
  return form;
}

export async function marketPage(root, cfg) {
  root.setAttribute('data-testid', 'market-page');
  root.dataset.state = 'loading';
  const [market, pay] = await Promise.all([import('../lib/market.js'), import('../lib/pay.js')]);
  await driveLook();
  root.classList.add('shop-main');
  document.title = `${t('market.h')} · ${BRAND}`;

  // An ask brought back with its secret after the # (from "Link to come back"): kept here too, then shown first.
  const secret = market.parseAskFragment(location.hash);
  if (secret) {
    const { b64uEncode } = await import('../lib/b64.js');
    const parts = await market.askParts(secret);
    if (!market.savedAsks().some((a) => a.askId === parts.askId)) {
      try {
        const st = await (await import('../lib/api.js')).request('GET', `/market/asks/${parts.askId}`,
          { headers: { 'X-Mutis-Ask': b64uEncode(parts.token) } });
        market.keepAsk({ s: b64uEncode(secret), askId: parts.askId, shareId: st.share_id, shop: null, title: null, priceUt: null,
          at: Math.floor(Date.now() / 1000) });
      } catch {
        // ended, or not an ask: the page says nothing of it
      }
    }
    history.replaceState(null, '', location.pathname);     // the secret leaves the address bar
  }

  const head = h('header', { class: 'shop-head' },
    h('span', { class: 'badge', 'data-variant': 'secondary' }, icon('store'), t('market.page_title')),
    h('h1', { class: 'h1', tabindex: '-1', 'data-testid': 'market-title' }, t('market.h')),
    h('p', { class: 'shop-bio' }, t('market.desc')),
    h('p', { class: 'small muted' }, t('market.owner_wrote')));
  const mine = market.savedAsks();
  const asks = mine.length
    ? h('section', { class: 'shop-list', 'aria-labelledby': 'market-asks-h', 'data-testid': 'market-asks' },
      h('h2', { class: 'h4', id: 'market-asks-h' }, t('market.your_asks')),
      h('ul', { class: 'shop-items', role: 'list' }, mine.map((a) => h('li', { class: 'card shop-item' },
        h('div', { class: 'shop-item-text' }, h('h3', { class: 'shop-item-title shop-own-text' }, a.title || t('market.your_asks')),
          a.shop ? h('a', { class: 'link-plain small', href: a.shop }, a.shop) : null),
        h('div', { class: 'shop-item-buy' }, askStatus(cfg, a, null))))))
    : null;
  const list = h('ul', { class: 'shop-items', role: 'list', 'data-testid': 'market-items' });
  const status = h('div', { 'aria-live': 'polite' });
  const more = h('button', { class: 'btn', 'data-variant': 'outline', type: 'button', hidden: true, 'data-testid': 'market-more' }, t('market.more'));
  let query = { q: '', kind: '' };
  let next = null;

  const load = async (append) => {
    more.disabled = true;
    try {
      const page = await market.browse({ ...query, cursor: append ? next : '' });
      next = page.next;
      const cards = page.items.map((it) => card(cfg, it, pay.sizeBucket));
      if (append) list.append(...cards);
      else list.replaceChildren(...cards);
      const none = !list.children.length;
      status.replaceChildren(none ? h('div', { class: 'empty', 'data-testid': 'market-empty' }, h('div', { class: 'empty-header' },
        h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('store')),
        h('h2', { class: 'empty-title' }, t(query.q || query.kind ? 'market.none' : 'market.empty')),
        query.q || query.kind ? null : h('p', { class: 'empty-description' }, t('market.empty_d')))) : '');
      more.hidden = !next;
      root.dataset.state = none ? 'empty' : 'ready';
    } catch (e) {
      root.dataset.state = 'error';
      status.replaceChildren(errorAlert(e, { action: { label: t('viewer.retry'), onClick: () => load(false) } }));
    } finally {
      more.disabled = false;
    }
  };
  more.addEventListener('click', () => load(true));
  const form = searchForm((q) => {
    query = q;
    load(false);
  });
  // The first page of listings comes before the page is drawn: what our server wrote stays on screen until then
  // (shop_page.py writes this same markup), and the list is never seen empty while it loads.
  await load(false);
  root.replaceChildren(h('div', { class: 'shop market' }, head, asks,
    h('section', { class: 'shop-list', 'aria-label': t('market.h') }, form, list, status, more),
    h('footer', { class: 'shop-foot' }, testnetLine(cfg))));
}
