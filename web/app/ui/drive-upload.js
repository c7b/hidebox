// SPDX-License-Identifier: MIT
// Uploads into the drive (16-drive-design §2 "Upload anywhere"; 16-drive-architecture §2.2): files and
// folders from the pickers, or dropped anywhere on a drive page ("Drop to lock and upload / Into
// {folder}"). Before any byte leaves: the count, each file's size for this drive, and the padded total
// against the space left. Then the folders top-down, then the files two at a time, each locked in this
// browser first (C32), photos without their location data (§4.13). The panel says Locking, Uploading,
// Locked and saved. Also New folder and Write a note.
import { formatBytes, t } from '../lib/i18n.js';
import { h, icon, init, openModal, closeModal } from './behaviors.js';
import { button, dialogBox, driveErrorText as errorText, errorAlert, itemName } from './drive-parts.js';

const AT_ONCE = 2;
let inputs = null;

// The folder an upload lands in: the open folder on My drive, the root elsewhere.
function target(drive) {
  const id = drive.route.view === 'mine' ? drive.route.folderId : null;
  return id ? drive.index.get(id) : null;
}

function pickers(drive) {
  if (inputs) return inputs;
  const files = h('input', { type: 'file', multiple: true, hidden: true, 'aria-hidden': 'true', tabindex: '-1', 'data-testid': 'upload-files-input' });
  const dir = h('input', { type: 'file', multiple: true, webkitdirectory: '', hidden: true, 'aria-hidden': 'true', tabindex: '-1', 'data-testid': 'upload-dir-input' });
  files.addEventListener('change', async () => {
    const list = [...files.files];
    files.value = '';
    if (list.length > maxFiles(drive)) return tooMany(drive, { code: 'too_many', max: maxFiles(drive) });
    return upload(drive, { files: list.map((file) => ({ path: [], file })), dirs: [] });
  });
  dir.addEventListener('change', async () => {
    const list = [...dir.files];
    dir.value = '';
    const { inputEntries } = await import('../lib/entries.js');
    try {
      await upload(drive, inputEntries(list, { maxFiles: maxFiles(drive) }));
    } catch (e) {
      tooMany(drive, e);
    }
  });
  document.body.append(files, dir);
  inputs = { files, dir };
  return inputs;
}

const maxFiles = (drive) => drive.cfg.folders?.max_upload_files ?? 500;

function show(box) {
  document.getElementById(box.id)?.remove();
  document.body.append(box);
  init(box);
  openModal(box);
  return box;
}

function tooMany(drive, e) {
  if (e?.code !== 'too_many') throw e;
  show(dialogBox({
    id: 'upload-stop', role: 'alertdialog', size: 'sm', title: t('drive.up.too_many', { max: e.max }), testid: 'upload-stop',
    media: h('span', { class: 'alert-media' }, icon('triangle-alert')),
    footer: [button(t('drive.done'), { variant: 'outline', 'data-close': '', 'data-cancel': '' })],
  }));
}

// "This needs {need}; you have {left} left": nothing is sent.
function noRoom(need, left) {
  show(dialogBox({
    id: 'upload-stop', role: 'alertdialog', size: 'sm', title: t('drive.up.no_room_title'), description: t('drive.up.no_room', { need: formatBytes(need), left: formatBytes(Math.max(0, left)) }),
    testid: 'upload-stop', media: h('span', { class: 'alert-media' }, icon('cloud')),
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '', 'data-cancel': '' }),
      h('a', { class: 'btn', href: '/drive/storage#more', 'data-nav': '', 'data-close': '' }, t('drive.side.more'))],
  }));
}

// --- the panel ------------------------------------------------------------------------------------

let panel = null;

function panelFor(count) {
  panel?.el.remove();
  const title = h('span', {}, t('drive.up.locking', { count }));
  const list = h('div', { class: 'uploads-list' });
  const live = h('p', { class: 'sr-only', 'aria-live': 'polite' }, t('drive.up.locking', { count }));
  const el = h('div', { class: 'card uploads', role: 'region', 'aria-label': t('drive.up.region'), 'data-testid': 'upload-panel' },
    h('div', { class: 'uploads-head' }, title, h('span', { class: 'spacer' }),
      button('', { variant: 'ghost', size: 'icon-sm', glyph: 'x', 'aria-label': t('drive.close'), onclick: () => el.remove() })),
    list, live);
  document.body.append(el);
  panel = { el, title, list, live };
  return panel;
}

