// SPDX-License-Identifier: MIT
// What a row's menu does to the owner's own items (16-drive-design §2, §5, §7; 16-drive-architecture
// §2.4): Open (a file's name: the preview, ui/lightbox.js), Download, Rename, Move (it asks first when the
// folder has a link: "This shares it too"), Delete it after… (a day, a week or {max_days} days; the file
// then leaves and gets its receipt, C42),
// Move to trash with Undo (its links stop now; it can come back for {trash_days} days, C47), and, from the
// trash, bring back or delete now. Names change in this browser only: the server gets new ciphertext.
import { formatDate, t } from '../lib/i18n.js';
import { h, icon, init, lines, openModal, closeModal, toast } from './behaviors.js';
import { button, dialogBox, errorAlert, itemName, turning } from './drive-parts.js';
import { extensionAsk, extensionChange, selectName } from './rename.js';

const api = () => import('../lib/api-drive.js');

function show(box) {
  document.getElementById(box.id)?.remove();
  document.body.append(box);
  init(box);
  openModal(box);
  return box;
}

// A dialog's primary that shows its error inside the dialog and stays usable.
function primary(label, run, { variant = null, glyph = null, testid = null, errors }) {
  const b = button(label, { variant, glyph, testid });
  b.addEventListener('click', async () => {
    b.disabled = true;
    errors.replaceChildren();
    const stop = turning(b);
    try {
      await run();
    } catch (e) {
      errors.replaceChildren(errorAlert(e));
    } finally {
      stop();
      b.disabled = false;
    }
  });
  return b;
}

const one = (items, key, params = {}) => (items.length === 1 ? itemName(items[0]) : t(key, { count: items.length, ...params }));

async function download(drive, items) {
  const [{ openKept, fetchContent }, { saveFile }] = await Promise.all([import('../lib/open.js'), import('../lib/download.js')]);
  for (const it of items.filter((x) => !x.folder)) {
    const note = toast(t('drive.toast.opening', { name: itemName(it) }), { type: 'loading', duration: Infinity });
    try {
      const opened = await openKept(drive.identity, it.row, drive.headers());
      saveFile(await fetchContent(opened), it.meta.kind === 'text' ? 'note.txt' : it.meta.name);
      note.dismiss();
    } catch (e) {
      note.dismiss();
      toast(t('drive.toast.open_failed', { name: itemName(it) }), { type: 'error' });
    }
  }
}

// A file's name opens it in the preview (ui/lightbox.js): what it shows comes from the decrypted bytes, never the name,
// and Download is always there. The arrows move through the files listed beside it, as shown (search hides some).
// (A share made meanwhile reloads the drive's index: the item is looked up again by its id.)
async function open(drive, item, trigger) {
  const fresh = (f) => drive.index.get(f.it.id) ?? f.it;
  const saveName = (it) => (it.meta.kind === 'text' ? 'note.txt' : it.meta.name);
  const rows = [...(trigger?.closest('tbody')?.querySelectorAll('tr[data-id]') ?? [])].filter((tr) => !tr.hidden);
  let list = rows.map((tr) => drive.index.get(tr.dataset.id)).filter((x) => x && !x.folder);
  if (!list.includes(item)) list = [item];
  const [{ openLightbox }, { openKept, fetchContent }] = await Promise.all([import('./lightbox.js'), import('../lib/open.js')]);
  return openLightbox({
    files: list.map((it) => ({ name: itemName(it), editName: it.name, saveAs: saveName(it), size: it.meta.size ?? 0, it })),
    at: list.indexOf(item),
    read: async (f, onProgress) => fetchContent(await openKept(drive.identity, f.it.row, drive.headers()), { onProgress }),
    problem: (e) => errorAlert(e),
    returnFocus: trigger,
    refocus: (f) => document.querySelector(`[data-testid="file-row"][data-id="${CSS.escape(f.it.id)}"] [data-testid="file-open"]`),
    // What the row's menu has, from the preview's bar: Share (the dialog opens over it) and, where folders are on, Rename.
    share: (f, button) => import('./share-dialog.js').then((m) => m.openShare(drive, fresh(f), { trigger: button }))
      .catch((e) => toast(t('drive.oops'), { type: 'error', description: e?.message })),
    rename: drive.folders ? async (f, name) => {
      const it = fresh(f);
      try {
        await renameItem(drive, it, name);
      } catch (e) {
        toast(t('drive.oops'), { type: 'error', description: e?.message });
        throw e;
      }
      toast(t('drive.toast.renamed'), { type: 'success' });
      drive.render();   // the list behind the preview shows the new name too
      Object.assign(f, { it, editName: it.name, saveAs: saveName(it) });
      return itemName(it);
    } : null,
  });
}

