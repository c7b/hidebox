// SPDX-License-Identifier: MIT
// /locker (spec §12.3.3): before a locker exists, what one is, "Leave me a file" first (it opens one
// silently), the two other ways in, and restoring a key; with a locker, its safety code and Tari address, the dead-drop
// link, a drop zone that locks files as the locker, kept files, the quota, the key, the view key,
// and leaving (forget this device, delete the locker).
import { h, setVar } from '../lib/dom.js';
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { b64uDecode, hex } from '../lib/b64.js';
import { config, deleteItem } from '../lib/api.js';
import { copyButton, fill, formatDuration, icon, toast } from './core.js';
import { safetyGrid, testnetLine } from './marks.js';
import { errorBanner } from './errors.js';
import { NeedsWasm, openLocker, storedLocker, wasmOk } from './locker-ctx.js';
import { keyBanner, maybeAskForKey, openKeyDialog, restorePanel } from './keyflow.js';
import { setTitle } from './shell.js';

const plate = () => h('div', { class: 'a-plate', 'aria-hidden': 'true' }, icon('keyhole', 'a-plate-mark'));

export async function render(main) {
  setTitle('locker.title');
  const cfg = await config();
  const root = h('div', { class: 'a-locker', 'data-testid': 'locker-root' });
  main.replaceChildren(root);
  if (!(await wasmOk())) return root.replaceChildren(h('h1', { class: 'a-h1' }, t('locker.h')), errorBanner(new NeedsWasm()));
  const identity = await storedLocker();
  if (!identity) return empty(root, cfg);
  root.replaceChildren(h('p', { class: 'a-working mono' }, t('locker.signing_in')));
  try {
    full(root, cfg, await openLocker());
  } catch (e) {
    root.replaceChildren(errorBanner(e, { action: { label: t('viewer.retry'), onClick: () => render(main) } }));
  }
}

// --- no locker yet ---------------------------------------------------------------------------------

function empty(root, cfg) {
  root.dataset.probation = '';
  const status = h('div', { 'aria-live': 'polite' });
  const open = async (then) => {
    status.replaceChildren(h('p', { class: 'a-working mono' }, t('locker.opening')));
    try {
      const ctx = await openLocker();
      await then?.(ctx);
      full(root, cfg, ctx);
    } catch (e) {
      status.replaceChildren(errorBanner(e));
    }
  };
  const label = h('input', { type: 'text', id: 'a-drop-label-0', class: 'a-input', 'data-testid': 'drop-label', maxlength: 80, autocomplete: 'off' });
  const make = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'drop-create' }, t('drop.make'));
  make.addEventListener('click', () => {
    make.disabled = true;
    open((ctx) => makeDrop(ctx, label.value.trim())).finally(() => { make.disabled = false; });
  });
  root.replaceChildren(
    plate(),
    h('h1', { class: 'a-h1' }, t('locker.h')),
    h('p', { class: 'a-lede' }, t('locker.intro')),
    status,
    h('section', { class: 'a-card', 'aria-labelledby': 'a-drop-h0' },
      icon('drop', 'a-card-icon'), h('h2', { id: 'a-drop-h0', class: 'a-card-h' }, t('drop.cta')),
      h('p', {}, t('drop.before')),
      h('label', { for: 'a-drop-label-0', class: 'a-label' }, t('drop.label')), label, make),
    h('ul', { class: 'a-ways' },
      h('li', {}, h('a', { class: 'a-more', href: '/send' }, icon('send'), h('span', {}, t('send.cta'))), h('p', { class: 'a-caption' }, t('locker.send_card'))),
      h('li', {}, h('a', { class: 'a-more', href: '/watch' }, icon('watch'), h('span', {}, t('watch.cta'))), h('p', { class: 'a-caption' }, t('locker.watch_card')))),
    h('section', { class: 'a-section', 'aria-labelledby': 'a-restore-h' },
      h('h2', { id: 'a-restore-h', class: 'a-h2' }, t('restore.h')),
      h('p', {}, t('restore.body')),
      restorePanel({ onRestored: () => open() })));
}

