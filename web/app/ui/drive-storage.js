// SPDX-License-Identifier: MIT
// Storage (16-drive-design §7): the meter (one neutral ramp for what fills the drive, counted in padded
// sizes as our server counts them; violet only for the space paid with tTARI), Get more space with the
// packs from /config (today's /upgrade flow: an invoice paid with test money or from this drive's wallet,
// its steps naming exactly the checks this deployment runs), and the rules of space in words, each true
// to quota.py and cleanup.py, numbers from /config.
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { h, icon, init, lines, openModal } from './behaviors.js';
import { alert, button, closeX, errorAlert, formatTari } from './drive-parts.js';
import { formatDuration } from './core.js';
import { testnetLine } from './marks.js';

// What fills the drive, by kind (decrypted types, here): padded sizes, like the meter. Files in the
// trash still count until it empties; /me says how much (`quota.trash_bytes`), so the parts add up.
function breakdown(drive) {
  const kinds = { media: 0, docs: 0, other: 0 };
  for (const it of drive.index.items.values()) {
    if (it.folder) continue;
    const type = String(it.meta.type || '').toLowerCase();
    const k = /^(image|video|audio)\//.test(type) ? 'media' : it.meta.kind === 'text' || /^text\/|pdf|document|sheet|presentation/.test(type) ? 'docs' : 'other';
    kinds[k] += it.row.size_stored;
  }
  kinds.trash = drive.me.quota.trash_bytes ?? 0;
  return Object.entries(kinds).filter(([, b]) => b > 0);
}

function meterCard(drive) {
  const { quota } = drive.me;
  const used = quota.used_bytes + quota.reserved_bytes;
  const limit = Math.max(1, quota.limit_bytes);
  const full = used >= limit * 0.97;
  const parts = breakdown(drive);
  const bar = h('div', { class: 'stackbar', role: 'img', 'data-testid': 'storage-meter', 'data-used': String(used), 'data-limit': String(quota.limit_bytes),
    'aria-label': [...parts.map(([k, b]) => `${t(`drive.sto.kind.${k}`)} ${formatBytes(b)}`), quota.paid_bytes ? `${t('drive.sto.paid')} ${formatBytes(quota.paid_bytes)}` : null].filter(Boolean).join(', ') || t('drive.sto.nothing') },
  parts.map(([, b], i) => {
    const s = h('span', { class: `c${i + 1}` });
    s.style.width = `${(b / limit) * 100}%`;
    return s;
  }));
  bar.style.setProperty('--free', `${Math.min(100, ((limit - quota.paid_bytes) / limit) * 100)}%`);
  const legend = h('ul', { class: 'legend', role: 'list' },
    parts.map(([k, b], i) => h('li', {}, h('span', { class: `sw c${i + 1}`, 'aria-hidden': 'true' }), h('span', {}, t(`drive.sto.kind.${k}`)), h('b', {}, formatBytes(b)))),
    quota.paid_bytes ? h('li', { class: 'paid' }, h('span', { class: 'sw sw-tari', 'aria-hidden': 'true' }), h('span', {}, t('drive.sto.paid')),
      h('b', {}, t('drive.sto.paid_until', { bytes: formatBytes(quota.paid_bytes), date: formatDate(quota.paid_until * 1000, { dateStyle: 'medium' }) }))) : null);
  return h('section', { class: 'card', 'aria-labelledby': 'meter-h' },
    h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: 'meter-h' }, t('drive.sto.space')),
      // Fifth pass: on the first day the limit is the first-day one; say both, so the two numbers don't clash.
      h('p', { class: 'card-description', 'data-testid': 'storage-free' }, drive.me.identity?.probation
        ? t('drive.sto.first_day', { probation_quota: formatBytes(quota.limit_bytes), free_each: formatBytes(quota.free_bytes) })
        : t('drive.sto.free', { free_each: formatBytes(quota.free_bytes) }))),
    h('div', { class: 'card-content meter-big' },
      h('div', { class: 'meter-num' }, formatBytes(used), h('small', {}, ` ${t('drive.sto.of', { limit: formatBytes(quota.limit_bytes) })}`)),
      bar,
      full ? alert({ glyph: 'triangle-alert', title: t('drive.sto.full'), variant: 'warning', testid: 'storage-full' }) : legend,
      h('p', { class: 'small muted' }, t('drive.sto.padded'))));
}

