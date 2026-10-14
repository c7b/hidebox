// SPDX-License-Identifier: MIT
// My drive, a folder, Shared and Trash (16-drive-design §2): breadcrumbs, folder cards, the file table
// (name, rule, opens, ends, size, a menu on each row), picking several rows, search in place (names are
// decrypted here; nothing is sent, C43), and the empty drive: the brand moment, one primary (a folder
// on computers, files on phones: iOS has no folder picker) and the drive's Tari address with Copy.
import { formatBytes, t } from '../lib/i18n.js';
import { leavesAt, ruleOf } from '../lib/drive.js';
import { h, icon, init, setChecked, toast } from './behaviors.js';
import { alert, badges, button, endsText, fileIcon, itemName, leavesBadge, opensText, ruleBadge, shortDay } from './drive-parts.js';

const coarse = () => matchMedia('(pointer: coarse)').matches;

// The row menu: one element for the page, filled for the row that opened it (shadcn's DropdownMenu).
function rowMenu(drive) {
  document.getElementById('row-menu')?.remove();
  const item = (value, glyph, key, variant = null) => h('button', { class: 'menu-item', role: 'menuitem', type: 'button', 'data-value': value, 'data-variant': variant, 'data-testid': `menu-${value}` }, icon(glyph), t(key));
  const sep = () => h('div', { class: 'menu-separator', role: 'separator' });
  const menu = h('div', { class: 'menu', id: 'row-menu', hidden: true, 'data-align': 'end', 'data-testid': 'row-menu' });
  menu.fill = (it) => {
    const file = !it.folder;
    const folders = drive.folders;
    menu.replaceChildren(...[   // the entries a folder doesn't have are null: never append them (they'd read "null")
      item('share', 'share-2', 'drive.menu.share'),
      file ? item('once', 'flame', 'drive.menu.once') : null,
      item('activity', 'activity', 'drive.menu.activity'),
      sep(),
      file ? item('download', 'download', 'drive.menu.download') : null,
      folders ? item('rename', 'pencil', 'drive.menu.rename') : null,
      folders ? item('move', 'folder-input', 'drive.menu.move') : null,
      folders && file ? item('later', 'hourglass', 'drive.menu.later') : null,
      sep(),
      folders ? item('trash', 'trash', 'drive.menu.trash', 'destructive') : item('delete', 'trash', 'drive.menu.delete', 'destructive')].filter(Boolean));
  };
  menu.addEventListener('sh:select', (e) => {
    const it = drive.index.get(e.detail.trigger.dataset.id);
    if (it) setTimeout(() => act(drive, e.detail.value, [it], e.detail.trigger), 120);
  });
  document.body.append(menu);
  return menu;
}

// Every row and folder action, by name. Share and Copy a once link are the share dialog's (lane A2,
// ui/share-dialog.js); the rest live in drive-menu.js and activity.js.
export async function act(drive, value, items, trigger = null) {
  try {
    if (value === 'share' || value === 'once') {
      const m = await import('./share-dialog.js');
      return value === 'once' ? m.copyOnceLink(drive, items[0], { trigger }) : m.openShare(drive, items[0], { trigger });
    }
    if (value === 'activity') return (await import('./activity.js')).openActivity(drive, items[0]);
    return (await import('./drive-menu.js')).menuAction(drive, value, items);
  } catch (e) {
    toast(t('drive.oops'), { type: 'error', description: e?.message });
  }
}

function kebab(item) {
  return h('button', {
    class: 'btn', 'data-variant': 'ghost', 'data-size': 'icon-sm', type: 'button', 'data-menu-trigger': '', 'aria-controls': 'row-menu',
    'data-id': item.id, 'aria-label': t('drive.row.more', { name: itemName(item) }), 'data-testid': 'row-kebab',
  }, icon('ellipsis-vertical'));
}

function wireKebabs(root, menu, drive) {
  for (const b of root.querySelectorAll('[aria-controls="row-menu"]')) {
    const fill = () => menu.fill(drive.index.get(b.dataset.id) ?? { folder: false });
    b.addEventListener('click', fill, { capture: true });
    b.addEventListener('keydown', fill, { capture: true });
  }
  init(root);
}

// Fifth pass: a file or folder with no live link of its own, inside a folder that has one, is not private:
// whoever opens that folder's link sees it. Its badge says so (the closest such folder).
function sharedAncestor(drive, it) {
  for (let p = drive.index.get(it.parentId), guard = 0; p && guard < 32; p = drive.index.get(p.parentId), guard++) {
    if (!['private', 'ended'].includes(ruleOf(p).kind)) return p;
  }
  return null;
}

