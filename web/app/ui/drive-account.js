// SPDX-License-Identifier: MIT
// The account menu (16-drive-design §2 "Drive anatomy"): Copy my Tari address, Save my key, Settings
// (key, Tari address with its code and safety code, view key, delete my drive) and Lock my drive. The
// key file is locked with a passphrase unless the owner unticks it (P-15); saving it is the only way
// back in (C17-k). Loaded the first time one of these is asked for.
import { hex } from '../lib/b64.js';
import { utf8 } from '../lib/bytes.js';
import { saveFile } from '../lib/download.js';
import { t } from '../lib/i18n.js';
import { h, icon, init, openModal, closeModal, toast } from './behaviors.js';
import { alert, button, dialogBox, errorAlert, safetyGrid } from './drive-parts.js';

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
    try {
      const lib = await identityLib();
      await lib.withOotle(identity).catch(() => null);   // the file names the address when Tari is here
      const text = locked() ? await lib.lockedKeyFileText(identity, pass.value) : lib.keyFileText(identity);
      saveFile([utf8(text)], lib.keyFileName(identity));
      await lib.updateIdentity(identity, { keySaved: true });
      msg.textContent = t(locked() ? 'drive.key.saved_locked' : 'drive.key.saved_plain');
      document.querySelectorAll('[data-testid="key-banner"]').forEach((b) => b.remove());
    } finally {
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

// Settings: the key, the drive's Tari address (with the code a phone scans, and the safety code), the view
// key (C15), and deleting the drive.
export async function openSettings(drive) {
  const addressSlot = h('div', { class: 'stack' }, h('p', { class: 'small muted' }, t('drive.acct.loading')));
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
      h('div', { class: 'qr-wrap' }, qrFigure(`${cfg.origin}/#to=${identity.locker.address}`, { label: t('drive.set.qr_label'), caption: t('drive.set.qr'), testid: 'locker-qr' })),
      h('p', { class: 'label' }, t('drive.set.safety')),
      safetyGrid(identity.safetyCode, 'locker-safety'),
      h('p', { class: 'small muted' }, t('drive.set.safety_d', { count: identity.safetyCode.emoji.length })));
  } catch (e) {
    addressSlot.replaceChildren(errorAlert(e));
  }
  return box;
}

function deleteDialog(drive) {
  const errors = h('div', {});
  const go = button(t('drive.set.delete'), { variant: 'destructive', testid: 'delete-locker-confirm' });
  go.addEventListener('click', async () => {
    go.disabled = true;
    errors.replaceChildren();
    try {
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
      location.assign('/drive');
    } catch (e) {
      go.disabled = false;
      errors.replaceChildren(errorAlert(e));
    }
  });
  closeModal('settings');
  setTimeout(() => show(dialogBox({
    id: 'delete-drive', role: 'alertdialog', size: 'sm', title: t('drive.set.delete_q'), description: t('drive.set.delete_qd'),
    media: h('span', { class: 'alert-media' }, icon('triangle-alert')),
    body: [errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '', 'data-cancel': '' }), go],
  })), 160);
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
