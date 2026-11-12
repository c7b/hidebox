// SPDX-License-Identifier: MIT
// Ask for it (docs/market.md): what a shopper without a shop's whole link gets beside each listing, on a public shop's
// page and in the market. It asks the seller's drive for the listing's key half (lib/market.js), then says where the
// ask stands: waiting (checked again every 15 seconds while the page is in view, with a link to come back), answered
// (Go to pay, the pay link itself), ended, or an answer that didn't check out (never followed). Nobody pays before the
// answer has come.
import { t } from '../lib/i18n.js';
import { ApiError } from '../lib/api.js';
import { forgetAsk, savedAskFor } from '../lib/asks.js';
import { h, icon } from './behaviors.js';

const POLL_MS = 15000;
const visible = () => document.visibilityState === 'visible';
// The page's own origin (a link's host is never an answer's to choose); /config's only outside a page.
const origin = (cfg) => globalThis.location?.origin ?? cfg.origin;

// The link that brings this ask back on any device: the market page with the ask's secret after the #.
export const comeBackUrl = async (cfg, entry) => `${origin(cfg)}/market#${(await import('../lib/market.js')).askFragment(
  (await import('../lib/b64.js')).b64uDecode(entry.s))}`;

function stateBox(kind, title, body, actions = []) {
  return h('div', { class: 'market-ask', 'data-testid': 'market-ask', 'data-state': kind, role: 'status' },
    h('p', { class: 'market-ask-title' }, icon(kind === 'answered' ? 'circle-check' : kind === 'waiting' ? 'clock' : 'triangle-alert'), title),
    body ? h('p', { class: 'small muted' }, body) : null, actions.length ? h('div', { class: 'row market-ask-actions' }, actions) : null);
}

// The ask's own block, for an entry this browser keeps (lib/market.js savedAsks); `again()` asks once more.
export function askStatus(cfg, entry, again) {
  const root = h('div', { class: 'market-ask-slot' });
  let timer = null;
  const stop = () => { if (timer) clearInterval(timer); timer = null; };
  const draw = async () => {
    const market = await import('../lib/market.js');
    let st;
    try {
      st = await market.askState(entry, origin(cfg));
    } catch {
      return;                                  // offline for a moment: the next round tries again
    }
    if (!root.isConnected && timer) return stop();
    if (st.state === 'answered') {
      stop();
      root.replaceChildren(stateBox('answered', t('market.answered_h'), t('market.answered_d'),
        [h('a', { class: 'btn', href: st.buy, 'data-testid': 'market-go-pay' }, icon('coins'), t('market.go_pay'))]));
    } else if (st.state === 'waiting') {
      const link = await comeBackUrl(cfg, entry);
      root.replaceChildren(stateBox('waiting', t('market.waiting_h'), t('market.waiting_d'), [
        h('a', { class: 'btn', 'data-variant': 'outline', href: link, 'data-testid': 'market-come-back' }, icon('link'), t('market.come_back')),
        h('button', { class: 'btn', 'data-variant': 'ghost', type: 'button', 'data-testid': 'market-check', onclick: () => draw() }, t('market.check'))]));
      timer ??= setInterval(() => visible() && draw(), POLL_MS);
    } else {
      stop();
      forgetAsk(entry.askId);
      const ended = st.state === 'ended';
      root.replaceChildren(stateBox(st.state, t(ended ? 'market.ended_h' : 'market.bad_h'),
        t(ended ? 'market.ended_d' : 'market.bad_d', { days: cfg.market?.ask_days ?? 7 }),
        again ? [h('button', { class: 'btn', 'data-variant': 'outline', type: 'button', 'data-testid': 'market-ask-again', onclick: again }, t('market.ask_again'))] : []));
    }
  };
  draw();
  return root;
}

// Beside a listing: this browser's ask for it, or Ask for it. `listing` as GET /market or GET /shop/{ref} gives it,
// with `shop` ({path}) when known.
export function askSlot(cfg, listing) {
  const slot = h('div', { class: 'market-ask-slot', 'data-testid': 'market-slot' });
  const fresh = () => {
    const errors = h('p', { class: 'small field-error', role: 'alert', hidden: true });
    const go = h('button', { class: 'btn', type: 'button', 'data-testid': 'market-ask-go', 'aria-label': t('shop.ask_aria', { title: listing.title }) },
      icon('key-round'), t('shop.ask'));
    go.addEventListener('click', async () => {
      go.disabled = true;
      go.lastChild.textContent = t('market.asking');
      try {
        const market = await import('../lib/market.js');
        const entry = await market.ask(listing);
        slot.replaceChildren(askStatus(cfg, entry, () => slot.replaceChildren(fresh())));
      } catch (e) {
        go.disabled = false;
        go.lastChild.textContent = t('shop.ask');
        errors.hidden = false;
        errors.textContent = e instanceof ApiError && e.code === 'asks_full' ? t('market.full') : (e?.message || t('drive.oops'));
      }
    });
    return h('div', { class: 'stack-sm' }, go, errors);
  };
  const saved = savedAskFor(listing.share_id);
  slot.replaceChildren(saved ? askStatus(cfg, saved, () => slot.replaceChildren(fresh())) : fresh());
  return slot;
}