function ownBadge(drive, it, r = ruleOf(it)) {
  const anc = ['private', 'ended'].includes(r.kind) ? sharedAncestor(drive, it) : null;
  if (!anc) return ruleBadge(r);
  const pay = ruleOf(anc).kind === 'pay';
  return h('span', { class: 'badge', 'data-variant': 'secondary', 'data-rule': 'inherited', 'data-testid': 'inherited-badge',
    title: t(pay ? 'drive.rule.inherited_pay' : 'drive.rule.inherited_d', { name: itemName(anc) }) }, icon(pay ? 'coins' : 'share-2'), t('drive.rule.inherited'));
}

function folderCard(drive, f) {
  const href = drive.folderPath(f.id);
  const count = drive.index.children(f.id).length;
  return h('div', { class: 'folder', role: 'group', 'aria-label': itemName(f), 'data-id': f.id, 'data-testid': 'folder-card', 'data-name': itemName(f) },
    h('a', { class: 'folder-icon', href, 'data-nav': '', 'aria-label': t('drive.folder.open', { name: itemName(f) }) }, icon('folder')),
    h('a', { class: 'folder-body', href, 'data-nav': '', tabindex: '-1' },
      h('span', { class: 'folder-name' }, itemName(f)),
      h('span', { class: 'folder-meta' }, ownBadge(drive, f), h('span', {}, t('drive.folder.count', { count })))),
    kebab(f));
}

// One table row. In Shared, folders are rows too (their name opens them).
function fileRow(drive, it) {
  const r = ruleOf(it);
  const opens = opensText(r);
  const ends = endsText(r);
  const at = leavesAt(it);
  const meta = [opens, ends].filter(Boolean).join(' · ');
  const name = it.folder
    ? h('a', { class: 'name', href: drive.folderPath(it.id), 'data-nav': '' }, itemName(it))
    : h('button', { class: 'name link-plain', type: 'button', 'data-open': null, onclick: () => act(drive, 'download', [it]) }, itemName(it));
  const none = () => h('span', { class: 'sr-only' }, t('drive.state.none'));
  return h('tr', { 'data-id': it.id, 'data-testid': 'file-row', 'data-name': itemName(it), class: r.kind === 'ended' ? 'row-ended' : null },
    h('td', {}, h('button', { class: 'checkbox', type: 'button', 'aria-checked': 'false', 'aria-label': t('drive.sel.pick', { name: itemName(it) }) })),
    h('td', {}, h('div', { class: 'file-name' }, icon(fileIcon(it)),
      h('div', { class: 'file-text' }, name,
        h('span', { class: 'file-meta' }, ownBadge(drive, it, r), meta ? h('span', {}, meta) : null, at ? leavesBadge(at) : null)))),
    h('td', { class: 'col-wide' }, h('span', { class: 'badges' }, ownBadge(drive, it, r), at ? leavesBadge(at) : null)),
    h('td', { class: 'col-wide num-cell' }, opens || none()),
    h('td', { class: 'col-wide num-cell' }, ends || none()),
    h('td', { class: 'col-wide num-cell' }, it.folder ? none() : formatBytes(it.meta.size)),
    h('td', {}, kebab(it)));
}