// A new name: new ciphertext for the item's meta, never the name in the clear (the menu's Rename and the preview's name).
async function renameItem(drive, item, name) {
  const [{ renamedMeta }, { patchItem }] = await Promise.all([import('../lib/folder.js'), api()]);
  const metaCt = await renamedMeta(item, name);
  await patchItem(item.id, { meta_ct: metaCt }, drive.headers());
  item.meta = { ...item.meta, name };
  item.name = name;
  item.row = { ...item.row, meta_ct: metaCt };
}

// The field opens with the name before its extension selected (ui/rename.js); a new extension asks under it first.
function rename(drive, item) {
  const errors = h('div', {});
  const ask = h('div', {});
  const input = h('input', { class: 'input', type: 'text', id: 'rename-in', value: item.name, maxlength: '255', autocomplete: 'off', spellcheck: 'false', 'data-testid': 'rename-input', 'data-autofocus': '' });
  const save = async (name) => {
    await renameItem(drive, item, name);
    closeModal('rename');
    toast(t('drive.toast.renamed'), { type: 'success' });
    drive.render();
  };
  const answer = (name) => async () => {
    ask.replaceChildren();
    errors.replaceChildren();
    try {
      await save(name);
    } catch (e) {
      errors.replaceChildren(errorAlert(e));
    }
  };
  const go = primary(t('drive.rename.go'), async () => {
    const name = input.value.trim();
    if (!name || name === item.name) return closeModal('rename');
    const change = item.folder ? null : extensionChange(item.name, name);
    if (!change) return save(name);
    ask.replaceChildren(extensionAsk(change, { use: answer(name), keep: answer(change.keep) }));
    ask.querySelector('[data-testid="rename-ext-keep"]').focus();
  }, { errors, testid: 'rename-go' });
  const box = dialogBox({
    id: 'rename', title: t('drive.rename.title'), testid: 'rename-dialog',
    body: [h('div', { class: 'field' }, h('label', { class: 'label', for: 'rename-in' }, t('drive.rename.label')), input), ask, errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go],
  });
  box.querySelector('.dialog-title').removeAttribute('data-autofocus');   // the field takes the focus, at once, with its selection
  show(box);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
  input.addEventListener('input', () => ask.replaceChildren());
  selectName(input, { folder: item.folder });
  return box;
}