// The rules of space, each with its numbers from /config; rules of parts this deployment doesn't run
// (the trash, Delete it after) are left out.
function rulesCard(drive) {
  const cfg = drive.cfg;
  const r = cfg.retention ?? {};
  const maxDays = cfg.items?.max_delete_after_days;
  const rules = [
    ['hard-drive', t('drive.sto.fair')],
    ['house', t('drive.sto.first', { probation_quota: formatBytes(cfg.limits.probation.quota_bytes) })],
    drive.folders && r.trash_days ? ['trash', t('drive.sto.counts', { trash_days: r.trash_days })] : null,
    drive.folders && maxDays ? ['hourglass', t('drive.sto.later', { max_days: maxDays })] : null,
    r.inactive_days ? ['clock', t('drive.sto.idle', { inactive_days: r.inactive_days })] : null,
    r.lapse_grace_days ? ['timer', t(drive.folders ? 'drive.sto.lapse' : 'drive.sto.lapse_oldest', { lapse_grace_days: r.lapse_grace_days })] : null,
    ['shield-check', t('drive.sto.seller')],
  ].filter(Boolean);
  return h('section', { class: 'card', 'aria-labelledby': 'how-h' },
    h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: 'how-h' }, t('drive.sto.how'))),
    h('div', { class: 'card-content rules-read' }, rules.map(([glyph, text]) =>
      h('div', { class: 'item', 'data-size': 'sm' }, h('div', { class: 'item-media', 'data-variant': 'icon', 'aria-hidden': 'true' }, icon(glyph)),
        h('div', { class: 'item-content' }, h('p', { class: 'item-description' }, text))))));
}

// The four steps of a pack payment and when each is reached, per proof mode (the old /upgrade's rule:
// name exactly the checks that run, never more).
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

let polling = 0;

async function poll(drive, id, draw, run) {
  const { getInvoice } = await import('../lib/api-locker.js');
  while (run === polling) {
    await new Promise((r) => setTimeout(r, 3000));
    if (run !== polling) return;
    let inv;
    try {
      inv = await getInvoice(id, drive.headers());
    } catch (e) {
      if (e?.status >= 400 && e.status < 500) return; // gone or not ours: nothing to wait for
      continue; // a missed poll is retried; the invoice is safe on the server
    }
    draw(inv);
    if (['credited', 'expired'].includes(inv.status)) return;
  }
}