function fileTable(drive, list, { label }) {
  const all = h('button', { class: 'checkbox', type: 'button', 'aria-checked': 'false', 'aria-label': t('drive.sel.all') });
  const tbody = h('tbody', {}, list.map((it) => fileRow(drive, it)));
  const count = h('span', { class: 'count', 'aria-live': 'polite' });
  const picked = () => [...tbody.querySelectorAll('tr')].filter((tr) => tr.querySelector('.checkbox')?.getAttribute('aria-checked') === 'true')
    .map((tr) => drive.index.get(tr.dataset.id)).filter(Boolean);
  const selbar = h('div', { class: 'selbar', hidden: true, role: 'toolbar', 'aria-label': t('drive.sel.bar'), 'data-testid': 'selbar' },
    button('', { variant: 'ghost', size: 'icon-sm', glyph: 'x', 'aria-label': t('drive.sel.clear'), onclick: () => clear() }),
    count,
    drive.folders ? button(t('drive.menu.move'), { variant: 'ghost', size: 'sm', glyph: 'folder-input', onclick: () => act(drive, 'move', picked()) }) : null,
    button(t('drive.menu.download'), { variant: 'ghost', size: 'sm', glyph: 'download', onclick: () => act(drive, 'download', picked().filter((x) => !x.folder)) }),
    button(t(drive.folders ? 'drive.menu.trash' : 'drive.menu.delete'), { variant: 'ghost', size: 'sm', glyph: 'trash', onclick: () => act(drive, drive.folders ? 'trash' : 'delete', picked()) }));
  const sync = () => {
    const n = picked().length;
    for (const tr of tbody.querySelectorAll('tr')) tr.dataset.state = tr.querySelector('.checkbox').getAttribute('aria-checked') === 'true' ? 'selected' : '';
    selbar.hidden = n === 0;
    count.textContent = t('drive.sel.count', { count: n });
    setChecked(all, n === 0 ? false : n === list.length ? true : 'mixed');
  };
  const clear = () => {
    for (const c of tbody.querySelectorAll('.checkbox')) setChecked(c, false);
    sync();
  };
  all.addEventListener('sh:change', () => {
    const on = all.getAttribute('aria-checked') === 'true';
    for (const c of tbody.querySelectorAll('.checkbox')) if (!c.closest('tr').hidden) setChecked(c, on);
    sync();
  });
  tbody.addEventListener('sh:change', sync);
  const col = (key, cls = 'col-wide') => h('th', { class: cls }, t(key));
  return [selbar,
    h('div', { class: 'files' }, h('div', { class: 'table-container' }, h('table', { class: 'table', 'aria-label': label, 'data-testid': 'file-table' },
      h('thead', {}, h('tr', {}, h('th', {}, all), col('drive.col.name', null), col('drive.col.rule'), col('drive.col.opens'), col('drive.col.ends'), col('drive.col.size'),
        h('th', {}, h('span', { class: 'sr-only' }, t('drive.col.actions'))))),
      tbody)))];
}

// Search: hide what doesn't match, here (C43).
function filterable(page, drive) {
  const apply = (q) => {
    for (const el of page.querySelectorAll('[data-name]')) el.hidden = Boolean(q) && !el.dataset.name.toLowerCase().includes(q);
    const none = page.querySelector('[data-no-match]');
    if (none) none.hidden = !q || Boolean(page.querySelector('[data-name]:not([hidden])'));
  };
  const on = (e) => apply(e.detail);
  document.addEventListener('drive:filter', on);
  page.addEventListener('drive:gone', () => document.removeEventListener('drive:filter', on), { once: true });
  apply(drive.query);
}

function leave(page) {
  page.dispatchEvent(new CustomEvent('drive:gone'));
}

// The key reminder: an outline action, never a primary (C17-k), until the key is saved.
function keyReminder(drive) {
  if (drive.identity.keySaved) return null;
  const save = button(t('drive.make.file'), { variant: 'outline', size: 'sm', glyph: 'download', testid: 'key-reminder-save' });
  save.addEventListener('click', async () => (await import('./drive-account.js')).openKeyDialog(drive));
  return h('div', { class: 'alert', role: 'note', 'data-testid': 'key-banner' }, icon('key-round'),
    h('div', { class: 'alert-title' }, t('drive.acct.key')),
    h('div', { class: 'alert-description' }, h('p', {}, t('drive.make.save')), h('div', { class: 'row' }, save)));
}

// The drive's Tari address with Copy (filled once the Tari keys load after the first render).
export function tariRow(drive) {
  const address = h('span', { class: 'mono small', 'data-testid': 'locker-address' });
  const copy = button(t('drive.copy'), { variant: 'ghost', size: 'sm', glyph: 'copy', testid: 'copy-address', disabled: true });
  const fill = () => {
    const loc = drive.identity.locker;
    if (!loc) return;
    address.textContent = loc.address;
    copy.disabled = false;
  };
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(drive.identity.locker.address);
      toast(t('drive.toast.addr'), { type: 'success' });
    } catch {
      toast(t('error.clipboard'), { type: 'error' });
    }
  });
  fill();
  if (!drive.identity.locker) document.addEventListener('drive:ootle', fill, { once: true });
  return h('div', { class: 'tari-row' }, icon('wallet'),
    h('div', { class: 'stack' }, h('span', { class: 'label' }, t('drive.make.address')), address,
      h('span', { class: 'small muted' }, t('drive.make.address_hint'))),
    copy);
}

