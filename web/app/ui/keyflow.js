// SPDX-License-Identifier: MIT
// The locker key (spec §4.8.5–4.8.6, 11-brand §10.4 with patch P-15): saving it (a key file locked
// with a passphrase by default, or the browser's password manager; no copy button), the one-time
// prompt when something worth keeping first exists, the banner until it is saved, and restoring a
// locker from its key on another device.
import { h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { utf8 } from '../lib/bytes.js';
import { saveFile } from '../lib/download.js';
import { localGet, localSet } from '../lib/store.js';
import { icon } from './core.js';
import { errorBanner } from './errors.js';

const ASKED = 'mutis.keyAsked'; // the locker ids this device already asked about (no secret)

let fields = 0;

// The save options: a key file (locked with a passphrase unless the box is unticked), the password
// manager where the browser has one, the key shown to write down, and "I saved it.".
function keySavePanel(identity) {
  const n = ++fields;
  const id = (name) => `a-key-${name}-${n}`;
  const lib = import('../lib/identity.js');
  const protect = h('input', { type: 'checkbox', id: id('protect'), checked: true, 'data-testid': 'key-protect' });
  const pass = h('input', { type: 'password', id: id('pass'), class: 'a-input', 'data-testid': 'key-passphrase', autocomplete: 'new-password', spellcheck: 'false', 'aria-describedby': id('pass-hint') });
  const passRow = h('div', { class: 'a-field' },
    h('label', { for: id('pass'), class: 'a-label' }, t('key.passphrase')), pass,
    h('p', { id: id('pass-hint'), class: 'a-caption' }, t('key.passphrase_hint')));
  protect.addEventListener('change', () => { passRow.hidden = !protect.checked; });
  const msg = h('p', { class: 'a-field-msg', 'aria-live': 'polite' });

  const download = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'key-save-file' }, icon('save'), h('span', {}, t('key.download')));
  download.addEventListener('click', async () => {
    const { keyFileName, keyFileText, lockedKeyFileText } = await lib;
    if (protect.checked && !pass.value) {
      msg.textContent = t('key.need_passphrase');
      return pass.focus();
    }
    download.disabled = true;
    const text = protect.checked ? await lockedKeyFileText(identity, pass.value) : keyFileText(identity);
    saveFile([utf8(text)], keyFileName(identity));
    download.disabled = false;
    msg.textContent = t(protect.checked ? 'key.downloaded_locked' : 'key.downloaded_plain');
  });

  const pm = globalThis.PasswordCredential
    ? h('button', { type: 'button', class: 'a-btn', 'data-testid': 'key-pm-save' }, t('key.pm'))
    : null;
  pm?.addEventListener('click', async () => {
    const { passwordManagerEntry } = await lib;
    try {
      await navigator.credentials.store(new PasswordCredential(passwordManagerEntry(identity)));
      msg.textContent = t('key.pm_done');
    } catch {
      msg.textContent = t('key.pm_failed');
    }
  });

  const code = h('p', { class: 'a-code mono' });
  const show = h('details', { class: 'a-disclose' }, h('summary', {}, t('key.show')),
    h('p', { class: 'a-caption' }, t('key.show_warn')), code);
  show.addEventListener('toggle', async () => {
    if (show.open && !code.textContent) code.textContent = (await lib).recoveryCode(identity.seed);
  });

  const saved = h('input', { type: 'checkbox', id: id('saved'), 'data-testid': 'key-saved-check', checked: identity.keySaved });
  saved.addEventListener('change', async () => {
    const { updateIdentity } = await lib;
    await updateIdentity(identity, { keySaved: saved.checked });
  });

  return h('div', { class: 'a-keysave' },
    h('p', { class: 'a-check' }, protect, h('label', { for: id('protect') }, t('key.protect'))),
    passRow,
    h('div', { class: 'a-row' }, download, pm),
    msg, show,
    h('p', { class: 'a-check a-check--strong' }, saved, h('label', { for: id('saved') }, t('key.saved'))));
}