async function makeDrop(ctx, label) {
  const { createDrop } = await import('../lib/drop.js');
  await createDrop(ctx.identity, label);
  maybeAskForKey(ctx.identity);
}

// --- the locker ------------------------------------------------------------------------------------

// On a fine pointer (a computer) the locker's address and its drop link are also codes a phone scans
// (14-ghost-design §9, track two): the address opens the phone's home with it filled in (/#to=…, a
// fragment our server never sees); the drop link opens the drop page.
function scanCode(holder, text, caption, testid) {
  if (!matchMedia('(hover: hover) and (pointer: fine), (min-width: 900px) and (not (pointer: coarse))').matches) return holder;
  import('./qr.js').then(({ qrFigure }) => holder.replaceChildren(qrFigure(text, { label: t('qr.label'), caption, testid })));
  return holder;
}

function full(root, cfg, ctx) {
  const { identity, me } = ctx;
  root.dataset.probation = String(me.identity.probation);
  const keyState = h('p', { class: 'a-done' });
  const afterKey = () => keyState.replaceChildren(...(identity.keySaved ? [icon('check'), h('span', {}, t('key.saved_state'))] : []));
  afterKey();
  const keySection = h('section', { class: 'a-section', id: 'key', 'aria-labelledby': 'a-key-h' },
    h('h2', { id: 'a-key-h', class: 'a-h2' }, t('key.h')),
    h('p', {}, t('key.intro')),
    keyState,
    h('button', { type: 'button', class: 'a-btn', onclick: () => openKeyDialog(identity, afterKey) }, t('key.save')));
  const zone = h('div', { class: 'a-zone' });
  const network = cfg.network.charAt(0).toUpperCase() + cfg.network.slice(1);
  const who = h('aside', { class: 'a-identity', 'aria-label': t('locker.h_yours') },
    h('section', { class: 'a-id-block', 'aria-labelledby': 'a-safety-h' },
      h('h2', { id: 'a-safety-h', class: 'a-label' }, t('safety.h')),
      safetyGrid(identity.safetyCode, { testid: 'locker-safety', class: 'a-safety--large' }),
      h('p', { class: 'a-caption' }, t('safety.compare', { count: identity.safetyCode.emoji.length }))),
    h('section', { class: 'a-id-block', 'aria-labelledby': 'a-address-h' },
      h('h2', { id: 'a-address-h', class: 'a-label' }, t('locker.address')),
      h('p', { class: 'a-address mono', 'data-testid': 'locker-address' }, identity.locker.address),
      h('div', { class: 'a-row' },
        copyButton({ label: t('locker.copy_address'), testid: 'copy-address', getText: () => identity.locker.address }),
        h('span', { class: 'a-chip' }, t('locker.network', { network }))),
      scanCode(h('div', {}), `${cfg.origin}/#to=${identity.locker.address}`, t('locker.qr'), 'locker-qr')));
  const uses = h('div', { class: 'a-locker-main' },
    dropSection(cfg, ctx),
    h('section', { class: 'a-section', 'aria-labelledby': 'a-lock-h' },
      h('h2', { id: 'a-lock-h', class: 'a-h2' }, t('locker.lock_h')),
      h('p', {}, t('locker.lock_body', { dur: formatDuration(me.limits.max_expiry_s) })),
      zone),
    cfg.features?.kept ? keptSection(ctx) : null,
    quotaSection(cfg, ctx),
    keySection,
    viewKeySection(identity),
    leaveSection(root, cfg, ctx));
  fill(root, keyBanner(identity, afterKey), h('h1', { class: 'a-h1' }, t('locker.h_yours')), h('div', { class: 'a-locker-cols' }, who, uses));
  import('./widget.js').then(({ mountWidget }) => mountWidget(zone, { variant: 'locker', locker: () => openLocker() }));
}

