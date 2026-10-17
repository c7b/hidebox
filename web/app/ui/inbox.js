// SPDX-License-Identifier: MIT
// /inbox, "See what came" (spec §12.3.3): deliveries found on the Ootle by this browser alone. Every browser downloads
// the same mirror of all TARI outputs and tries to open each one with its own view key, so our
// server never learns which outputs are yours. Nothing opens by itself; Open runs the viewer here.
import { h } from './lines.js';
import { formatRelative, t } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { icon } from './core.js';
import { formatTari } from './marks.js';
import { errorBanner } from './errors.js';
import { NeedsWasm, openLocker, storedLocker, wasmOk } from './locker-ctx.js';
import { maybeAskForKey } from './keyflow.js';
import { scene } from './scene.js';
import { setTitle } from './shell.js';

const RESCAN_MS = 15000;

export async function render(main) {
  setTitle('inbox.title');
  const cfg = await config();
  const root = h('div', { class: 'a-inbox', 'data-testid': 'inbox-root' });
  main.replaceChildren(scene({ state: 'keep', title: t('inbox.cta'), say: t('locker.inbox_card') }).head, root);
  if (!(await wasmOk())) return root.replaceChildren(errorBanner(new NeedsWasm()));
  const identity = await storedLocker();
  if (!identity) {
    return root.replaceChildren(h('p', { class: 'a-lede' }, t('inbox.no_locker')),
      h('a', { class: 'a-btn a-btn--primary', href: '/drive' }, t('nav.open_locker')));
  }
  const { deliverySecret, inboxState, scan, updateDelivery } = await import('../lib/scan.js');

  const scanLine = h('p', { class: 'a-scanline mono', 'data-testid': 'inbox-scan', 'aria-live': 'polite' }, t('inbox.scanning'));
  const drops = h('ul', { class: 'a-items' });
  const sends = h('ul', { class: 'a-items' });
  const receipts = h('ul', { class: 'a-items' });
  const sections = {
    drop: h('section', { class: 'a-section', hidden: true, 'aria-labelledby': 'a-in-drop' }, h('h2', { id: 'a-in-drop', class: 'a-h2' }, t('inbox.drops')), drops),
    send: h('section', { class: 'a-section', hidden: true, 'aria-labelledby': 'a-in-send' }, h('h2', { id: 'a-in-send', class: 'a-h2' }, t('inbox.sends')), sends),
    receipt: h('section', { class: 'a-section', hidden: true, 'aria-labelledby': 'a-in-pay' }, h('h2', { id: 'a-in-pay', class: 'a-h2' }, t('inbox.receipts')), receipts),
  };
  const empty = h('p', { class: 'a-lede', 'data-testid': 'inbox-empty', hidden: true }, t('inbox.empty'));
  const problems = h('div', {});
  const again = h('button', { type: 'button', class: 'a-btn', disabled: true }, t('inbox.again'));
  // What the same browser sees with only the view key (judge track two, step 5).
  const peek = h('p', { class: 'a-peek-link' },
    h('a', { class: 'a-btn', href: '/watch#mine', 'data-testid': 'watch-mine' }, t('viewkey.see')));
  root.replaceChildren(scanLine, problems, empty, sections.drop, sections.send, sections.receipt, h('div', { class: 'a-row' }, again, peek));

  // When this browser found the output (the chain epoch in the tooltip); records from before this
  // field existed show the epoch.
  const when = (r) => h('span', { class: 'a-caption mono', title: t('inbox.epoch', { epoch: r.epoch ?? '—' }) },
    r.found ? t('inbox.found', { relative: formatRelative(r.found * 1000) }) : t('inbox.epoch', { epoch: r.epoch ?? '—' }));
  const exitedNote = () => h('span', { class: 'a-caption' }, t('inbox.exited'));

  let found = 0;
  function delivery(d) {
    found++;
    const label = d.source === 'drop'
      ? t('inbox.left_in', { label: identity.drops.find((x) => x.i === d.dropIndex)?.label || t('inbox.drop_n', { n: (d.dropIndex ?? 0) + 1 }) })
      : t('inbox.sent_item');
    const slot = h('div', { class: 'a-item-view' });
    const open = h('button', { type: 'button', class: 'a-btn a-btn--primary', disabled: !d.openable }, t('inbox.open'));
    const li = h('li', { class: 'a-item', 'data-testid': 'inbox-item', 'data-source': d.source, 'data-state': d.exited ? 'exited' : d.openable ? 'ready' : 'unreadable' },
      h('div', { class: 'a-item-row' },
        h('span', { class: 'a-item-what' }, icon(d.source === 'drop' ? 'drop' : 'send'), h('span', {}, label)),
        when(d),
        d.exited ? exitedNote() : d.openable ? open : h('span', { class: 'a-caption' }, t('inbox.unreadable'))),
      slot);
    open.addEventListener('click', async () => {
      open.disabled = true;
      li.dataset.state = 'opened';
      const [{ viewer }, inner] = await Promise.all([import('./view.js'), deliverySecret(identity, d)]);
      viewer(slot, {
        cfg, shareId: inner.shareId, secrets: { s: inner.s }, delivery: d, autoOpen: true, clearKey: false,
        locker: () => openLocker(),
        // Its link ended (opened for the last time, expired or removed): the row says so from now on.
        onEnded: () => {
          li.dataset.state = 'exited';
          open.replaceWith(exitedNote());
          updateDelivery(identity, d.utxoId, { exited: true });
        },
      });
    });
    (d.source === 'drop' ? drops : sends).append(li);
    sections[d.source].hidden = false;
    empty.hidden = true;
  }

  function receipt(r) {
    receipts.append(h('li', { class: 'a-item a-item-row' },
      h('span', {}, t('inbox.received', { x: formatTari(r.value) })),
      r.text ? h('span', { class: 'a-memo' }, t('inbox.message'), ' ', h('q', { class: 'mono' }, r.text)) : null,
      when(r)));
    sections.receipt.hidden = false;
    empty.hidden = true;
  }

  const stored = await inboxState(identity);
  stored.deliveries.forEach(delivery);
  stored.receipts.forEach(receipt);
  const storedCount = found;

  // While the page is open it looks again every little while: deliveries arrive on their own.
  let running = false;
  let timer = null;
  let checkedSoFar = 0; // outputs checked since this page opened
  async function run() {
    if (running) return;
    running = true;
    clearTimeout(timer);
    again.disabled = true;
    problems.replaceChildren();
    let progress = { checked: 0, epoch: null, head: 0 };
    const base = checkedSoFar;
    try {
      await scan(identity, {
        onDelivery: delivery,
        onReceipt: receipt,
        onProgress: (p) => {
          progress = p;
          checkedSoFar = base + p.checked;
          scanLine.dataset.checked = String(checkedSoFar);
          scanLine.dataset.head = String(p.head);
          scanLine.textContent = t('inbox.scan_line', { n: checkedSoFar, e: p.epoch ?? '—' });
        },
      });
      scanLine.dataset.checked = String(checkedSoFar);
      scanLine.textContent = t('inbox.scan_line', { n: checkedSoFar, e: progress.epoch ?? '—' });
      empty.hidden = Boolean(found || receipts.childElementCount);
      if (found > storedCount) maybeAskForKey(identity);
    } catch (e) {
      problems.replaceChildren(errorBanner(e, { key: 'inbox.mirror_error' }));
    } finally {
      running = false;
      again.disabled = false;
      timer = setTimeout(() => document.visibilityState === 'visible' && run(), RESCAN_MS);
    }
  }
  again.addEventListener('click', run);
  document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && run());
  run();
}