function panelRow(p, name) {
  const bar = h('div', { class: 'progress', role: 'progressbar', 'aria-label': name, 'aria-valuemin': '0', 'aria-valuemax': '100' }, h('div', { class: 'progress-indicator' }));
  const stage = h('span', { class: 'stage' }, t('drive.up.lock_one'));
  const row = h('div', { class: 'upload-row', 'data-testid': 'upload-row' }, icon('file-lock'), h('span', { class: 'name' }, name), stage, bar);
  p.list.append(row);
  return {
    set(phase, fraction = 0) {
      const pct = Math.round((phase === 'uploading' ? 0.1 + 0.9 * fraction : phase === 'finishing' ? 1 : 0.1 * fraction) * 100);
      bar.style.setProperty('--value', String(pct));
      bar.setAttribute('aria-valuenow', String(pct));
      stage.textContent = t(phase === 'uploading' || phase === 'finishing' ? 'drive.up.send_one' : 'drive.up.lock_one');
      row.dataset.phase = phase;
      // a chunk on its way moves the bar only when it lands: until then it sweeps (ux-feedback-1)
      row.toggleAttribute('data-busy', (phase === 'uploading' && fraction === 0) || phase === 'finishing');
    },
    done() {
      row.removeAttribute('data-busy');
      row.dataset.done = '';
      bar.style.setProperty('--value', '100');
      stage.replaceChildren(icon('check', '3'), ' ', t('drive.up.ok'));
    },
    fail(e, retry) {
      row.removeAttribute('data-busy');
      row.dataset.failed = '';
      stage.replaceChildren(h('span', { class: 'failed' }, errorText(e)));
      if (retry) stage.append(' ', h('button', { class: 'link-btn', type: 'button', onclick: retry }, t('drive.retry')));
    },
  };
}

// --- uploading ------------------------------------------------------------------------------------

// plan: {files: [{path, file}], dirs: [path…]}; paths are relative to the folder the upload lands in.
export async function upload(drive, plan) {
  if (!plan.files.length && !plan.dirs.length) return;
  const { sizeStoredFor } = await import('../lib/format.js');
  const q = drive.me.quota;
  const left = q.limit_bytes - q.used_bytes - q.reserved_bytes;
  const need = plan.files.reduce((sum, f) => sum + sizeStoredFor(f.file.size), 0);
  if (need > left) return noRoom(need, left);
  const base = target(drive);
  const p = panelFor(plan.files.length);
  // Folders first, parents before children; each new folder's key stays in memory for its files.
  const made = new Map([['', base]]);
  if (plan.dirs.length && drive.folders) {
    const [{ newFolder }, { createFolder }] = await Promise.all([import('../lib/folder.js'), import('../lib/api-drive.js')]);
    for (const path of plan.dirs) {
      const key = path.join('/');
      if (made.has(key)) continue;
      const parent = made.get(path.slice(0, -1).join('/')) ?? null;
      const name = path[path.length - 1];
      try {
        made.set(key, await addFolder(drive, name, parent, { newFolder, createFolder }));
      } catch (e) {
        p.title.textContent = errorText(e);
        p.el.append(errorAlert(e));
        return null;
      }
    }
  }
  const [{ sealItem }, { fileSource, precheck, stripPhoto }] = await Promise.all([import('../lib/seal.js'), import('./sealing.js')]);
  const queue = plan.files.map((f) => ({ ...f, row: panelRow(p, f.file.name) }));
  let done = 0;
  let failed = 0;
  const one = async (job, resume = null) => {
    try {
      let source = await fileSource(job.file);
      const stop = await precheck(source, { limits: drive.me.limits, next: null, anonymous: false });
      if (stop) throw Object.assign(new Error(stop.code), { code: stop.code, details: { max_bytes: drive.me.limits.max_file_bytes } });
      job.row.set('stripping');
      source = (await stripPhoto(source, { keepOriginal: false })).source;
      const parent = made.get(job.path.join('/')) ?? base;
      await sealItem(source, {
        headers: drive.headers(), keepFor: drive.identity, parent: parent && drive.folders ? parent : null, resume,
        onPhase: (phase, fraction) => job.row.set(phase, fraction),
      });
      job.row.done();
      done++;
    } catch (e) {
      failed++;
      job.row.fail(e, e?.resume ? () => { failed--; one(job, e.resume).then(finish); } : null);
    }
  };
  const finish = async () => {
    if (done + failed < queue.length) return;
    p.title.textContent = t('drive.up.done', { count: done });
    p.live.textContent = t('drive.toast.uploaded', { count: done });
    await drive.reload().catch(() => null);
    drive.render();
  };
  let next = 0;
  const worker = async () => {
    while (next < queue.length) await one(queue[next++]);
  };
  await Promise.all(Array.from({ length: Math.min(AT_ONCE, queue.length) }, worker));
  if (!queue.length) {
    p.title.textContent = t('drive.up.folders_done', { count: plan.dirs.length });
    drive.render();
    return null;
  }
  return finish();
}

