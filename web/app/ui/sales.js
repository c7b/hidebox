// SPDX-License-Identifier: MIT
// The seller's side of pay to open in the drive (16-drive-design §4, 16-drive-architecture §1.9), lane
// app2: the owner check, run once each time a selling drive opens, and the Payments list in Received.
// Each payment to the drive's sales address is checked here, in this browser: the one-time key on the
// chain must be the one this drive's sales owner key derives, or the payer kept control of the money.
// Our server waits for this check before it releases the key to a buyer who paid from their own wallet.
import { formatRelative, t } from '../lib/i18n.js';
import { h, icon } from './behaviors.js';
import { formatTari } from './drive-parts.js';

const listeners = new Set();
let running = null;
let last = null;

const sells = (drive) => [...drive.index.items.values()].some((x) => (x.row.shares ?? []).some((s) => s.mode === 'pay' || s.paid));

// Once per page: a no-op for a drive that never sold from here and has no paid link.
export function startOwnerCheck(drive) {
  running ??= (async () => {
    const pay = await import('../lib/pay.js');
    const state = await pay.salesState(drive.identity);
    if (!state.registered && !sells(drive)) return state;
    last = state;
    emit();
    last = await pay.checkSales(drive.identity, drive.cfg, drive.headers(), { onOutput: () => emit() });
    emit();
    return last;
  })().catch(() => { running = null; return last; });
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

// Received's Payments: every payment the owner check found, newest first. Hidden while there are none.
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
    const outputs = (state?.outputs ?? []).filter((o) => o.claimId).slice().sort((a, b) => (b.seq ?? 0) - (a.seq ?? 0));
    el.hidden = !outputs.length;
    body.replaceChildren(...outputs.map((o) => h('tr', { 'data-testid': 'sales-row', 'data-utxo': o.utxoId, 'data-check': o.check ?? 'waiting' },
      h('td', {}, h('div', { class: 'file-name' }, icon('coins'), h('span', { class: 'name' }, t('sales.what')))),
      h('td', { class: 'num-cell' }, t('sales.amount', { price: formatTari(o.value) })),
      h('td', { class: 'col-wide num-cell' }, o.at ? formatRelative(o.at * 1000) : ''),
      h('td', {}, badge(o)))));
  };
  listeners.add(draw);
  draw(last);
  startOwnerCheck(drive);
  return el;
}
