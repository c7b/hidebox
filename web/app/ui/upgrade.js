// SPDX-License-Identifier: MIT
// /upgrade (spec §12.3.3, §10.5): the free share of the disk, the packs, and an invoice paid in tTARI.
// A payment counts only after the chain checks of this deployment's mode (amount_proof): the stepper
// names exactly the checks that run, never more. Purple marks the buttons that move tTARI.
import { h } from '../lib/dom.js';
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { config, getStats } from '../lib/api.js';
import { copyButton, formatDuration, icon } from './core.js';
import { formatTari, testnetLine } from './marks.js';
import { errorBanner } from './errors.js';
import { NeedsWasm, openLocker, storedLocker, wasmOk } from './locker-ctx.js';
import { maybeAskForKey } from './keyflow.js';
import { setTitle } from './shell.js';

// The four steps and when each one is reached, per proof mode. A new invoice has no payments yet.
function steps(proof) {
  const pays = (inv) => inv.payments ?? [];
  const seen = (inv) => pays(inv).length > 0 || ['seen', 'credited', 'underpaid'].includes(inv.status);
  const added = (inv) => inv.status === 'credited';
  if (proof === 'wallet') {
    return [['waiting', () => true], ['seen_wallet', seen],
      ['exists', (inv) => added(inv) || pays(inv).some((p) => p.checks.committed_on_chain)], ['added', added]];
  }
  return [['waiting', () => true], ['seen', seen],
    ['proven', (inv) => added(inv) || pays(inv).some((p) => p.checks.amount_proven)], ['added', added]];
}

