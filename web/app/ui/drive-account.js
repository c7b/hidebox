// SPDX-License-Identifier: MIT
// The account menu (16-drive-design §2 "Drive anatomy"): Copy my Tari address, Save my key, Settings
// (key, Tari address with its code, drive ID, view key, delete my drive) and Lock my drive. The
// key file is locked with a passphrase unless the owner unticks it (P-15); saving it is the only way
// back in (C17-k). Loaded the first time one of these is asked for.
import { hex } from '../lib/b64.js';
import { utf8 } from '../lib/bytes.js';
import { saveFile } from '../lib/download.js';
import { t } from '../lib/i18n.js';
import { h, icon, init, lines, openModal, closeModal, toast } from './behaviors.js';
import { alert, button, dialogBox, errorAlert, fileIcon, itemName, safetyGrid } from './drive-parts.js';

const identityLib = () => import('../lib/identity.js');

async function tari(drive) {
  const { withOotle } = await identityLib();
  return withOotle(drive.identity);
}

function show(box) {
  document.getElementById(box.id)?.remove();
  document.body.append(box);
  init(box);
  openModal(box);
  return box;
}

async function copyAddress(drive) {
  try {
    const identity = await tari(drive);
    await navigator.clipboard.writeText(identity.locker.address);
    toast(t('drive.toast.addr'), { type: 'success' });
  } catch (e) {
    toast(e?.name === 'NotAllowedError' ? t('error.clipboard') : t('error.needs_wasm'), { type: 'error' });
  }
}

// Save my key: a key file (locked with a passphrase by default), the key shown to write down, "I saved it".
export function openKeyDialog(drive) {
  const identity = drive.identity;
  const protect = h('button', { class: 'switch', type: 'button', 'aria-checked': 'true', id: 'key-protect', 'aria-labelledby': 'key-protect-l', 'data-testid': 'key-protect' }, h('span', { class: 'switch-thumb' }));
  const pass = h('input', { class: 'input', type: 'password', id: 'key-pass', autocomplete: 'new-password', spellcheck: 'false', 'aria-describedby': 'key-pass-hint', 'data-testid': 'key-passphrase' });
  const passField = h('div', { class: 'field' }, h('label', { class: 'label', for: 'key-pass' }, t('drive.key.passphrase')), pass,
    h('p', { class: 'small muted', id: 'key-pass-hint' }, t('drive.key.passphrase_hint')));
  const msg = h('p', { class: 'small', 'aria-live': 'polite' });
  const save = button(t('drive.make.file'), { glyph: 'download', testid: 'key-save-file' });
  const locked = () => protect.getAttribute('aria-checked') === 'true';
  protect.addEventListener('sh:change', () => { passField.hidden = !locked(); });
  save.addEventListener('click', async () => {
    if (locked() && !pass.value) {
      msg.textContent = t('drive.key.need_passphrase');
      return pass.focus();
    }
    save.disabled = true;
    // the passphrase's lock (PBKDF2) and Tari's library can take a few seconds on a phone: the button says so
    const label = [...save.childNodes];
    const turning = icon('loader-circle');
    turning.classList.add('spinner');
    save.replaceChildren(turning, t('drive.key.locking'));
    try {
      const lib = await identityLib();
      await lib.withOotle(identity).catch(() => null);   // the file names the address when Tari is here
      const text = locked() ? await lib.lockedKeyFileText(identity, pass.value) : lib.keyFileText(identity);
      saveFile([utf8(text)], lib.keyFileName(identity));
      await lib.updateIdentity(identity, { keySaved: true });
      msg.replaceChildren(...lines(t(locked() ? 'drive.key.saved_locked' : 'drive.key.saved_plain')));
      document.querySelectorAll('[data-testid="key-banner"]').forEach((b) => b.remove());
    } finally {
      save.replaceChildren(...label);
      save.disabled = false;
    }
  });
  const code = h('p', { class: 'mono word-code', 'data-testid': 'key-code' });
  const reveal = h('details', { class: 'disclosure' }, h('summary', {}, icon('chevron-right'), t('drive.key.show')),
    h('div', { class: 'stack' }, h('p', { class: 'small muted' }, t('drive.key.show_warn')), code));
  reveal.addEventListener('toggle', async () => {
    if (reveal.open && !code.textContent) code.textContent = (await identityLib()).recoveryCode(identity.seed);
  });
  const savedBox = h('button', { class: 'checkbox', type: 'button', id: 'key-saved', 'aria-checked': String(identity.keySaved), 'aria-labelledby': 'key-saved-l', 'data-testid': 'key-saved-check' });
  savedBox.addEventListener('sh:change', async () => {
    const lib = await identityLib();
    await lib.updateIdentity(identity, { keySaved: savedBox.getAttribute('aria-checked') === 'true' });
    if (identity.keySaved) document.querySelectorAll('[data-testid="key-banner"]').forEach((b) => b.remove());
  });
  show(dialogBox({
    id: 'key-dialog', title: t('drive.acct.key'), description: t('drive.make.save'), testid: 'key-dialog',
    body: [h('div', { class: 'stack' },
      h('div', { class: 'row' }, protect, h('label', { id: 'key-protect-l', for: 'key-protect' }, t('drive.key.protect'))),
      passField,
      h('div', { class: 'row' }, save),
      msg,
      reveal,
      h('div', { class: 'row' }, savedBox, h('label', { id: 'key-saved-l', for: 'key-saved' }, t('drive.key.saved'))))],
    footer: [button(t('drive.done'), { variant: 'outline', 'data-close': '', testid: 'key-later' })],
  }));
}

