// SPDX-License-Identifier: MIT
// /drive in a browser with no drive yet (16-drive-design §2, §11): Make my drive makes the key here at
// once and opens the drive (one tap; /drive?make does it on arrival from the home page), and Open my
// drive takes the saved key, pasted or as its file (/drive?open opens that dialog). No email, no
// password: the key is the account (C17).
import { t, BRAND } from '../lib/i18n.js';
import { h, icon, init, lines, openModal, closeModal } from './behaviors.js';
import { alert, button, dialogBox, errorAlert } from './drive-parts.js';
import { mmss } from './errors.js';

// A new drive: its key made in this browser, then registered (a proof of work, or the judge pass).
export async function makeDrive({ onProgress } = {}) {
  const [{ createIdentity }, session] = await Promise.all([import('../lib/identity.js'), import('../lib/session.js')]);
  const identity = await createIdentity({ lazy: true });
  await session.ensureSession(identity, { onProgress });
  return identity;
}

let opener = null;

// The Open my drive dialog: paste the key (or the key file's text) or pick the file; a locked key
// file asks for its passphrase. onOpened(identity) runs once the drive opens.
export function openDialog(onOpened) {
  opener?.remove();
  const text = h('textarea', { class: 'textarea mono', id: 'open-key', rows: '3', placeholder: t('drive.open.key_ph'), spellcheck: 'false', autocomplete: 'off', 'data-testid': 'restore-text' });
  const file = h('input', { class: 'input', type: 'file', id: 'open-file-in', accept: '.txt,text/plain', 'data-testid': 'restore-file' });
  const pass = h('input', { class: 'input', type: 'password', id: 'open-pass', autocomplete: 'current-password', 'data-testid': 'restore-passphrase' });
  const passField = h('div', { class: 'field', hidden: true }, h('label', { class: 'label', for: 'open-pass' }, t('drive.open.pass_label')), pass);
  const fileName = h('p', { class: 'small muted', 'aria-live': 'polite' });
  const errors = h('div', { 'aria-live': 'polite' });
  const go = button(t('drive.open.go'), { testid: 'restore-submit' });
  const locked = () => /Locked key:/.test(text.value);
  const sync = () => { passField.hidden = !locked(); };
  text.addEventListener('input', sync);
  file.addEventListener('change', async () => {
    const f = file.files[0];
    if (f) {
      text.value = await f.text();
      fileName.textContent = t('drive.open.file_read', { name: f.name });
    }
    file.value = '';
    sync();
  });
  go.addEventListener('click', async () => {
    errors.replaceChildren();
    go.disabled = true;
    try {
      const { restoreFromText } = await import('../lib/identity.js');
      const identity = await restoreFromText(text.value, pass.value, { lazy: true });
      closeModal(opener);
      onOpened(identity);
    } catch (e) {
      if (e?.code === 'locked') passField.hidden = false;
      errors.replaceChildren(e?.code === 'no_key' || e?.code === 'checksum'
        ? alert({ glyph: 'triangle-alert', title: t('drive.open.bad'), variant: 'destructive', role: 'alert', testid: 'error-banner' })
        : errorAlert(e));
    } finally {
      go.disabled = false;
    }
  });
  opener = dialogBox({
    id: 'open-drive', title: t('drive.open.title'), description: t('drive.open.desc'), testid: 'open-dialog',
    body: [h('div', { class: 'tabs' },
      h('div', { class: 'tabs-list', 'data-stretch': '' },
        h('button', { class: 'tabs-trigger', type: 'button', 'aria-controls': 'open-paste', 'data-state': 'active' }, icon('key-round'), t('drive.open.paste')),
        h('button', { class: 'tabs-trigger', type: 'button', 'aria-controls': 'open-file', 'data-testid': 'restore-open' }, icon('file-lock'), t('drive.open.file'))),
      h('div', { class: 'tabs-content', id: 'open-paste' }, h('div', { class: 'field' },
        h('label', { class: 'label', for: 'open-key' }, t('drive.open.key_label')), text)),
      h('div', { class: 'tabs-content', id: 'open-file' }, h('div', { class: 'field' },
        h('label', { class: 'label', for: 'open-file-in' }, t('drive.open.file_label')), file, fileName))),
    passField, errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go],
  });
  document.body.append(opener);
  init(opener);
  openModal(opener);
}

// The screen itself. onReady(identity, {made}) boots the drive.
export function renderStart(app, { onReady, make = false, open = false }) {
  const status = h('div', { class: 'stack', 'aria-live': 'polite' });
  const makeBtn = button(t('drive.start.make'), { glyph: 'plus', testid: 'drive-make', size: 'lg' });
  const openBtn = button(t('drive.start.open'), { variant: 'outline', glyph: 'key-round', testid: 'drive-open', size: 'lg' });
  const start = async () => {
    makeBtn.disabled = true;
    openBtn.disabled = true;
    const line = h('p', { class: 'muted row' }, icon('loader-circle'), h('span', {}, t('drive.start.making')));
    line.firstChild.classList.add('spinner');
    status.replaceChildren(line);
    try {
      onReady(await makeDrive(), { made: true });
    } catch (e) {
      makeBtn.disabled = false;
      openBtn.disabled = false;
      if (e?.code === 'rate_limited' && e.retryAfter) return wait(e.retryAfter);
      status.replaceChildren(errorAlert(e, { action: { label: t('drive.retry'), onClick: start } }));
    }
  };
  // Fifth pass: too many new drives from this network: a live countdown, then it tries again by itself.
  const wait = (seconds) => {
    const until = Date.now() + seconds * 1000;
    const text = h('span', { 'data-testid': 'make-wait' });
    const box = alert({ glyph: 'timer', title: t('drive.start.busy_h'), description: text, testid: 'error-banner', role: 'status' });
    box.dataset.code = 'rate_limited';
    status.replaceChildren(box);
    const tick = () => {
      if (!box.isConnected) return;
      const left = Math.ceil((until - Date.now()) / 1000);
      if (left <= 0) return start();
      text.replaceChildren(...lines(t('drive.start.busy', { wait: mmss(left) })));
      setTimeout(tick, 1000);
    };
    tick();
  };
  makeBtn.addEventListener('click', start);
  openBtn.addEventListener('click', () => openDialog((identity) => onReady(identity, { made: false })));
  app.replaceChildren(h('main', { class: 'start', id: 'main', tabindex: '-1', 'data-testid': 'drive-start' },
    h('div', { class: 'start-card' },
      h('a', { class: 'brand', href: '/' }, h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, icon('lock')), h('span', {}, BRAND)),
      h('h1', { class: 'h2' }, t('drive.start.title')),
      h('p', { class: 'lead' }, t('drive.start.lede')),
      h('div', { class: 'row wrap' }, makeBtn, openBtn),
      status,
      h('p', { class: 'small muted' }, t('drive.start.no_email')))));
  if (make) start();
  else if (open) openDialog((identity) => onReady(identity, { made: false }));
}