function emptyDrive(drive, folder) {
  const pickFiles = () => document.dispatchEvent(new CustomEvent('drive:new', { detail: 'files' }));
  const pickDir = () => document.dispatchEvent(new CustomEvent('drive:new', { detail: 'dir' }));
  const phone = coarse() || !drive.folders;
  const primary = phone ? button(t('drive.empty.upload'), { glyph: 'upload', onclick: pickFiles, testid: 'empty-upload' })
    : button(t('drive.empty.dir'), { glyph: 'folder-up', onclick: pickDir, testid: 'empty-upload-dir' });
  const second = phone
    ? (drive.folders ? button(t('drive.new.folder'), { variant: 'outline', glyph: 'folder-plus', onclick: () => document.dispatchEvent(new CustomEvent('drive:new', { detail: 'folder' })) }) : null)
    : button(t('drive.empty.upload'), { variant: 'outline', glyph: 'upload', onclick: pickFiles, testid: 'empty-upload' });
  const art = folder
    ? h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('folder-open'))
    : h('div', { class: 'empty-art', 'aria-hidden': 'true' }, h('span', { class: 'ea-file ea-l' }, icon('file-image')),
      h('span', { class: 'brand-mark ea-mark' }, icon('lock')), h('span', { class: 'ea-file ea-r' }, icon('file-text')));
  return h('div', { class: 'empty', 'data-testid': 'drive-empty' },
    h('div', { class: 'empty-header' }, art,
      h('h2', { class: 'empty-title', id: 'files-h' }, t(folder ? 'drive.empty.folder_title' : 'drive.empty.title')),
      h('p', { class: 'empty-description' }, t(coarse() ? 'drive.empty.desc_tap' : 'drive.empty.desc'))),
    h('div', { class: 'empty-content' }, h('div', { class: 'row wrap' }, primary, second), folder ? null : tariRow(drive)));
}

function crumbs(drive, folder) {
  const path = drive.index.path(folder.id);
  const sep = () => h('li', { class: 'crumb-sep', role: 'presentation', 'aria-hidden': 'true' }, icon('chevron-right'));
  return h('nav', { class: 'breadcrumb', 'aria-label': t('drive.crumbs'), 'data-testid': 'breadcrumbs' }, h('ol', {},
    h('li', {}, h('a', { href: '/drive', 'data-nav': '' }, t('drive.side.mine'))),
    path.slice(0, -1).map((f) => [sep(), h('li', {}, h('a', { href: drive.folderPath(f.id), 'data-nav': '' }, itemName(f)))]),
    sep(),
    h('li', {}, h('span', { 'aria-current': 'page' }, h('h1', { class: 'h2' }, itemName(folder))))));
}

// My drive, or one folder of it.
export async function renderMine(drive, page) {
  await drive.ready();
  leave(page);
  const { folderId } = drive.route;
  const folder = folderId ? drive.index.get(folderId) : null;
  if (folderId && !folder) {
    page.replaceChildren(alert({ glyph: 'folder', title: t('drive.folder.missing'), testid: 'folder-missing' }),
      h('div', {}, h('a', { class: 'btn', 'data-variant': 'outline', href: '/drive', 'data-nav': '' }, t('drive.side.mine'))));
    return;
  }
  if (folder) drive.setTitle(itemName(folder));
  const children = drive.index.children(folderId);
  const folders = children.filter((it) => it.folder);
  const files = children.filter((it) => !it.folder);
  const menu = rowMenu(drive);
  const head = h('div', { class: 'page-head' }, folder ? crumbs(drive, folder) : h('h1', { class: 'h2' }, t('drive.side.mine')),
    folder ? badges(folder) : null,
    folder ? button(t('drive.share'), { variant: 'outline', glyph: 'share-2', testid: 'folder-share', onclick: (e) => act(drive, 'share', [folder], e.currentTarget) }) : null);
  const parts = [head, keyReminder(drive)];
  if (!children.length) {
    parts.push(h('section', { 'aria-labelledby': 'files-h' }, emptyDrive(drive, folder)));
  } else {
    if (folders.length) {
      parts.push(h('section', { 'aria-labelledby': 'folders-h' },
        h('h2', { class: 'section-label', id: 'folders-h' }, t('drive.folders')),
        h('div', { class: 'folder-grid' }, folders.map((f) => folderCard(drive, f)))));
    }
    if (files.length) {
      parts.push(h('section', { 'aria-labelledby': 'files-h' },
        h('h2', { class: 'section-label', id: 'files-h' }, t('drive.files')),
        fileTable(drive, files, { label: t('drive.files') })));
    }
    parts.push(h('p', { class: 'muted', 'data-no-match': '', hidden: true }, t('drive.search.none')));
  }
  page.replaceChildren(...parts.filter(Boolean));
  wireKebabs(page, menu, drive);
  filterable(page, drive);
  page.dataset.folder = folderId ?? '';
}

