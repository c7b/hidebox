// SPDX-License-Identifier: MIT
// The seller's side of pay to open in the drive (16-drive-design §4, 16-drive-architecture §1.9), lane
// app2: the owner check, run once each time a selling drive opens, and the Payments list in Received.
// Each payment to the drive's sales address is checked here, in this browser: the one-time key on the
// chain must be the one this drive's sales owner key derives, or the payer kept control of the money.
// Our server waits for this check before it releases the key to a buyer who paid from their own wallet.
import { formatRelative, t } from '../lib/i18n.js';
import { h, icon } from './behaviors.js';
import { formatTari, itemName } from './drive-parts.js';

const listeners = new Set();
let running = null;
let last = null;
let timer = null;

const sells = (drive) => [...drive.index.items.values()].some((x) => (x.row.shares ?? []).some((s) => s.mode === 'pay' || s.paid));
const visible = () => document.visibilityState === 'visible';

// One pass at a time: a no-op for a drive that never sold from here and has no paid link. Fifth pass: it
// runs again every minute while the drive is open and visible, and when the tab comes back (Received asks
// every 20 seconds), so a payment shows up and a buyer's claim is answered without a reload.
export function startOwnerCheck(drive) {
  if (!timer) {
    timer = setInterval(() => visible() && startOwnerCheck(drive), 60000);
    document.addEventListener('visibilitychange', () => visible() && startOwnerCheck(drive));
  }
  running ??= (async () => {
    const pay = await import('../lib/pay.js');
    const state = await pay.salesState(drive.identity);
    if (!state.registered && !sells(drive)) return state;
    if (!last) {
      last = state;
      emit();
    }
    last = await pay.checkSales(drive.identity, drive.cfg, drive.headers(), { onOutput: () => emit() });
    emit();
    return last;
  })().catch(() => last).finally(() => { running = null; });
  return running;
}

function emit() {
  for (const fn of listeners) fn(last);
}

const badge = (o) => {
  if (o.check === 'ok') return h('span', { class: 'badge', 'data-variant': 'success', 'data-check': 'ok' }, icon('shield-check'), t('sales.ok'));
  if (o.check === 'bad') return h('span', { class: 'badge', 'data-variant': 'destructive', 'data-check': 'bad' }, icon('triangle-alert'), t('sales.bad'));
  return h('span', { class: 'badge', 'data-variant': 'outline', 'data-check': 'waiting' }, t('sales.checking'));
};

// The name of the file or folder a paid link shares, decrypted in this browser (null when it's gone).
function nameOf(drive, shareId) {
  if (!shareId) return null;
  for (const x of drive.index.items.values()) if ((x.row.shares ?? []).some((s) => s.share_id === shareId || s.id === shareId)) return itemName(x);
  return null;
}

// Received's Payments: every payment to this drive's paid links, newest first: which link, Test money,
// checked on the chain, the tx, and the owner check. Hidden while there are none.
export function salesSection(drive) {
  const body = h('tbody', {});
  const el = h('section', { class: 'stack', 'aria-labelledby': 'sales-h', 'data-testid': 'sales-root', hidden: true },
    h('h2', { class: 'h4', id: 'sales-h' }, t('sales.h')),
    h('p', { class: 'small muted' }, t('sales.d')),
    h('div', { class: 'files', 'data-plain': '' }, h('div', { class: 'table-container' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, h('th', {}, t('rec.what')), h('th', {}, t('sales.price')), h('th', { class: 'col-wide' }, t('rec.when')), h('th', {}, t('sales.check')))),
      body))));
  const draw = (state) => {
    if (!el.isConnected && state) return listeners.delete(draw);
    const local = new Map((state?.outputs ?? []).map((o) => [o.utxoId, o]));
    // Our server's list when we have it (any device); else what this browser's walk found.
    const rows = state?.paid
      ? state.paid.map((p) => ({ utxoId: p.utxo_id, shareId: p.share_id, value: p.value_ut, at: p.seen_at, demo: p.demo,
        chain: p.checked, tx: p.tx_id, check: p.owner_ok === false ? 'bad' : (p.owner_ok || p.demo) ? 'ok' : local.get(p.utxo_id)?.check ?? null }))
      : (state?.outputs ?? []).filter((o) => o.claimId).slice().sort((a, b) => (b.seq ?? 0) - (a.seq ?? 0))
        .map((o) => ({ utxoId: o.utxoId, value: o.value, at: null, check: o.check }));
    el.hidden = !rows.length;
    body.replaceChildren(...rows.map((o) => h('tr', { 'data-testid': 'sales-row', 'data-utxo': o.utxoId, 'data-check': o.check ?? 'waiting', 'data-demo': o.demo ? 'true' : null },
      h('td', {}, h('div', { class: 'file-name' }, icon('coins'), h('span', { class: 'name' }, nameOf(drive, o.shareId) ?? t('sales.what'))),
        h('div', { class: 'row wrap small muted' },
          o.demo ? h('span', { class: 'badge', 'data-variant': 'secondary', 'data-testid': 'sales-test' }, t('rec.test_money')) : null,
          o.chain ? h('span', { class: 'badge', 'data-variant': 'outline', 'data-testid': 'sales-checked' }, icon('check'), t('sales.checked')) : null,
          o.tx ? h('a', { class: 'mono tx-link', href: `/verify/tx/${o.tx}`, 'data-testid': 'sales-tx', 'aria-label': t('chain.sees') }, `tx ${o.tx.slice(0, 8)}…`) : null)),
      h('td', { class: 'num-cell' }, t('sales.amount', { price: formatTari(o.value) })),
      h('td', { class: 'col-wide num-cell' }, o.at ? formatRelative(o.at * 1000) : ''),
      h('td', {}, badge(o)))));
  };
  listeners.add(draw);
  draw(last);
  startOwnerCheck(drive);
  const poll = setInterval(() => (el.isConnected ? visible() && startOwnerCheck(drive) : clearInterval(poll)), 20000);
  return el;
}