// A folder made in this browser: its key and name never leave it in clear.
async function addFolder(drive, name, parent, libs = null) {
  const [{ newFolder }, { createFolder }] = libs ? [libs, libs] : await Promise.all([import('../lib/folder.js'), import('../lib/api-drive.js')]);
  const f = await newFolder(drive.identity.vaultKey, name, parent);
  const res = await createFolder(f.body, drive.headers());
  const item = {
    id: res.item_id, folder: true, fk: f.fk, salt: f.salt, header: f.header, headerHash: f.headerHash, metaKey: f.metaKey, meta: f.meta,
    name, parentId: parent?.id ?? null,
    row: { item_id: res.item_id, kind: 'folder', retention: 'kept', size_stored: 0, chunk_count: 0, created_hour: Math.floor(Date.now() / 3600000) * 3600,
      expires_at: null, header: f.body.header, meta_ct: f.body.meta_ct, owner_wrap: f.body.owner_wrap, parent_id: f.body.parent_id, parent_wrap: f.body.parent_wrap ?? null, shares: [] },
  };
  drive.index.put(item);
  return item;
}

function newFolderDialog(drive) {
  const parent = target(drive);
  const input = h('input', { class: 'input', type: 'text', id: 'folder-name', maxlength: '255', autocomplete: 'off', spellcheck: 'false', value: t('drive.new.folder_default'), 'data-testid': 'folder-name', 'data-autofocus': '' });
  const errors = h('div', {});
  const go = button(t('drive.new.folder_go'), { testid: 'folder-create' });
  go.addEventListener('click', async () => {
    const name = input.value.trim();
    if (!name) return input.focus();
    go.disabled = true;
    errors.replaceChildren();
    try {
      await addFolder(drive, name, parent);
      closeModal('new-folder');
      drive.render();
    } catch (e) {
      errors.replaceChildren(errorAlert(e));
    } finally {
      go.disabled = false;
    }
  });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
  show(dialogBox({
    id: 'new-folder', title: t('drive.new.folder'), description: parent ? t('drive.new.folder_in', { folder: itemName(parent) }) : null, testid: 'new-folder-dialog',
    body: [h('div', { class: 'field' }, h('label', { class: 'label', for: 'folder-name' }, t('drive.new.folder_label')), input), errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go],
  }));
  requestAnimationFrame(() => input.select());
}

function noteDialog(drive) {
  const max = drive.cfg.text_max_chars;
  const text = h('textarea', { class: 'textarea', id: 'note-text', rows: '8', maxlength: String(max), 'data-testid': 'note-text', 'data-autofocus': '' });
  const errors = h('div', {});
  const go = button(t('drive.note.go'), { glyph: 'lock', testid: 'note-save' });
  go.addEventListener('click', async () => {
    if (!text.value.trim()) return text.focus();
    go.disabled = true;
    errors.replaceChildren();
    try {
      const { sealItem } = await import('../lib/seal.js');
      const parent = target(drive);
      await sealItem({ text: text.value }, { headers: drive.headers(), keepFor: drive.identity, parent: parent && drive.folders ? parent : null });
      closeModal('note');
      await drive.reload();
      drive.render();
    } catch (e) {
      errors.replaceChildren(errorAlert(e));
    } finally {
      go.disabled = false;
    }
  });
  show(dialogBox({
    id: 'note', title: t('drive.new.note'), description: t('drive.note.desc'), testid: 'note-dialog',
    body: [h('div', { class: 'field' }, h('label', { class: 'label', for: 'note-text' }, t('drive.note.label')), text), errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go],
  }));
}

export function newAction(drive, value) {
  const p = pickers(drive);
  if (value === 'files') return p.files.click();
  if (value === 'dir') return drive.folders ? p.dir.click() : p.files.click();
  if (value === 'folder') return newFolderDialog(drive);
  if (value === 'note') return noteDialog(drive);
  return null;
}

// Drop anywhere on a drive page. The overlay names the folder the files go into.
export async function wireDrop(drive) {
  pickers(drive);
  const entries = await import('../lib/entries.js');
  const where = h('p', { class: 'muted' });
  const overlay = h('div', { class: 'drop-overlay', hidden: true, 'aria-hidden': 'true', 'data-testid': 'drop-overlay' },
    h('div', { class: 'drop-overlay-inner' }, h('span', { class: 'dropzone-media' }, icon('upload')),
      h('p', { class: 'h3' }, t('drive.drop.title')), where));
  document.body.append(overlay);
  let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes('Files');
  const hide = () => {
    depth = 0;
    overlay.hidden = true;
  };
  addEventListener('dragenter', (e) => {
    if (!hasFiles(e) || document.querySelector('.dialog:not([hidden]), .sheet:not([hidden])')) return;
    depth++;
    const f = target(drive);
    where.textContent = t('drive.drop.to', { folder: f ? itemName(f) : t('drive.side.mine') });
    overlay.hidden = false;
    overlay.dataset.state = 'open';
  });
  addEventListener('dragleave', () => { if (--depth <= 0) hide(); });
  addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
  addEventListener('drop', async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    hide();
    const dropped = entries.dropEntries(e.dataTransfer);   // now, inside the event: its list is dead afterwards
    try {
      const plan = await entries.walkEntries(dropped, { maxFiles: maxFiles(drive) });
      if (!drive.folders) plan.dirs = [];
      await upload(drive, plan);
    } catch (err) {
      tooMany(drive, err);
    }
  });
}