// Files and folders with a link that still opens.
export async function renderShared(drive, page) {
  await drive.ready();
  leave(page);
  const list = drive.index.shared();
  const menu = rowMenu(drive);
  const head = h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.shared')));
  if (!list.length) {
    page.replaceChildren(head, h('div', { class: 'empty', 'data-testid': 'shared-empty' },
      h('div', { class: 'empty-header' }, h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('share-2')),
        h('h2', { class: 'empty-title' }, t('drive.shared.empty')), h('p', { class: 'empty-description' }, t('drive.shared.empty_d')))));
    return;
  }
  page.replaceChildren(head, h('p', { class: 'page-desc' }, t('drive.shared.desc')),
    h('section', { 'aria-label': t('drive.side.shared') }, fileTable(drive, list, { label: t('drive.side.shared') })),
    h('p', { class: 'muted', 'data-no-match': '', hidden: true }, t('drive.search.none')));
  wireKebabs(page, menu, drive);
  filterable(page, drive);
}

// The trash (server state, 16-drive-architecture §2.4): bring back, or delete now. Its files still
// use space and leave after {trash_days} days (C47).
export async function renderTrash(drive, page) {
  leave(page);
  const head = h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.trash')));
  const days = drive.cfg.retention?.trash_days ?? 30;
  let list = [];
  if (drive.folders) {
    const { listAll } = await import('../lib/api-drive.js');
    list = await drive.index.openList(await listAll({ view: 'trash' }, drive.headers()));
  }
  if (!list.length) {
    page.replaceChildren(head, h('div', { class: 'empty', 'data-testid': 'trash-empty' },
      h('div', { class: 'empty-header' }, h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('trash')),
        h('h2', { class: 'empty-title' }, t('drive.trash.empty')),
        h('p', { class: 'empty-description' }, drive.folders ? t('drive.trash.empty_d', { trash_days: days }) : t('drive.trash.off')))));
    return;
  }
  const rows = list.map((it) => {
    const restore = button(t('drive.trash.restore'), { variant: 'outline', size: 'sm', glyph: 'rotate-ccw', testid: 'trash-restore' });
    const now = button(t('drive.trash.delete_now'), { variant: 'ghost', size: 'sm', testid: 'trash-delete' });
    restore.addEventListener('click', () => act(drive, 'restore', [it]));
    now.addEventListener('click', () => act(drive, 'purge', [it]));
    const gone = (it.row.trashed_at ?? 0) + days * 86400;
    return h('tr', { 'data-id': it.id, 'data-testid': 'trash-row', 'data-name': itemName(it) },
      h('td', {}, h('div', { class: 'file-name' }, icon(fileIcon(it)), h('div', { class: 'file-text' }, h('span', { class: 'name' }, itemName(it)),
        h('span', { class: 'file-meta' }, t('drive.trash.leaves', { date: shortDay(gone) }))))),
      h('td', { class: 'col-wide num-cell' }, t('drive.trash.leaves', { date: shortDay(gone) })),
      h('td', { class: 'col-wide num-cell' }, it.folder ? '' : formatBytes(it.meta.size)),
      h('td', {}, h('div', { class: 'row end' }, restore, now)));
  });
  page.replaceChildren(head, h('p', { class: 'page-desc' }, t('drive.trash.desc', { trash_days: days })),
    h('div', { class: 'files' }, h('div', { class: 'table-container' }, h('table', { class: 'table trash-table', 'aria-label': t('drive.side.trash') },
      h('thead', {}, h('tr', {}, h('th', {}, t('drive.col.name')), h('th', { class: 'col-wide' }, t('drive.col.leaves')), h('th', { class: 'col-wide' }, t('drive.col.size')),
        h('th', {}, h('span', { class: 'sr-only' }, t('drive.col.actions'))))),
      h('tbody', {}, rows)))),
    h('p', { class: 'muted', 'data-no-match': '', hidden: true }, t('drive.search.none')));
  filterable(page, drive);
}