// "Leave me a file": the drop link (spec §4.11), one active link at a time from this page.
function dropSection(cfg, ctx) {
  const section = h('section', { class: 'a-section a-dropcard', 'aria-labelledby': 'a-drop-h' });
  const draw = () => {
    const active = ctx.identity.drops.filter((d) => d.state === 'active').at(-1);
    const head = [icon('drop', 'a-card-icon'), h('h2', { id: 'a-drop-h', class: 'a-h2' }, t('drop.cta'))];
    if (!cfg.features?.drops) return section.replaceChildren(...head, errorBanner({ code: 'feature_disabled' }));
    if (!active) {
      const label = h('input', { type: 'text', id: 'a-drop-label', class: 'a-input', 'data-testid': 'drop-label', maxlength: 80, autocomplete: 'off' });
      const make = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'drop-create' }, t('drop.make'));
      const errors = h('div', {});
      make.addEventListener('click', async () => {
        make.disabled = true;
        make.textContent = t('drop.making');
        try {
          await makeDrop(ctx, label.value.trim());
          draw();
        } catch (e) {
          errors.replaceChildren(errorBanner(e));
          make.disabled = false;
          make.textContent = t('drop.make');
        }
      });
      return section.replaceChildren(...head, h('p', {}, t('drop.before')),
        h('label', { for: 'a-drop-label', class: 'a-label' }, t('drop.label')), label, make, errors);
    }
    const url = `${cfg.origin}/d/${active.drop_id}`;
    const errors = h('div', {});
    const act = (fn) => async () => {
      errors.replaceChildren();
      try {
        await fn();
        draw();
      } catch (e) {
        errors.replaceChildren(errorBanner(e));
      }
    };
    const lib = import('../lib/drop.js');
    fill(section, ...head,
      active.label ? h('p', { class: 'a-caption' }, t('drop.for', { label: active.label })) : null,
      h('input', { type: 'text', readonly: true, class: 'a-droplink mono', 'data-testid': 'drop-link', value: url, 'aria-label': t('drop.link_label') }),
      h('div', { class: 'a-row' },
        copyButton({ label: t('drop.copy'), testid: 'drop-copy', getText: () => url, cls: 'a-btn a-btn--primary' }),
        h('button', { type: 'button', class: 'a-btn', onclick: act(async () => (await lib).rotateDrop(ctx.identity, active.i)) }, t('drop.new')),
        h('button', { type: 'button', class: 'a-btn', 'data-testid': 'drop-close', onclick: act(async () => (await lib).closeDrop(ctx.identity, active.i)) }, t('drop.close'))),
      h('p', { class: 'a-caption' }, t('drop.after', { count: cfg.limits.drop.views, dur: formatDuration(cfg.limits.drop.expiry_s) })),
      scanCode(h('div', {}), url, t('drop.qr'), 'drop-qr'),
      errors);
  };
  draw();
  return section;
}

// P1: files kept in the locker ("Only me", "Until I delete it"), newest first.
function keptSection(ctx) {
  const list = h('ul', { class: 'a-kept' }, h('li', { class: 'a-working mono' }, t('known.loading')));
  const section = h('section', { class: 'a-section', 'aria-labelledby': 'a-kept-h' },
    h('h2', { id: 'a-kept-h', class: 'a-h2' }, t('kept.h')), list);
  (async () => {
    const { listMyItems } = await import('../lib/api-locker.js');
    const { items } = await listMyItems(null, ctx.headers());
    const kept = items.filter((i) => i.retention === 'kept');
    if (!kept.length) return list.replaceWith(h('p', { class: 'a-caption' }, t('kept.empty')));
    list.replaceChildren(...await Promise.all(kept.map((row) => keptRow(ctx, row))));
  })().catch((e) => list.replaceWith(errorBanner(e)));
  return section;
}