function settingRow(glyph, title, desc, ...actions) {
  return h('div', { class: 'setting-row' }, h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon(glyph)),
    h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, title), desc ? h('span', { class: 'choice-desc' }, desc) : null, ...actions));
}

// Settings: the key, the drive's Tari address (with the code a phone scans), its drive ID (the 12 emoji the drop
// page shows under the same name), the view key (C15), and deleting the drive.
export async function openSettings(drive) {
  const addressSlot = h('div', { class: 'stack' }, h('p', { class: 'small muted' }, t('drive.acct.loading')));
  const idSlot = h('div', { class: 'stack' }, h('p', { class: 'small muted' }, t('drive.acct.loading')));
  const viewSlot = h('div', { class: 'stack' });
  const showView = button(t('drive.set.view_show'), { variant: 'outline', size: 'sm', testid: 'export-view-key', 'aria-expanded': 'false' });
  showView.addEventListener('click', async () => {
    try {
      const identity = await tari(drive);
      const value = hex(identity.locker.viewSk);
      const field = h('input', { class: 'input mono', type: 'text', readonly: true, value, 'aria-label': t('drive.set.view'), 'data-testid': 'view-key-value' });
      const copy = button(t('drive.copy'), { variant: 'outline', size: 'sm', glyph: 'copy' });
      copy.addEventListener('click', () => navigator.clipboard.writeText(value).then(() => toast(t('drive.toast.copied'), { type: 'success' }), () => field.select()));
      viewSlot.replaceChildren(h('div', { class: 'link-row' }, field, copy));
      showView.setAttribute('aria-expanded', 'true');
    } catch (e) {
      viewSlot.replaceChildren(errorAlert(e));
    }
  });
  const box = show(dialogBox({
    id: 'settings', title: t('drive.set.title'), size: 'lg', testid: 'settings',
    body: [h('div', { class: 'stack' },
      settingRow('key-round', t('drive.set.key'), t('drive.set.key_d'),
        h('div', { class: 'row wrap' }, button(t('drive.make.file'), { size: 'sm', glyph: 'download', onclick: () => { closeModal('settings'); setTimeout(() => openKeyDialog(drive), 160); } }))),
      settingRow('wallet', t('drive.make.address'), t('drive.make.address_hint'), addressSlot),
      settingRow('shield-check', t('drive.set.safety'), null, idSlot),
      settingRow('eye', t('drive.set.view'), t('drive.set.view_d'), h('div', { class: 'row' }, showView), viewSlot),
      settingRow('trash', t('drive.set.delete'), t('drive.set.delete_d'),
        h('div', { class: 'row' }, button(t('drive.set.delete'), { variant: 'destructive', size: 'sm', testid: 'delete-locker', onclick: () => deleteDialog(drive) }))))],
    footer: [button(t('drive.done'), { variant: 'outline', 'data-close': '' })],
  }));
  try {
    const identity = await tari(drive);
    const { qrFigure } = await import('./qr.js');
    const cfg = drive.cfg;
    const copy = button(t('drive.copy'), { variant: 'outline', size: 'sm', glyph: 'copy', testid: 'copy-address' });
    copy.addEventListener('click', () => copyAddress(drive));
    addressSlot.replaceChildren(
      h('p', { class: 'mono small address-full', 'data-testid': 'locker-address' }, identity.locker.address),
      h('div', { class: 'row' }, copy),
      h('div', { class: 'qr-wrap' }, qrFigure(`${cfg.origin}/#to=${identity.locker.address}`, { label: t('drive.set.qr_label'), caption: t('drive.set.qr'), testid: 'locker-qr' })));
    idSlot.replaceChildren(
      safetyGrid(identity.safetyCode, 'locker-safety'),
      h('p', { class: 'small muted' }, t('drive.set.safety_d', { count: identity.safetyCode.emoji.length })));
  } catch (e) {
    addressSlot.replaceChildren(errorAlert(e));
    idSlot.replaceChildren();
  }
  return box;
}

