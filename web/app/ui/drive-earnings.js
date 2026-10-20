// SPDX-License-Identifier: MIT
// Earnings (the owner's "where's my money?"): what people paid to open this drive's pay links, from our
// server's count over every payment (GET /me/sales: the total, each link's take, the newest 50 payments with
// the owner check of ui/sales.js), where that money is, and what moving it out means today.
//
// The money is in stealth outputs to the drive's sales address. Its owner key is derived in this browser from
// the drive's key (lib/ootle.js, label `sales`) and never leaves it; our server holds only the sealed view key,
// which finds and proves payments and can't spend them. No Tari wallet can take that key today: Ootle wallets
// make their accounts from their own seed words, and their key import doesn't make an account that finds or
// spends stealth outputs. So the page says the money stays at this address, and offers no way out that
// doesn't work (docs/review/drive-earnings-activity.md).
import { formatRelative, t } from '../lib/i18n.js';
import { h, icon, init, toast } from './behaviors.js';
import { button, fileIcon, formatTari, itemName } from './drive-parts.js';
import { testnetLine } from './marks.js';
import { fetchSales, itemOf, onSales, salesNow, salesSection } from './sales.js';

const NONE = { received_ut: '0', test_ut: '0', payments: 0, links: 0 };

// The total, as our server counts it, with the part our demo wallet paid told apart.
function summary(drive, s) {
  const total = s?.total ?? NONE;
  if (!total.payments) {
    return h('div', { class: 'empty', 'data-testid': 'earn-empty' }, h('div', { class: 'empty-header' },
      h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('coins')),
      h('h2', { class: 'empty-title' }, t('earn.empty')), h('p', { class: 'empty-description' }, t('earn.empty_d'))));
  }
  const test = BigInt(total.test_ut);
  const wallet = BigInt(total.received_ut) - test;
  const part = (label, variant, ut, testid) => h('li', { 'data-testid': testid },
    h('span', { class: 'badge', 'data-variant': variant }, label), h('b', {}, t('sales.amount', { price: formatTari(ut) })));
  return h('section', { class: 'card', 'aria-labelledby': 'earn-h', 'data-testid': 'earn-total', 'data-received-ut': total.received_ut, 'data-test-ut': total.test_ut },
    h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: 'earn-h' }, t('earn.paid')),
      h('p', { class: 'card-description' }, t('earn.count', { count: total.payments }))),
    h('div', { class: 'card-content earn-body' },
      h('div', { class: 'earn-num', 'data-testid': 'earn-amount' }, formatTari(total.received_ut), h('small', {}, ` ${t('earn.unit')}`)),
      test > 0n ? h('ul', { class: 'legend earn-parts', role: 'list' },
        part(t('rec.test_money'), 'secondary', test, 'earn-test'),
        wallet > 0n ? part(t('earn.wallet'), 'outline', wallet, 'earn-wallet') : null) : null,
      testnetLine(drive.cfg)));
}