// Move: one radio card per folder (My drive first). A folder with a link that opens shares what lands
// in it, and the dialog says so before Move here (16-drive-design §5).
function move(drive, items) {
  const index = drive.index;
  const here = items[0].parentId ?? null;
  const targets = [null, ...index.folders().filter((f) => !items.some((it) => index.contains(it, f)))];
  let picked = targets.find((f) => (f?.id ?? null) !== here) ?? null;
  const radios = h('div', { class: 'radio-group choices', 'aria-label': t('drive.move.where'), 'data-testid': 'move-targets' },
    targets.map((f) => {
      const id = f?.id ?? '';
      const on = (f?.id ?? null) === (picked?.id ?? null);
      const radio = h('button', { class: 'radio', role: 'radio', type: 'button', 'aria-checked': String(on), 'data-value': id, 'aria-label': f ? index.pathName(f) : t('drive.side.mine') });
      const card = h('div', { class: 'choice', 'data-radio-card': '', 'data-state': on ? 'checked' : 'unchecked', 'data-testid': 'move-target', 'data-name': f ? index.pathName(f) : '' },
        h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon(f ? 'folder' : 'hard-drive')),
        h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, f ? index.pathName(f) : t('drive.side.mine'))), radio);
      card.addEventListener('click', (e) => { if (e.target !== radio) radio.click(); });
      return card;
    }));
  const warnText = h('div', { class: 'alert-description' });
  const warn = h('div', { class: 'alert', 'data-variant': 'warning', role: 'status', 'data-testid': 'move-shares' },
    icon('triangle-alert'), h('div', { class: 'alert-title' }, t('drive.move.shares')), warnText);
  const sync = () => {
    const shared = picked ? index.sharedAbove(picked) : null;
    warn.hidden = !shared || items.every((it) => index.sharedAbove(it)?.id === shared.id);
    warnText.replaceChildren(...(shared ? [h('span', {}, ...lines(t('drive.move.shares_d', { folder: itemName(shared) })))] : []));   // one grid item
  };
  radios.addEventListener('sh:change', (e) => {
    picked = e.detail.value ? index.get(e.detail.value) : null;
    for (const c of radios.children) c.dataset.state = c.querySelector('.radio').getAttribute('aria-checked') === 'true' ? 'checked' : 'unchecked';
    sync();
  });
  sync();
  const errors = h('div', {});
  const go = primary(t('drive.move.go'), async () => {
    const [{ moveBody }, { patchItem }] = await Promise.all([import('../lib/folder.js'), api()]);
    const from = items.map((it) => it.parentId ?? null);
    for (const it of items) {
      if ((it.parentId ?? null) === (picked?.id ?? null)) continue;
      await patchItem(it.id, await moveBody(it, picked), drive.headers());
      it.parentId = picked?.id ?? null;
    }
    closeModal('move');
    const back = async () => {
      for (const [i, it] of items.entries()) {
        const to = from[i] ? index.get(from[i]) : null;
        await patchItem(it.id, await moveBody(it, to), drive.headers());
        it.parentId = to?.id ?? null;
      }
      drive.render();
    };
    toast(t('drive.toast.moved', { folder: picked ? itemName(picked) : t('drive.side.mine') }), { type: 'success', action: { label: t('drive.toast.undo'), onClick: () => back().catch(() => toast(t('drive.oops'), { type: 'error' })) } });
    drive.render();
  }, { errors, testid: 'move-go' });
  return show(dialogBox({
    id: 'move', title: t('drive.move.title', { name: one(items, 'drive.sel.count') }), testid: 'move-dialog',
    body: [h('div', { class: 'scroll-area move-list' }, radios), warn, errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go],
  }));
}

// Delete it after… (PATCH /items/{id} {expires_at}); the file stays kept until that day.
function later(drive, item) {
  const max = drive.cfg.items?.max_delete_after_days ?? null;
  const options = [['day', 1, t('drive.later.day')], ['week', 7, t('drive.later.week')]];
  if (max) options.push(['max', max, t('drive.later.max', { max_days: max })]);
  let days = 7;
  const radios = h('div', { class: 'radio-group choices', 'aria-label': t('drive.later.title', { name: itemName(item) }) },
    options.map(([v, d, name]) => {
      const radio = h('button', { class: 'radio', role: 'radio', type: 'button', 'aria-checked': String(d === days), 'data-value': String(d), 'aria-label': name });
      const card = h('div', { class: 'choice', 'data-radio-card': '', 'data-state': d === days ? 'checked' : 'unchecked', 'data-testid': `later-${v}` },
        h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon('hourglass')), h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, name)), radio);
      card.addEventListener('click', (e) => { if (e.target !== radio) radio.click(); });
      return card;
    }));
  radios.addEventListener('sh:change', (e) => {
    days = Number(e.detail.value);
    for (const c of radios.children) c.dataset.state = c.querySelector('.radio').getAttribute('aria-checked') === 'true' ? 'checked' : 'unchecked';
  });
  const errors = h('div', {});
  const set = async (expiresAt) => {
    const { patchItem } = await api();
    const res = await patchItem(item.id, { expires_at: expiresAt }, drive.headers());
    item.row = { ...item.row, expires_at: res && 'expires_at' in res ? res.expires_at : expiresAt };
  };
  const go = primary(t('drive.later.go'), async () => {
    const before = item.row.expires_at ?? null;
    // The server takes at most max_days ahead by its own clock (and rounds up to the hour), so the
    // longest choice keeps a few minutes in hand for a clock that runs a little fast here.
    const at = Math.floor(Date.now() / 1000) + days * 86400 - (max && days >= max ? 300 : 0);
    await set(at);
    closeModal('later');
    toast(t('drive.later.set', { date: formatDate(at * 1000, { month: 'short', day: 'numeric' }) }), { type: 'success',
      action: { label: t('drive.toast.undo'), onClick: () => set(before).then(() => drive.render(), () => toast(t('drive.oops'), { type: 'error' })) } });
    drive.render();
  }, { variant: 'destructive', glyph: 'hourglass', errors, testid: 'later-go' });   // site v4: a delete, never lime
  const keep = item.row.expires_at ? primary(t('drive.later.keep'), async () => {
    await set(null);
    closeModal('later');
    drive.render();
  }, { variant: 'ghost', errors, testid: 'later-keep' }) : null;
  return show(dialogBox({
    id: 'later', title: t('drive.later.title', { name: itemName(item) }), description: t('drive.later.desc'), testid: 'delete-after',
    body: [radios, errors],
    footer: [keep, button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go].filter(Boolean),
  }));
}