// Delete my drive: the dialog counts what will go (the drive and its Trash), the owner ticks that it can't
// be undone, then each file and folder is deleted one by one into the trash can on screen. Our server is
// asked again that nothing is left, then DELETE /me ends the drive, and the dialog says what went.
async function driveRows(drive) {
  const { listAll } = await import('../lib/api-drive.js');
  const [live, trashed] = await Promise.all([listAll({ view: 'all' }, drive.headers()),
    listAll({ view: 'trash' }, drive.headers()).catch(() => [])]);
  const seen = new Set();
  return [...live, ...trashed].filter((r) => !seen.has(r.item_id) && seen.add(r.item_id));
}

function goneText(files, folders) {
  return [t('drive.wipe.files', { count: files }), folders ? t('drive.wipe.folders', { count: folders }) : null].filter(Boolean).join(t('drive.wipe.and'));
}

function trashCan() {
  const ns = 'http://www.w3.org/2000/svg';
  const make = (tag, attrs) => { const el = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };
  const can = make('svg', { viewBox: '0 0 96 104', class: 'wipe-can', 'aria-hidden': 'true', focusable: 'false' });
  const lid = make('g', { class: 'wipe-lid' });
  lid.append(make('rect', { x: '14', y: '14', width: '68', height: '8', rx: '3' }), make('path', { d: 'M38 14v-4a4 4 0 0 1 4-4h12a4 4 0 0 1 4 4v4' }));
  const body = make('g', { class: 'wipe-body' });
  body.append(make('path', { d: 'M20 30h56l-5 66a6 6 0 0 1-6 6H31a6 6 0 0 1-6-6z' }),
    make('path', { d: 'M38 44v44M48 44v44M58 44v44', class: 'wipe-ribs' }));
  can.append(body, lid);
  return can;
}