async function keptRow(ctx, row) {
  const [{ parseHeader, deriveItemKeys, decryptMeta }, { unwrapFileKey }, { sha256 }] = await Promise.all([
    import('../lib/format.js'), import('../lib/share.js'), import('../lib/crypto.js')]);
  const header = b64uDecode(row.header);
  const hh = await sha256(header);
  const fk = await unwrapFileKey(ctx.identity.vaultKey, hh, b64uDecode(row.owner_wrap));
  const meta = await decryptMeta((await deriveItemKeys(fk, parseHeader(header).salt)).metaKey, hh, b64uDecode(row.meta_ct));
  const li = h('li', { class: 'a-kept-row', 'data-testid': 'kept-row' },
    h('span', { class: 'a-kept-name' }, meta.kind === 'text' ? t('card.note') : meta.name),
    h('span', { class: 'mono' }, formatBytes(meta.size)),
    h('span', { class: 'a-caption' }, formatDate(row.created_hour * 1000, { dateStyle: 'medium' })));
  const save = h('button', { type: 'button', class: 'a-btn', 'data-testid': 'kept-save' }, icon('save'), h('span', {}, t('viewer.save')));
  const fail = (e) => li.append(errorBanner(e));
  save.addEventListener('click', async () => {
    try {
      const [{ openKept, fetchContent }, { saveFile }] = await Promise.all([import('../lib/open.js'), import('../lib/download.js')]);
      const opened = await openKept(ctx.identity, row, ctx.headers());
      saveFile(await fetchContent(opened), meta.name || 'mutis-note.txt');
    } catch (e) {
      fail(e);
    }
  });
  const del = h('button', { type: 'button', class: 'a-btn a-btn--exit', 'data-testid': 'kept-delete' }, t('kept.delete'));
  del.addEventListener('click', async () => {
    try {
      await deleteItem(row.item_id, ctx.headers());
      li.remove();
      toast(t('toast.deleted'));
    } catch (e) {
      fail(e);
    }
  });
  li.append(h('span', { class: 'a-row' }, save, del));
  return li;
}

function quotaSection(cfg, ctx) {
  const { quota, identity } = ctx.me;
  const used = quota.used_bytes + quota.reserved_bytes;
  const bar = h('div', { class: 'a-quota', 'data-testid': 'quota-bar', 'data-used': used, 'data-limit': quota.limit_bytes, role: 'meter',
    'aria-valuemin': '0', 'aria-valuemax': String(quota.limit_bytes), 'aria-valuenow': String(used), 'aria-label': t('quota.label') },
  h('span', { class: 'a-quota-fill' }));
  setVar(bar, '--q', Math.min(1, used / Math.max(1, quota.limit_bytes)));
  return h('section', { class: 'a-section', 'aria-labelledby': 'a-quota-h' },
    h('h2', { id: 'a-quota-h', class: 'a-h2' }, t('quota.h')),
    bar,
    h('p', {}, t('quota.used', { used: formatBytes(used), quota: formatBytes(quota.limit_bytes) })),
    identity.probation ? h('p', { class: 'a-caption' }, t('quota.probation', { probation: formatBytes(cfg.limits.probation.quota_bytes) })) : null,
    quota.paid_until ? h('p', { class: 'a-caption' }, t('quota.paid', { date: formatDate(quota.paid_until * 1000, { dateStyle: 'medium' }) })) : null,
    h('a', { class: 'a-btn', href: '/upgrade' }, t('quota.more')),
    testnetLine(cfg));
}