// The invoice dialog: the price, the address to pay (our receiver with the invoice's reference inside),
// one primary (test money, paid by our demo wallet), and from this drive's wallet when the deployment
// sends from browsers.
async function buy(drive, pack, label) {
  const cfg = drive.cfg;
  const run = ++polling;
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('upgrade.making')));
  const footer = h('div', { class: 'dialog-footer' });
  const box = h('div', { class: 'dialog', role: 'dialog', id: 'invoice', hidden: true, 'data-testid': 'invoice-dialog' }, closeX(),
    h('div', { class: 'dialog-header' }, h('h2', { class: 'dialog-title', tabindex: '-1', 'data-autofocus': '' }, t('drive.sto.invoice')),
      h('p', { class: 'dialog-description' }, label)),
    body, footer);
  document.getElementById('invoice')?.remove();
  document.body.append(box);
  openModal(box, { onClose: () => { if (polling === run) polling++; } });
  let invoice;
  try {
    const [{ createInvoice }, { judgeHeaders }] = await Promise.all([import('../lib/api-locker.js'), import('../lib/pow.js')]);
    invoice = await createInvoice(pack.id, { ...drive.headers(), ...judgeHeaders() });  // a judge pass buys from the judges' share
  } catch (e) {
    return body.replaceChildren(errorAlert(e));
  }
  const direct = cfg.send_mode === 'direct' && cfg.features?.direct_send;
  if (direct && cfg.features?.sponsor) {
    // Pay from my drive spends the browser wallet's sponsor grant: ask for today's, in the background (once a day).
    import('../lib/identity.js').then(({ withOotle }) => withOotle(drive.identity))
      .then((id) => import('../lib/wallet.js').then((w) => w.ensureGrant(id, cfg))).catch(() => null);
  }
  const list = steps(cfg.amount_proof);
  const status = h('p', { class: 'say', 'data-testid': 'invoice-status', 'data-status': invoice.status, 'aria-live': 'polite' });
  const stepper = h('ol', { class: 'steps', 'aria-label': t('drive.sto.steps') });
  const errors = h('div', {});
  const buttons = [];
  const payButton = (testid, label2, variant, glyph, pay) => {
    const b = button(label2, { testid, variant, glyph });
    b.addEventListener('click', async () => {
      b.disabled = true;
      errors.replaceChildren();
      try {
        await pay(await import('../lib/wallet.js'));
      } catch (e) {
        b.disabled = false;
        errors.replaceChildren(errorAlert(e));
      }
    });
    buttons.push(b);
    return b;
  };
  const demo = cfg.features?.demo_pay ? payButton('demo-pay', t('drive.sto.pay_test'), null, 'coins', (w) => w.demoPayInvoice(invoice.invoice_id)) : null;
  const fromDrive = direct ? payButton('pay-browser', t('drive.sto.pay_drive'), 'outline', 'wallet', async (w) => {
    const { withOotle } = await import('../lib/identity.js');
    await w.payInvoice(await withOotle(drive.identity), invoice);
  }) : null;
  const copy = button(t('drive.copy'), { variant: 'outline', glyph: 'copy' });
  copy.addEventListener('click', () => navigator.clipboard.writeText(invoice.address).catch(() => null));
  const draw = (inv) => {
    status.dataset.status = inv.status;
    status.replaceChildren(...lines(t(`upgrade.status.${inv.status}`, {
      x: formatTari(inv.received_ut ?? '0'), y: formatTari(inv.amount_ut), z: formatTari(BigInt(inv.amount_ut) - BigInt(inv.received_ut ?? '0')),
      underpaid_days: cfg.invoices.underpaid_grace_days,
    })));
    const reached = list.map(([, done]) => done(inv));
    stepper.replaceChildren(...list.map(([name], i) => {
      const state = reached[i] && (reached[i + 1] || inv.status === 'credited') ? 'done' : reached[i] ? 'now' : 'todo';
      const dot = h('span', { class: 'dot' }, state === 'done' ? icon('check') : null);
      return h('li', { 'data-state': state, 'data-testid': 'pay-step', 'data-step': name, 'data-done': String(reached[i]), 'aria-current': state === 'now' ? 'step' : null },
        dot, h('span', {}, t(`upgrade.step.${name}`)));
    }));
    if (inv.status === 'credited') {
      for (const b of buttons) b.remove();
      stepper.after(alert({ glyph: 'circle-check', variant: 'success', title: t('upgrade.added', { bytes: formatBytes(inv.credited?.bytes ?? pack.bytes), date: formatDate((inv.credited?.until ?? 0) * 1000, { dateStyle: 'medium' }) }), testid: 'invoice-done' }));
      drive.refreshMe().then(() => (drive.route.view === 'storage' ? drive.render() : null)).catch(() => null);
    }
  };
  body.replaceChildren(...[   // without the null lines, which would read "null"
    h('div', { class: 'price-big' }, formatTari(invoice.amount_ut), h('small', {}, 'tTARI')),
    h('div', { class: 'field' }, h('label', { class: 'label', for: 'invoice-addr' }, t('upgrade.address')),
      h('div', { class: 'link-row' }, h('input', { class: 'input mono', id: 'invoice-addr', type: 'text', readonly: true, value: invoice.address, 'data-testid': 'invoice-address' }), copy),
      h('p', { class: 'small muted' }, t('upgrade.address_note'))),
    stepper, status, errors,
    h('p', { class: 'small muted' }, t(cfg.amount_proof === 'wallet' ? 'claim.c11_wallet' : 'claim.c11_proof')),
    demo ? h('p', { class: 'small muted' }, t('pay.demo_note')) : null,
    testnetLine(cfg)].filter(Boolean));
  footer.replaceChildren(...[fromDrive, demo].filter(Boolean));
  init(box);
  draw(invoice);
  poll(drive, invoice.invoice_id, draw, run);
}