async function deleteDialog(drive) {
  closeModal('settings');
  const errors = h('div', {});
  const summary = h('p', { class: 'small muted', 'data-testid': 'wipe-count' }, t('drive.wipe.counting'));
  const ok = h('button', { class: 'checkbox', type: 'button', id: 'wipe-sure', 'aria-checked': 'false', 'aria-labelledby': 'wipe-sure-l', 'data-testid': 'wipe-sure' });
  const go = button(t('drive.wipe.go'), { variant: 'destructive', testid: 'delete-locker-confirm', disabled: true });
  const cancel = button(t('drive.cancel'), { variant: 'outline', 'data-close': '', 'data-cancel': '' });
  let rows = null;
  const ready = () => { go.disabled = !(rows && ok.getAttribute('aria-checked') === 'true'); };
  ok.addEventListener('sh:change', ready);
  const ask = h('div', { class: 'stack' }, summary,
    h('div', { class: 'row wipe-sure' }, ok, h('label', { id: 'wipe-sure-l', for: 'wipe-sure' }, t('drive.wipe.sure'))), errors);
  const box = dialogBox({
    id: 'delete-drive', role: 'alertdialog', size: 'sm', title: t('drive.set.delete_q'), testid: 'delete-drive',
    media: h('span', { class: 'alert-media' }, icon('triangle-alert')),
    body: [ask], footer: [cancel, go],
  });
  await new Promise((r) => setTimeout(r, 160));
  show(box);
  try {
    rows = await driveRows(drive);
    const folders = rows.filter((r) => r.kind === 'folder').length;
    summary.className = '';
    summary.replaceChildren(...lines(rows.length ? t('drive.wipe.desc', { what: goneText(rows.length - folders, folders) }) : t('drive.wipe.desc_empty')));
    ready();
  } catch (e) {
    summary.replaceChildren();
    errors.replaceChildren(errorAlert(e));
  }
  go.addEventListener('click', () => wipe(drive, box, rows, ask));
}

async function wipe(drive, box, rows, ask) {
  const { deleteItem } = await import('../lib/api.js');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const folders = rows.filter((r) => r.kind === 'folder');
  // Files first, then folders (a folder's DELETE takes what is left inside it).
  const queue = [...rows.filter((r) => r.kind !== 'folder'), ...folders];
  const total = queue.length;
  const bar = h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(total || 1), 'aria-valuenow': '0', 'aria-label': t('drive.wipe.progress_label') },
    h('div', { class: 'progress-indicator' }));
  const count = h('p', { class: 'wipe-count', 'aria-live': 'polite', 'data-testid': 'wipe-progress' }, t('drive.wipe.starting'));
  const now = h('p', { class: 'small muted wipe-now mono' });
  const stage = h('div', { class: 'wipe-stage' }, trashCan());
  const errors = h('div', {});
  box.dataset.busy = 'true';
  box.querySelector('.dialog-title').textContent = t('drive.wipe.working');
  box.querySelector('.dialog-header .alert-media')?.replaceChildren(icon('trash'));
  box.querySelector('.dialog-footer')?.remove();
  ask.remove();
  const panel = h('div', { class: 'stack wipe' }, stage, bar, count, now, errors);
  box.append(panel);

  const drop = (row) => {
    if (reduce) return;
    const it = drive.index.get(row.item_id);
    const chip = h('span', { class: 'wipe-chip' }, icon(it ? fileIcon(it) : row.kind === 'folder' ? 'folder' : 'file'));
    chip.style.setProperty('--x', `${Math.round(Math.random() * 40 - 20)}px`);
    chip.style.setProperty('--r', `${Math.round(Math.random() * 50 - 25)}deg`);
    stage.append(chip);
    stage.classList.remove('is-eating'); void stage.offsetWidth; stage.classList.add('is-eating');
    chip.addEventListener('animationend', () => chip.remove());
  };
  const step = (done) => {
    bar.setAttribute('aria-valuenow', String(done));
    bar.firstChild.style.setProperty('--value', String(total ? Math.round((done / total) * 100) : 100));
    count.textContent = t('drive.wipe.count', { done, total });
  };
  const pause = (ms) => (reduce ? null : new Promise((r) => setTimeout(r, ms)));
  // Fewer than ~25 items: each gets a beat so the eye can follow it. More: as fast as the server goes.
  const beat = total > 25 ? 0 : Math.max(120, Math.min(420, 2400 / Math.max(total, 1)));

  const run = async (from) => {
    errors.replaceChildren();
    try {
      for (let i = from; i < queue.length; i++) {
        const row = queue[i];
        const it = drive.index.get(row.item_id);
        now.textContent = it ? itemName(it) : t(row.kind === 'folder' ? 'drive.wipe.a_folder' : 'drive.wipe.a_file');
        drop(row);
        await deleteItem(row.item_id, drive.headers()).catch((e) => {
          if (e?.status !== 404 && e?.code !== 'not_found' && e?.code !== 'item_gone') throw Object.assign(e, { at: i });
        });
        step(i + 1);
        await pause(beat);
      }
      now.textContent = t('drive.wipe.checking');
      const left = await driveRows(drive);
      if (left.length) throw Object.assign(new Error(t('drive.wipe.left', { count: left.length })), { at: queue.length, left });
      // Drop links close first; if one can't, the drive stays and the alert says why.
      const { closeDrop } = await import('../lib/drop.js');
      for (const d of drive.identity.drops.filter((x) => x.state === 'active')) {
        await closeDrop(drive.identity, d.i).catch((e) => {
          if (e?.code !== 'drop_closed' && e?.code !== 'drop_not_found') throw e;
        });
      }
      const { deleteLocker } = await import('../lib/session.js');
      await deleteLocker(drive.identity);
      await (await identityLib()).forgetIdentity();
      await pause(500);
      done();
    } catch (e) {
      const at = Number.isInteger(e?.at) ? e.at : queue.length;
      if (e?.left) { queue.push(...e.left); }
      delete box.dataset.busy;   // stopped: Escape closes, the drive stays with what is left, Settings can finish it
      errors.replaceChildren(errorAlert(e, { action: { label: t('drive.wipe.retry'), onClick: () => run(at) } }));
    }
  };

  const done = () => {
    delete box.dataset.busy;
    box.setAttribute('role', 'dialog');
    box.querySelector('.dialog-title').textContent = t('drive.wipe.done_title');
    box.querySelector('.dialog-header .alert-media')?.remove();   // the big check below says it
    const finish = button(t('drive.done'), { testid: 'wipe-done', onclick: () => location.assign('/drive') });
    panel.replaceChildren(
      h('div', { class: 'wipe-stage is-done' }, trashCan(), h('span', { class: 'wipe-check' }, icon('check'))),
      h('p', { 'data-testid': 'wipe-done-text' }, total ? t('drive.wipe.done', { what: goneText(total - folders.length, folders.length) }) : t('drive.wipe.done_empty')),
      h('p', { class: 'small muted' }, t('drive.wipe.done_checked')));
    box.append(h('div', { class: 'dialog-footer' }, finish));
    // The drive is gone: closing the dialog any way leaves for /drive.
    box.addEventListener('sh:close', () => location.assign('/drive'), { once: true });
    requestAnimationFrame(() => finish.focus());
  };

  step(0);
  run(0);
}