// Each paid link: what it took in, when it was last paid, its opens, and the newest payment's tx we know.
function byLink(drive, s) {
  const links = s?.links ?? [];
  if (!links.length) return null;
  const tx = new Map();
  for (const p of s?.paid ?? []) if (p.tx_id && !tx.has(p.share_id)) tx.set(p.share_id, p.tx_id);
  const rows = links.map((l) => {
    const item = itemOf(drive, l.share_id);
    const name = item ? itemName(item) : t('sales.what');
    const amount = t('sales.amount', { price: formatTari(l.received_ut) });
    const last = l.last_at ? formatRelative(l.last_at * 1000) : '';
    const opens = t('earn.opens', { count: l.views_used ?? 0 });
    const id = tx.get(l.share_id);
    const open = item ? () => import('./activity.js').then((m) => m.openActivity(drive, item)) : null;
    return h('tr', { 'data-testid': 'earn-link', 'data-share': l.share_id, 'data-received-ut': l.received_ut, 'data-opens': String(l.views_used ?? 0) },
      h('td', {}, h('div', { class: 'file-name' }, icon(item ? fileIcon(item) : 'coins'),
        h('div', { class: 'file-text' },
          open ? h('button', { class: 'link-btn name', type: 'button', onclick: open }, name) : h('span', { class: 'name' }, name),
          h('span', { class: 'file-meta' }, last ? `${last} · ${opens}` : opens)))),
      h('td', { class: 'num-cell earn-amount' }, amount,
        BigInt(l.test_ut ?? '0') > 0n ? h('span', { class: 'badge', 'data-variant': 'secondary', 'data-testid': 'earn-link-test' }, t('rec.test_money')) : null),
      h('td', { class: 'col-wide num-cell' }, last),
      h('td', { class: 'col-wide num-cell' }, opens),
      h('td', { class: 'col-wide' }, id ? h('a', { class: 'mono tx-link', href: `/verify/tx/${id}`, 'data-testid': 'earn-tx', 'aria-label': `${t('chain.sees')}: ${name}` }, `tx ${id.slice(0, 8)}…`) : null));
  });
  return h('section', { class: 'stack', 'aria-labelledby': 'earn-links-h', 'data-testid': 'earn-links' },
    h('h2', { class: 'h4', id: 'earn-links-h' }, t('earn.links')),
    h('div', { class: 'files', 'data-plain': '' }, h('div', { class: 'table-container' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, h('th', {}, t('earn.link')), h('th', {}, t('earn.received')), h('th', { class: 'col-wide' }, t('earn.last')),
        h('th', { class: 'col-wide' }, t('earn.opens_h')), h('th', { class: 'col-wide' }, h('span', { class: 'sr-only' }, t('earn.tx'))))),
      h('tbody', {}, rows)))));
}

// Where the money is: the sales address this browser derives from the drive's key, with Copy, and what a person
// can do with it today. Shown once the drive has a sales address on our server or has been paid.
function whereCard(drive) {
  const field = h('input', { class: 'input mono', id: 'earn-addr', readonly: true, value: '', placeholder: t('drive.acct.loading'), 'data-testid': 'earn-address' });
  const copy = button(t('drive.copy'), { variant: 'outline', glyph: 'copy', testid: 'earn-copy', disabled: true });
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(field.value);
      toast(t('drive.toast.addr'), { type: 'success' });
    } catch {
      field.select();
      toast(t('error.clipboard'), { type: 'error' });
    }
  });
  const show = (address) => {
    field.value = address;
    copy.disabled = false;
  };
  (async () => {
    const [{ withOotle }, { salesKeys }] = await Promise.all([import('../lib/identity.js'), import('../lib/pay.js')]);
    show((await salesKeys(await withOotle(drive.identity))).address);
  })().catch(() => {
    // No WebAssembly here: the address this drive registered with our server (PUT /me/sales) stands in.
    const known = drive.sales?.seller?.address;
    if (known) show(known);
    else field.placeholder = t('drive.acct.no_wasm');
  });
  return h('section', { class: 'card', 'aria-labelledby': 'earn-where-h', 'data-testid': 'earn-where', hidden: true },
    h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: 'earn-where-h' }, t('earn.where')),
      h('p', { class: 'card-description' }, t('earn.where_d'))),
    h('div', { class: 'card-content stack' },
      h('div', { class: 'stack earn-field' }, h('label', { class: 'label', for: 'earn-addr' }, t('earn.address')), h('div', { class: 'link-row' }, field, copy)),
      h('p', { class: 'small muted' }, t('earn.key')),
      h('div', { class: 'stack earn-move', 'data-testid': 'earn-move' }, h('h3', { class: 'h4' }, t('earn.move_h')), h('p', { class: 'small muted' }, t('earn.move')))));
}

export async function render(drive, page) {
  // The names, rules and files of the paid links come from the index, opened here; the money from our server.
  await Promise.all([drive.ready(), fetchSales(drive)]);
  const top = h('div', { class: 'view' });
  const links = h('div', { class: 'view' });
  const where = whereCard(drive);
  page.replaceChildren(
    h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.earnings'))),
    h('p', { class: 'page-desc' }, t('earn.desc')),
    top, links, salesSection(drive), where);
  const draw = () => {
    const { server } = salesNow();
    top.replaceChildren(summary(drive, server));
    links.replaceChildren(byLink(drive, server) ?? '');
    where.hidden = !(server?.seller || server?.total?.payments);
  };
  draw();
  init(page);
  onSales(drive, page, draw);
}