// Asked once per locker on this device, as a modal, when the first thing worth keeping exists.
export function maybeAskForKey(identity) {
  const asked = localGet(ASKED, []);
  if (identity.keySaved || asked.includes(identity.id)) return;
  localSet(ASKED, [...asked, identity.id].slice(-10));
  openKeyDialog(identity);
}

// The save options as a modal (the one place they appear, so each control exists once on a page).
// onClose(saved) runs when it closes.
export function openKeyDialog(identity, onClose = null) {
  const dialog = h('dialog', { class: 'a-modal', 'aria-labelledby': 'a-key-modal-h' });
  const close = () => {
    dialog.close();
    dialog.remove();
    if (identity.keySaved) document.querySelectorAll('[data-testid="key-banner"]').forEach((b) => b.remove());
    onClose?.(identity.keySaved);
  };
  dialog.append(
    h('h2', { id: 'a-key-modal-h' }, t('key.modal_h')),
    h('p', {}, t('key.modal_body')),
    keySavePanel(identity),
    h('div', { class: 'a-row a-modal-actions' },
      h('button', { type: 'button', class: 'a-btn a-btn--primary', onclick: close }, t('key.continue')),
      h('button', { type: 'button', class: 'a-btn', 'data-testid': 'key-later', onclick: close }, t('key.later'))));
  dialog.addEventListener('cancel', (e) => {
    e.preventDefault();
    close();
  });
  document.body.append(dialog);
  dialog.showModal();
}

// Shown on locker pages until the key is saved (spec §4.8.6 "Later"). onClose(saved) as for the dialog.
export function keyBanner(identity, onClose = null) {
  if (identity.keySaved) return null;
  const banner = h('div', { class: 'a-keybanner', 'data-testid': 'key-banner', role: 'note' },
    icon('warning'), h('p', {}, t('key.banner')),
    h('button', { type: 'button', class: 'a-btn', onclick: () => openKeyDialog(identity, onClose) }, t('key.save')));
  return banner;
}

// "I already have a key": paste the key or its file's text, or choose the file.
export function restorePanel({ onRestored }) {
  const n = ++fields;
  const text = h('textarea', { id: `a-restore-${n}`, class: 'a-input mono', 'data-testid': 'restore-text', rows: 4, spellcheck: 'false', autocomplete: 'off', placeholder: t('restore.placeholder') });
  const file = h('input', { type: 'file', class: 'a-file', 'data-testid': 'restore-file', accept: '.txt,text/plain' });
  const pass = h('input', { type: 'password', id: `a-restore-pass-${n}`, class: 'a-input', 'data-testid': 'restore-passphrase', autocomplete: 'off' });
  const passRow = h('div', { class: 'a-field', hidden: true }, h('label', { for: `a-restore-pass-${n}`, class: 'a-label' }, t('restore.passphrase')), pass);
  const errors = h('div', {});
  const submit = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'restore-submit' }, t('restore.open'));
  const locked = () => /Locked key:/.test(text.value);
  text.addEventListener('input', () => { passRow.hidden = !locked(); });
  file.addEventListener('change', async () => {
    if (file.files[0]) text.value = await file.files[0].text();
    file.value = '';
    passRow.hidden = !locked();
  });
  submit.addEventListener('click', async () => {
    errors.replaceChildren();
    submit.disabled = true;
    try {
      const { restoreFromText } = await import('../lib/identity.js');
      const identity = await restoreFromText(text.value, pass.value);
      onRestored(identity);
    } catch (e) {
      if (e?.code === 'locked') passRow.hidden = false;
      errors.replaceChildren(errorBanner(e));
    } finally {
      submit.disabled = false;
    }
  });
  return h('div', { class: 'a-restore' },
    h('label', { for: `a-restore-${n}`, class: 'a-label' }, t('restore.label')), text,
    h('label', { class: 'a-btn a-filebtn' }, file, h('span', {}, t('restore.file'))),
    passRow, errors, submit);
}