// Lock my drive: this browser forgets the key. Without the key file, nobody opens it again (C17-k).
function lockDialog(drive) {
  const go = button(t('drive.lock.go'), { variant: 'destructive', testid: 'forget-device' });
  go.addEventListener('click', async () => {
    const { endSession } = await import('../lib/session.js');
    await endSession().catch(() => null);
    await (await identityLib()).forgetIdentity();
    location.assign('/');
  });
  const save = drive.identity.keySaved ? null : button(t('drive.make.file'), { variant: 'outline', glyph: 'download', onclick: () => { closeModal('lock-drive'); setTimeout(() => openKeyDialog(drive), 160); } });
  show(dialogBox({
    id: 'lock-drive', role: 'alertdialog', size: 'sm', title: t('drive.lock.title'), description: t('drive.lock.desc'),
    media: h('span', { class: 'alert-media' }, icon('log-out')),
    body: drive.identity.keySaved ? [] : [alert({ glyph: 'triangle-alert', title: t('drive.lock.unsaved'), variant: 'warning' })],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '', 'data-cancel': '' }), save, go].filter(Boolean),
  }));
}

export function accountAction(drive, value) {
  if (value === 'copy') return copyAddress(drive);
  if (value === 'key') return openKeyDialog(drive);
  if (value === 'settings') return openSettings(drive);
  if (value === 'lock') return lockDialog(drive);
  return null;
}
