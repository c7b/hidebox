// SPDX-License-Identifier: MIT
// /watch, "See without opening" (spec §12.3.3): a Tari address and its view key show every delivery
// and payment to that address, and how many of those files the view key could open (none sealed to a
// locker; kind-4 "other wallet" sends are the labelled exception). The key stays in this tab.
import { h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { equal } from '../lib/bytes.js';
import { icon } from './core.js';
import { formatTari } from './marks.js';
import { errorBanner, uiError } from './errors.js';
import { NeedsWasm, storedLocker, wasmOk } from './locker-ctx.js';
import { setTitle } from './shell.js';

export async function render(main) {
  setTitle('watch.title');
  const cfg = await config();
  const root = h('div', { class: 'a-watch' });
  main.replaceChildren(h('h1', { class: 'a-h1' }, t('watch.h')), root);
  const banner = h('p', { class: 'a-note' }, icon('watch'), h('span', {}, t('watch.banner')));
  if (!(await wasmOk())) return root.replaceChildren(banner, errorBanner(new NeedsWasm()));
  const mine = await storedLocker();
  const ootle = await import('../lib/ootle.js');

  const address = h('input', { type: 'text', id: 'a-w-address', class: 'a-input mono', 'data-testid': 'watch-address', autocomplete: 'off', spellcheck: 'false', placeholder: t('watch.address_ph') });
  const viewKey = h('input', { type: 'password', id: 'a-w-key', class: 'a-input mono', 'data-testid': 'watch-viewkey', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'a-w-key-note' });
  let lockerKeys = null; // set by "Use my locker's view key": the key never appears on screen
  const useMine = mine ? h('button', { type: 'button', class: 'a-btn' }, t('watch.use_mine')) : null;
  useMine?.addEventListener('click', () => {
    lockerKeys = { viewSk: mine.locker.viewSk, viewPk: mine.locker.viewPk };
    address.value = mine.locker.address;
    viewKey.value = '';
    viewKey.disabled = true;
    viewKey.placeholder = t('watch.mine_placeholder');
  });
  const whole = h('input', { type: 'checkbox', id: 'a-w-all' });
  const run = h('button', { type: 'submit', class: 'a-btn a-btn--primary', 'data-testid': 'watch-run' }, t('watch.look'));
  const out = h('div', { class: 'a-watch-out', 'aria-live': 'polite' });
  const form = h('form', { class: 'a-form' },
    h('label', { for: 'a-w-address', class: 'a-label' }, t('watch.address')), address,
    h('label', { for: 'a-w-key', class: 'a-label' }, t('watch.viewkey')), viewKey,
    h('p', { id: 'a-w-key-note', class: 'a-caption' }, t('watch.key_note')),
    useMine,
    h('p', { class: 'a-check' }, whole, h('label', { for: 'a-w-all' }, t('watch.everything'))),
    run);
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    look();
  });
  root.replaceChildren(banner, form, out);

  async function keys() {
    if (lockerKeys) return lockerKeys;
    const { unhex } = await import('../lib/b64.js');
    let viewSk;
    try {
      viewSk = unhex(viewKey.value.trim().toLowerCase());
      if (viewSk.length !== 32) throw new TypeError('length');
    } catch {
      throw uiError('view_key');
    }
    const { viewPk } = ootle.decodeAddress(address.value);
    // A key of the right length that isn't a valid scalar is a wrong key too, not a crash.
    const derived = await ootle.viewPublicKey(viewSk).catch(() => { throw uiError('view_key'); });
    if (!equal(derived, viewPk)) throw uiError('address_mismatch');
    return { viewSk, viewPk };
  }

  async function look() {
    run.disabled = true;
    out.replaceChildren(h('p', { class: 'a-working mono' }, t('watch.looking', { n: 0 })));
    const rows = h('tbody', {});
    try {
      const code = ootle.addressErrorCode(ootle.classifyAddressInput(address.value));
      if (code) throw uiError(code);
      const k = await keys();
      const progress = out.firstChild;
      const { watch } = await import('../lib/scan.js');
      const sum = await watch(k, {
        fromSeq: whole.checked ? 0 : undefined,
        onProgress: (p) => { progress.textContent = t('watch.looking', { n: p.checked }); },
        onRow: (r) => rows.append(h('tr', { 'data-testid': 'watch-row' },
          h('td', { class: 'mono' }, String(r.epoch ?? '—')),
          h('td', { class: 'mono' }, `${formatTari(r.value)} tTARI`),
          h('td', {}, t(`watch.kind.${r.kind}`), r.text ? [' · ', h('q', { class: 'mono' }, r.text)] : null))),
      });
      out.replaceChildren(
        h('p', {
          class: 'a-summary', 'data-testid': 'watch-summary', 'data-deliveries': sum.deliveries,
          'data-received-ut': sum.receivedUt.toString(), 'data-readable': sum.readable,
        },
        h('span', {}, t('watch.deliveries', { count: sum.deliveries })),
        h('span', {}, t('watch.received', { x: formatTari(sum.receivedUt) })),
        h('strong', {}, t('watch.readable', { count: sum.readable }))),
        h('p', { class: 'a-caption mono' }, t('watch.checked', { n: sum.checked })),
        rows.childElementCount
          ? h('table', { class: 'a-table' },
            h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, t('watch.col_epoch')), h('th', { scope: 'col' }, t('watch.col_amount')), h('th', { scope: 'col' }, t('watch.col_what')))),
            rows)
          : h('p', {}, t(whole.checked ? 'watch.none_all' : 'watch.none_week')));
    } catch (e) {
      out.replaceChildren(errorBanner(e, { params: { network: cfg.network } }));
    } finally {
      run.disabled = false;
    }
  }

  if (location.hash === '#mine' && mine) {
    useMine.click();
    look();
  }
}