export async function render(main) {
  setTitle('upgrade.title');
  const cfg = await config();
  const root = h('div', { class: 'a-upgrade' });
  main.replaceChildren(h('h1', { class: 'a-h1' }, t('upgrade.h')), h('p', { class: 'a-lede' }, t('upgrade.lede')), root);
  if (!(await wasmOk())) return root.replaceChildren(errorBanner(new NeedsWasm()));
  const mine = await storedLocker();
  const free = h('p', { class: 'a-plan-price' });
  (mine ? openLocker().then((c) => c.me.quota.free_bytes) : getStats().then((s) => s.free_quota_bytes))
    .then((bytes) => { free.textContent = t('upgrade.free_now', { free_each: formatBytes(bytes) }); }, () => free.remove());
  const invoiceSlot = h('div', { 'aria-live': 'polite' });
  root.replaceChildren(
    h('div', { class: 'a-plans' },
      h('section', { class: 'a-plan' },
        h('h2', { class: 'a-card-h' }, t('upgrade.free')), free,
        h('p', {}, t('upgrade.free_body')),
        h('a', { href: '/pricing', class: 'a-more' }, t('upgrade.why'), icon('arrow'))),
      ...cfg.pricing.packs.map((pack) => h('section', { class: 'a-plan' },
        h('h2', { class: 'a-card-h' }, t('upgrade.pack', { bytes: formatBytes(pack.bytes), dur: formatDuration(pack.days * 86400) })),
        h('p', { class: 'a-plan-price a-pay-text' }, t('upgrade.price', { price: formatTari(pack.price_ut) })),
        h('button', { type: 'button', class: 'a-btn', 'data-testid': `pack-${pack.id}`, onclick: () => buy(pack) }, t('upgrade.buy'))))),
    invoiceSlot,
    testnetLine(cfg));

  async function buy(pack) {
    invoiceSlot.replaceChildren(h('p', { class: 'a-working mono' }, t(mine ? 'upgrade.making' : 'locker.opening')));
    try {
      const ctx = await openLocker();
      const { createInvoice } = await import('../lib/api-locker.js');
      showInvoice(ctx, await createInvoice(pack.id, ctx.headers()), pack);
    } catch (e) {
      invoiceSlot.replaceChildren(errorBanner(e));
    }
  }

  function showInvoice(ctx, invoice, pack) {
    const direct = cfg.send_mode === 'direct' && cfg.features?.direct_send;
    const list = steps(cfg.amount_proof);
    const status = h('p', { class: 'a-invoice-status', 'data-testid': 'invoice-status', 'data-status': invoice.status });
    const stepper = h('ol', { class: 'a-steps a-paysteps' });
    const errors = h('div', {});
    const buttons = [];
    function payButton(testid, label, run) {
      const b = h('button', { type: 'button', class: 'a-btn a-btn--pay', 'data-testid': testid }, label);
      b.addEventListener('click', async () => {
        b.disabled = true;
        errors.replaceChildren();
        try {
          await run(await import('../lib/wallet.js'));
        } catch (e) {
          b.disabled = false;
          errors.replaceChildren(errorBanner(e));
        }
      });
      buttons.push(b);
      return b;
    }
    const demo = () => payButton('demo-pay', t('upgrade.pay_demo'), (w) => w.demoPayInvoice(invoice.invoice_id));
    const pay = direct
      ? payButton('pay-browser', t('upgrade.pay_browser', { price: formatTari(invoice.amount_ut) }), (w) => w.payInvoice(ctx.identity, invoice))
      : cfg.features?.demo_pay ? demo() : null;
    const row = h('div', { class: 'a-row' }, copyButton({ label: t('upgrade.copy_address'), getText: () => invoice.address }), pay);
    // Direct mode: when the browser's wallet is short of the price (its grant is on the way, or there is
    // none today), our demo wallet can pay instead.
    const short = h('p', { class: 'a-caption', 'data-testid': 'pay-short', hidden: true });
    if (direct && cfg.features?.demo_pay) {
      import('../lib/wallet.js')
        .then((w) => w.ensureGrant(ctx.identity, cfg, { need: BigInt(invoice.amount_ut) + w.FEE_UT }))
        .then((grant) => {
          if (!grant || grant === 'funded' || status.dataset.status === 'credited') return;
          short.textContent = t(`upgrade.short_${grant}`);
          short.hidden = false;
          row.append(demo());
        }, () => null);
    }

    function draw(inv) {
      status.dataset.status = inv.status;
      status.textContent = t(`upgrade.status.${inv.status}`, {
        x: formatTari(inv.received_ut ?? '0'), y: formatTari(inv.amount_ut), z: formatTari(BigInt(inv.amount_ut) - BigInt(inv.received_ut ?? '0')),
        underpaid_days: cfg.invoices.underpaid_grace_days,
      });
      const reached = list.map(([, done]) => done(inv));
      stepper.replaceChildren(...list.map(([name], i) => h('li', {
        class: ['a-step', reached[i] && 'a-step--done', reached[i] && i >= 2 && 'a-step--chain'],
        'data-testid': 'pay-step', 'data-step': name, 'data-done': String(reached[i]),
        'aria-current': reached[i] && !reached[i + 1] ? 'step' : null,
      }, reached[i] ? icon('check') : null, h('span', {}, t(`upgrade.step.${name}`)))));
      if (inv.status === 'credited') {
        for (const b of buttons) b.remove();
        short.remove();
        stepper.after(h('p', { class: 'a-done' }, t('upgrade.added', { bytes: formatBytes(inv.credited?.bytes ?? pack.bytes), date: formatDate((inv.credited?.until ?? 0) * 1000, { dateStyle: 'medium' }) })));
        maybeAskForKey(ctx.identity);
      }
    }

    invoiceSlot.replaceChildren(h('section', { class: 'a-invoice', 'aria-labelledby': 'a-inv-h' },
      h('h2', { id: 'a-inv-h', class: 'a-h2' }, t('upgrade.invoice_h')),
      h('p', { class: 'a-pay-text a-plan-price' }, t('upgrade.price', { price: formatTari(invoice.amount_ut) })),
      h('label', { class: 'a-label', for: 'a-inv-addr' }, t('upgrade.address')),
      h('input', { type: 'text', readonly: true, id: 'a-inv-addr', class: 'a-input mono', 'data-testid': 'invoice-address', value: invoice.address }),
      row, short,
      h('p', { class: 'a-caption' }, t('upgrade.address_note')),
      pay ? h('p', { class: 'a-caption' }, t(direct ? 'pay.browser_note' : 'pay.demo_note')) : null,
      errors, status, stepper,
      h('p', { class: 'a-caption' }, t(cfg.amount_proof === 'wallet' ? 'claim.c11_wallet' : 'claim.c11_proof'))));
    draw(invoice);
    poll(ctx, invoice.invoice_id, draw);
  }
}

async function poll(ctx, id, draw) {
  const { getInvoice } = await import('../lib/api-locker.js');
  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    let inv;
    try {
      inv = await getInvoice(id, ctx.headers());
    } catch (e) {
      if (e?.status >= 400 && e.status < 500) return; // gone or not ours: nothing to wait for
      continue; // a missed poll is retried; the invoice is safe on the server
    }
    draw(inv);
    if (['credited', 'expired'].includes(inv.status)) return;
  }
}