async function setTrashed(drive, items, trashed) {
  const { patchItem } = await api();
  for (const it of items) await patchItem(it.id, { trashed }, drive.headers());
}

function trash(drive, items) {
  const days = drive.cfg.retention?.trash_days;
  const errors = h('div', {});
  const go = primary(t('drive.trash.go'), async () => {
    await setTrashed(drive, items, true);
    for (const it of items) drive.index.remove(it.id);
    closeModal('trash');
    toast(t('drive.toast.trashed', { count: items.length }), { action: { label: t('drive.toast.undo'), onClick: () => setTrashed(drive, items, false).then(() => drive.reload()).then(() => drive.render(), () => toast(t('drive.oops'), { type: 'error' })) } });
    drive.refreshMe().catch(() => null);
    drive.render();
  }, { variant: 'destructive', errors, testid: 'trash-go' });
  return show(dialogBox({
    id: 'trash', role: 'alertdialog', size: 'sm', title: t('drive.trash.title', { count: items.length }), testid: 'trash-dialog',
    description: days ? t('drive.trash.desc', { trash_days: days }) : null,
    media: h('span', { class: 'alert-media' }, icon('trash')),
    body: [errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '', 'data-cancel': '' }), go],
  }));
}

// Delete now (no trash on this deployment, or from the trash): the file leaves at once and its
// ciphertext is deleted within a minute; its receipt goes on the Tari chain (C42).
function remove(drive, items, { fromTrash = false } = {}) {
  const errors = h('div', {});
  const go = primary(t('drive.delete.go'), async () => {
    const { deleteItem } = await import('../lib/api.js');
    for (const it of items) {
      await deleteItem(it.id, drive.headers());
      drive.index.remove(it.id);
    }
    closeModal('delete');
    toast(t('drive.toast.deleted', { count: items.length }), { type: 'success' });
    drive.refreshMe().catch(() => null);
    drive.render();
  }, { variant: 'destructive', errors, testid: 'delete-go' });
  return show(dialogBox({
    id: 'delete', role: 'alertdialog', size: 'sm', title: t('drive.delete.title', { count: items.length }), testid: 'delete-dialog',
    description: t(fromTrash || !items.some((it) => it.folder) ? 'drive.delete.desc' : 'drive.delete.desc_folder'),
    media: h('span', { class: 'alert-media' }, icon('trash')),
    body: [errors],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '', 'data-cancel': '' }), go],
  }));
}

export async function menuAction(drive, value, items, trigger = null) {
  const list = items.filter(Boolean);
  if (!list.length) return null;
  if (value === 'open') return open(drive, list[0], trigger);
  if (value === 'download') return download(drive, list);
  if (value === 'rename') return rename(drive, list[0]);
  if (value === 'move') return move(drive, list);
  if (value === 'later') return later(drive, list[0]);
  if (value === 'trash') return trash(drive, list);
  if (value === 'delete') return remove(drive, list);
  if (value === 'purge') return remove(drive, list, { fromTrash: true });
  if (value === 'restore') {
    await setTrashed(drive, list, false);
    toast(t('drive.toast.restored', { count: list.length }), { type: 'success' });
    await drive.reload();
    return drive.render();
  }
  return null;
}