// The view key: see what it sees (here, in this tab), or export it with the warning next to it.
function viewKeySection(identity) {
  const out = h('div', { class: 'a-viewkey', hidden: true });
  const exportButton = h('button', { type: 'button', class: 'a-btn', 'data-testid': 'export-view-key', 'aria-expanded': 'false' }, t('viewkey.export'));
  exportButton.addEventListener('click', () => {
    const value = hex(identity.locker.viewSk);
    const field = h('input', { type: 'text', readonly: true, class: 'a-input mono', 'data-testid': 'view-key-value', value, 'aria-label': t('viewkey.label') });
    out.replaceChildren(
      h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t('viewkey.warn'))),
      field, copyButton({ label: t('viewkey.copy'), getText: () => value, fallback: field }));
    out.hidden = false;
    exportButton.setAttribute('aria-expanded', 'true');
  });
  return h('section', { class: 'a-section', 'aria-labelledby': 'a-vk-h' },
    h('h2', { id: 'a-vk-h', class: 'a-h2' }, t('viewkey.h')),
    h('p', {}, t('viewkey.intro')),
    h('div', { class: 'a-row' },
      h('a', { class: 'a-btn a-btn--primary', href: '/watch#mine', 'data-testid': 'watch-mine' }, icon('watch'), h('span', {}, t('viewkey.see'))),
      exportButton),
    out);
}

// Forget this device; delete the locker (type DELETE).
function leaveSection(root, cfg, ctx) {
  const area = h('div', {});
  const forget = h('button', { type: 'button', class: 'a-btn', 'data-testid': 'forget-device' }, t('leave.forget'));
  const remove = h('button', { type: 'button', class: 'a-btn a-btn--exit', 'data-testid': 'delete-locker' }, t('leave.delete'));
  const reset = async () => {
    const { forgetIdentity } = await import('../lib/identity.js');
    const { endSession } = await import('../lib/session.js');
    await endSession().catch(() => null);
    await forgetIdentity();
    location.reload();
  };
  forget.addEventListener('click', () => {
    area.replaceChildren(h('div', { class: 'a-confirm' },
      h('p', {}, t('leave.forget_confirm')),
      h('div', { class: 'a-row' },
        h('button', { type: 'button', class: 'a-btn a-btn--exit', onclick: reset }, t('leave.forget_yes')),
        h('button', { type: 'button', class: 'a-btn', onclick: () => area.replaceChildren() }, t('leave.cancel')))));
  });
  remove.addEventListener('click', () => {
    const typed = h('input', { type: 'text', id: 'a-delete-typed', class: 'a-input', autocomplete: 'off', 'data-testid': 'delete-typed' });
    const errors = h('div', {});
    const go = h('button', { type: 'button', class: 'a-btn a-btn--exit', 'data-testid': 'delete-locker-confirm' }, t('leave.delete_yes'));
    go.addEventListener('click', async () => {
      if (typed.value.trim() !== 'DELETE') return errors.replaceChildren(h('p', { class: 'a-field-msg a-field-msg--bad' }, t('leave.delete_type')));
      try {
        // Drop links close first; if one can't, the locker stays and the banner says why, so no
        // public drop is left delivering to a locker that no longer exists.
        const { closeDrop } = await import('../lib/drop.js');
        for (const d of ctx.identity.drops.filter((x) => x.state === 'active')) {
          await closeDrop(ctx.identity, d.i).catch((e) => {
            if (e?.code !== 'drop_closed' && e?.code !== 'drop_not_found') throw e;
          });
        }
        const { deleteLocker } = await import('../lib/session.js');
        await deleteLocker(ctx.identity);
        await reset();
      } catch (e) {
        errors.replaceChildren(errorBanner(e));
      }
    });
    area.replaceChildren(h('div', { class: 'a-confirm' },
      h('p', {}, t('leave.delete_confirm')),
      h('label', { for: 'a-delete-typed', class: 'a-label' }, t('leave.delete_type')), typed, errors,
      h('div', { class: 'a-row' }, go, h('button', { type: 'button', class: 'a-btn', onclick: () => area.replaceChildren() }, t('leave.cancel')))));
    typed.focus();
  });
  return h('section', { class: 'a-section', 'aria-labelledby': 'a-leave-h' },
    h('h2', { id: 'a-leave-h', class: 'a-h2' }, t('leave.h')),
    h('div', { class: 'a-row' }, forget, remove), area);
}