// Sixth pass: one pack at a time. The pack a drive holds says until when, and turns into Renew it in its
// last days (the same pack again adds days, not space); the other waits. Paused packs say so instead.
function moreSection(drive) {
  const cfg = drive.cfg;
  const packs = cfg.pricing?.packs ?? [];
  const held = drive.me.pack ?? null;
  const day = (s) => formatDate(s * 1000, { dateStyle: 'medium' });
  const renewing = held && Date.now() / 1000 >= held.renew_from;
  const paused = cfg.features?.packs === false;
  const action = (pack, label, i) => {
    const testid = `pack-${pack.id}`;
    const variant = i === 0 ? null : 'outline';
    if (paused) return null;
    if (!held) return button(t('drive.sto.get'), { variant, testid, onclick: () => buy(drive, pack, label) });
    if (held.id === pack.id || held.id === null) {
      return renewing ? button(t('drive.sto.renew'), { variant, testid, glyph: 'repeat', onclick: () => buy(drive, pack, label) })
        : button(t('drive.sto.yours', { date: day(held.until) }), { variant: 'outline', testid, disabled: true });
    }
    return button(t('drive.sto.get'), { variant: 'outline', testid, disabled: true });
  };
  const note = paused ? alert({ glyph: 'info', title: t('drive.sto.paused'), testid: 'packs-paused' })
    : held && !renewing ? h('p', { class: 'small muted', 'data-testid': 'pack-renew-from' }, t('drive.sto.renew_from', { date: day(held.renew_from) }))
      : null;
  return h('section', { id: 'more', 'aria-labelledby': 'more-h', class: 'stack' },
    h('div', {}, h('h2', { class: 'h3', id: 'more-h' }, t('drive.sto.more')),
      h('p', { class: 'muted' }, t('drive.sto.more_d')),
      cfg.pricing?.renew_days ? h('p', { class: 'small muted', 'data-testid': 'pack-rule' }, t('drive.sto.one', { renew_days: formatDuration(cfg.pricing.renew_days * 86400) })) : null),
    note,
    h('div', { class: 'packs' }, packs.map((pack, i) => {
      const label = t('drive.sto.pack', { bytes: formatBytes(pack.bytes), days: formatDuration(pack.days * 86400) });
      return h('div', { class: 'card', 'data-testid': 'storage-pack', 'data-pack': pack.id, 'data-held': held && (held.id === pack.id || held.id === null) ? 'true' : null },
        h('div', { class: 'card-header' }, h('h3', { class: 'card-title' }, label),
          h('p', { class: 'card-description' }, t(i === 0 ? 'drive.sto.small_d' : 'drive.sto.big_d'))),
        h('div', { class: 'card-content' }, h('div', { class: 'pack-price' }, formatTari(pack.price_ut), h('small', {}, 'tTARI'))),
        h('div', { class: 'card-footer' }, action(pack, label, i)));
    })),
    testnetLine(drive.cfg));
}

export async function render(drive, page) {
  await drive.ready();
  await drive.refreshMe();
  page.replaceChildren(
    h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.storage'))),
    h('div', { class: 'two-col' }, h('div', { class: 'stack' }, meterCard(drive), moreSection(drive)), rulesCard(drive)));
  init(page);
}
