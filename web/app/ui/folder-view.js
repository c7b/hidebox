// SPDX-License-Identifier: MIT
// The folder viewer (16-drive-design §5, 16-drive-architecture §2.5), lane app2: what someone sees after
// opening a folder link, in the drive's look. Every name below the folder is opened in this browser from
// the folder's key. One open is one visit of retention.ticket_s, shown as a countdown; inside it, Open a
// file (a preview for pictures, video, sound and plain text), Save one, or Download all as one ZIP built
// here (lib/zip.js) when the folder fits folders.zip_max_bytes (on phones folders.zip_max_bytes_phone);
// beyond that, one by one. Used by the link page (/s/<id>, view.html) and by the drive's Received.
import { BRAND, formatBytes, formatDate, t } from '../lib/i18n.js';
import { checkRisky, sanitizeFileName } from '../lib/filetype.js';
import { saveFile } from '../lib/download.js';
import { filesBelow, pathTo, readNode } from '../lib/folder-open.js';
import { h, icon, init, openModal } from './behaviors.js';

const MiB = 1024 * 1024;
const TICK_MS = 15000;
const nowS = () => Math.floor(Date.now() / 1000);

// Phones (a coarse pointer, or iOS that says it is a Mac) keep the ZIP smaller: it is built in memory.
export function isPhone() {
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  return ios || matchMedia('(pointer: coarse)').matches;
}

export function zipCap(cfg) {
  const f = cfg.folders ?? {};
  return isPhone() ? (f.zip_max_bytes_phone ?? 500 * MiB) : (f.zip_max_bytes ?? 2048 * MiB);
}

const spinner = () => {
  const s = icon('loader-circle');
  s.classList.add('spinner');
  return s;
};

const btn = (label, { variant = null, size = null, glyph = null, testid = null, ...rest } = {}) =>
  h('button', { class: 'btn', type: 'button', 'data-variant': variant, 'data-size': size, 'data-testid': testid, ...rest }, glyph ? icon(glyph) : null, label);

function fileGlyph(node) {
  const type = String(node.meta.type || '').toLowerCase();
  if (node.folder) return 'folder';
  if (node.meta.kind === 'text' || type.startsWith('text/') || type === 'application/pdf') return 'file-text';
  if (type.startsWith('image/')) return 'file-image';
  if (type.startsWith('video/')) return 'file-video-camera';
  if (type.startsWith('audio/')) return 'file-play';
  return 'file';
}

const nameOf = (node) => (node.meta.kind === 'text' ? t('fv.note') : sanitizeFileName(node.name));

// The visit's clock: the ticket's lifetime counted from the moment this browser got it.
function visitClock(cfg, opened) {
  const span = cfg.retention?.ticket_s ?? 1800;
  const serverLeft = opened.ticketExpiresAt ? Math.min(span, Math.max(0, opened.ticketExpiresAt - nowS())) : span;
  // A clock far off from ours would make serverLeft meaningless; the full span is the honest fallback.
  const left = serverLeft > 0 ? serverLeft : span;
  return nowS() + left;
}

// -> {el, stop()}: the folder, its files and the visit. opts: {cfg, heading ('h1' on the link page,
// 'h2' in a dialog), onSaveToDrive (Received: re-lock the files as the drive's own)}
export function folderPanel(opened, { cfg, heading = 'h1', onSaveToDrive = null } = {}) {
  const root = opened.root;
  let at = root;
  const deadline = visitClock(cfg, opened);
  let ended = false;
  const all = filesBelow(root);
  const total = all.reduce((sum, f) => sum + f.node.size, 0);
  const visit = h('p', { class: 'visit small muted', 'data-testid': 'fv-visit', role: 'timer', 'aria-live': 'off' });
  const left = opened.viewsLeft === null || opened.viewsLeft === undefined ? null
    : h('p', { class: 'small muted', 'data-testid': 'view-views-left', 'data-left': String(opened.viewsLeft) },
      opened.burned || opened.viewsLeft === 0 ? t('fv.last') : t('fv.left', { count: opened.viewsLeft }));
  const errors = h('div', { 'aria-live': 'polite' });
  const crumbs = h('nav', { class: 'breadcrumb', 'aria-label': t('fv.crumbs'), 'data-testid': 'fv-crumbs' });
  const tbody = h('tbody', {});
  const table = h('div', { class: 'files', 'data-plain': '' }, h('div', { class: 'table-container' }, h('table', { class: 'table' },
    h('thead', {}, h('tr', {}, h('th', {}, t('drive.col.name')), h('th', { class: 'col-wide' }, t('drive.col.size')),
      h('th', {}, h('span', { class: 'sr-only' }, t('drive.col.actions'))))),
    tbody)));
  const empty = h('div', { class: 'empty', hidden: true }, h('div', { class: 'empty-header' },
    h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('folder')), h('p', { class: 'empty-title' }, t('fv.empty'))));

  // Download all, or why not.
  let zipButton = null;
  let tooBig = null;
  if (all.length) {
    if (total <= zipCap(cfg) && all.length < 1000) {
      zipButton = btn(t('fv.save_all'), { glyph: 'download', testid: 'fv-zip', onclick: () => downloadAll() });
    } else {
      tooBig = h('p', { class: 'small muted', 'data-testid': 'fv-one-by-one' }, t('fv.one_by_one'));
    }
  }
  const keep = onSaveToDrive && all.length
    ? btn(t('fv.keep'), { variant: zipButton ? 'outline' : null, glyph: 'hard-drive', testid: 'fv-keep', onclick: (e) => keepAll(e.currentTarget) }) : null;
  const HeadTag = heading;
  const el = h('section', { class: 'fv stack', 'data-testid': 'folder-view', 'data-state': 'open', 'aria-labelledby': 'fv-title' },
    h('div', { class: 'fv-head' },
      h('div', { class: 'stack fv-title' },
        h(HeadTag, { class: heading === 'h1' ? 'h2' : 'h3', id: 'fv-title', tabindex: '-1' }, root.name || t('fv.folder')),
        h('p', { class: 'muted', 'data-testid': 'fv-count' }, t(total < 1024 ? 'fv.count_tiny' : 'fv.count', { count: all.length, size: formatBytes(total) }))),
      h('div', { class: 'row wrap fv-actions' }, keep, zipButton)),
    h('div', { class: 'row wrap fv-status' }, visit, left),
    tooBig, errors, crumbs, table, empty,
    opened.skipped ? h('p', { class: 'small muted' }, t('fv.skipped', { count: opened.skipped })) : null,
    h('p', { class: 'small muted path-line' }, icon('info'), h('span', {}, t('fv.scan'))));

  function draw() {
    const path = pathTo(opened, at);
    const sep = () => h('li', { class: 'crumb-sep', role: 'presentation', 'aria-hidden': 'true' }, icon('chevron-right'));
    crumbs.hidden = path.length < 2;
    crumbs.replaceChildren(h('ol', {}, path.map((n, i) => [i ? sep() : null, h('li', {},
      i === path.length - 1 ? h('span', { 'aria-current': 'page' }, n.name || t('fv.folder'))
        : h('button', { type: 'button', class: 'link-plain', onclick: () => { at = n; draw(); } }, n.name || t('fv.folder')))])));
    tbody.replaceChildren(...at.children.map(row));
    table.hidden = !at.children.length;
    empty.hidden = Boolean(at.children.length);
  }

  function row(node) {
    const name = nameOf(node);
    const risk = node.folder ? null : checkRisky(name, null);
    const open = h('button', { type: 'button', class: 'link-plain name', 'data-testid': 'fv-open', onclick: () => (node.folder ? (at = node, draw()) : preview(node)) }, name);
    const meta = node.folder ? t('fv.items', { count: node.children.length }) : formatBytes(node.size);
    return h('tr', { 'data-testid': 'fv-row', 'data-name': name, 'data-kind': node.folder ? 'folder' : 'file' },
      h('td', {}, h('div', { class: 'file-name' }, icon(fileGlyph(node)),
        h('div', { class: 'file-text' }, open,
          h('span', { class: 'file-meta' }, h('span', {}, meta)),
          risk?.risky ? h('span', { class: 'small fv-warn', 'data-testid': 'fv-program' }, icon('triangle-alert'), t('fv.program')) : null))),
      h('td', { class: 'col-wide num-cell' }, node.folder ? meta : formatBytes(node.size)),
      h('td', {}, node.folder
        ? btn(null, { variant: 'ghost', size: 'icon-sm', glyph: 'chevron-right', 'aria-label': t('fv.open_folder', { name }), onclick: () => { at = node; draw(); } })
        : btn(t('fv.save'), { variant: 'outline', size: 'sm', glyph: 'download', testid: 'fv-save', 'aria-label': t('fv.save_one', { name }), onclick: (e) => saveOne(node, e.currentTarget) })));
  }

  async function read(node, onProgress) {
    if (ended) throw Object.assign(new Error('visit over'), { code: 'visit_over' });
    return readNode(opened, node, { onProgress });
  }

  async function busy(button, run, label) {
    const before = [...button.childNodes];
    button.disabled = true;
    button.replaceChildren(spinner(), label);
    errors.replaceChildren();
    try {
      await run((text) => { button.lastChild.textContent = text; });
    } catch (e) {
      errors.replaceChildren(await problem(e));
    } finally {
      button.replaceChildren(...before);
      button.disabled = ended;
    }
  }

  async function problem(e) {
    const { errorAlert } = await import('./drive-parts.js');
    if (e?.code === 'visit_over') return h('div', { class: 'alert', role: 'alert' }, icon('timer'), h('div', { class: 'alert-title' }, t('fv.over')));
    // 403 not_in_folder: the owner moved the file out (or deleted it) during this visit.
    if (e?.code === 'not_in_folder') return h('div', { class: 'alert', 'data-variant': 'destructive', role: 'alert', 'data-testid': 'error-banner', 'data-code': 'not_in_folder' },
      icon('triangle-alert'), h('div', { class: 'alert-title' }, t('fv.moved')));
    return errorAlert(e);
  }

  function saveOne(node, button) {
    return busy(button, async () => saveFile(await read(node), nameOf(node)), t('fv.opening'));
  }

  function downloadAll() {
    return busy(zipButton, async (say) => {
      const { ZipWriter, zipPath } = await import('../lib/zip.js');
      const zip = new ZipWriter();
      for (const f of opened.folders) {
        const names = pathTo(opened, f).slice(1).map((n) => n.name);
        if (!f.children.length) zip.addFolder(zipPath(names), { mtime: f.meta.mtime });
      }
      let done = 0;
      for (const { node, path } of all) {
        const parts = await read(node, (x) => say(t('fv.zipping', { percent: Math.floor(((done + x * node.size) / Math.max(1, total)) * 100) })));
        zip.addFile(zipPath([...path, nameOf(node)]), parts, { mtime: node.meta.mtime });
        done += node.size;
      }
      saveFile([zip.finish()], `${sanitizeFileName(root.name || t('fv.folder'))}.zip`);
    }, t('fv.zipping', { percent: 0 }));
  }

  function keepAll(button) {
    return busy(button, async () => {
      const files = [];
      for (const { node, path } of all) {
        const parts = await read(node);
        files.push({ path: [root.name || t('fv.folder'), ...path], name: nameOf(node), parts, type: node.meta.type, mtime: node.meta.mtime });
      }
      await onSaveToDrive({ folder: root.name || t('fv.folder'), files, dirs: opened.folders.map((f) => [root.name || t('fv.folder'), ...pathTo(opened, f).slice(1).map((n) => n.name)]) });
    }, t('fv.keeping'));
  }

  async function preview(node) {
    const name = nameOf(node);
    const body = h('div', { class: 'stack fv-preview-body', 'data-state': 'loading' }, h('p', { class: 'row muted' }, spinner(), t('fv.opening')));
    const box = h('div', { class: 'dialog', role: 'dialog', id: 'fv-preview', hidden: true, 'data-size': 'lg', 'data-testid': 'fv-preview' },
      h('div', { class: 'dialog-header' }, h('h2', { class: 'dialog-title', tabindex: '-1', 'data-autofocus': '' }, name),
        h('p', { class: 'dialog-description' }, formatBytes(node.size))),
      body,
      h('div', { class: 'dialog-footer' }, btn(t('drive.close'), { variant: 'outline', 'data-close': '' })),
      h('button', { class: 'dialog-close', type: 'button', 'data-close': '', 'aria-label': t('drive.close') }, icon('x')));
    document.getElementById('fv-preview')?.remove();
    document.body.append(box);
    init(box);
    let revoke = null;
    openModal(box, { onClose: () => { revoke?.(); setTimeout(() => box.remove(), 600); } });
    try {
      const parts = await read(node);
      const risk = checkRisky(name, parts[0]?.subarray(0, 0x8006) ?? null);
      const { makePreview } = await import('../lib/preview.js');
      const shown = risk.risky || risk.active ? null : makePreview(parts, node.meta, { label: name });
      revoke = shown?.revoke ?? null;
      const save = btn(t('fv.save'), { glyph: 'download', testid: 'fv-preview-save', onclick: () => saveFile(parts, name) });
      body.dataset.state = 'open';
      body.replaceChildren(
        shown ? h('div', { class: 'fv-media' }, shown.el) : h('div', { class: 'locked-note' }, icon(fileGlyph(node)), t(risk.risky ? 'fv.program' : 'fv.no_preview')),
        h('div', { class: 'row' }, save));
    } catch (e) {
      body.dataset.state = 'error';
      body.replaceChildren(await problem(e));
    }
  }

  function tick() {
    const secs = deadline - nowS();
    visit.dataset.left = String(Math.max(0, secs));
    if (secs > 0) {
      visit.replaceChildren(icon('timer'), h('span', {}, t('fv.visit', { count: Math.ceil(secs / 60) })));
      return;
    }
    ended = true;
    el.dataset.state = 'ended';
    visit.replaceChildren(icon('timer'), h('span', {}, t('fv.over')));
    for (const b of el.querySelectorAll('[data-testid="fv-save"], [data-testid="fv-zip"], [data-testid="fv-keep"]')) b.disabled = true;
    stop();
  }
  const timer = setInterval(tick, TICK_MS);
  const stop = () => clearInterval(timer);
  draw();
  tick();
  return { el, stop };
}

// ---------- the link page (/s/<id>, view.html) ----------

// view.html carries the drive's stylesheets switched off (data-drive); a folder link switches the page
// to them, so a folder looks like the drive it came from. The ghost page's header and footer go.
// The link pages' one way to the drive: Open my drive when this browser holds one (html[data-has-drive],
// painted by theme.js from the flag identity.js keeps), else Make your own drive.
export const ownDrive = (attrs = {}) => (document.documentElement.hasAttribute('data-has-drive')
  ? h('a', { class: 'btn', 'data-variant': 'outline', href: '/drive', ...attrs }, t('nav.open_locker'))
  : h('a', { class: 'btn', 'data-variant': 'outline', href: '/drive?make', ...attrs }, t('fv.own')));

export async function driveLook() {
  if (document.body.dataset.look === 'drive') return;
  const sheets = [...document.querySelectorAll('link[rel="stylesheet"]')];
  const drive = sheets.filter((l) => l.hasAttribute('data-drive'));
  await Promise.all(drive.map((l) => new Promise((resolve) => {
    const timer = setTimeout(resolve, 3000);
    const done = () => { clearTimeout(timer); resolve(); };
    l.addEventListener('load', done, { once: true });
    l.addEventListener('error', done, { once: true });
    l.disabled = false;
    if (l.sheet && l.sheet.cssRules) done();
  })));
  if (drive.length) for (const l of sheets) if (!l.hasAttribute('data-drive') && !l.hasAttribute('data-both')) l.disabled = true;
  document.body.dataset.look = 'drive';
  for (const el of document.querySelectorAll('body > header, body > footer, body > .site-header, body > .site-footer')) el.hidden = true;
  const skip = document.querySelector('.skip-link');
  if (skip) {
    skip.dataset.pageClass = skip.className;
    skip.className = 'skip sr-only';
  }
  const main = document.getElementById('main');
  if (main) {
    main.dataset.pageClass = main.className;
    main.className = 'fv-page';
    if (!document.querySelector('.fv-top')) {
      main.before(h('header', { class: 'fv-top' },
        h('a', { class: 'brand', href: '/' }, h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, icon('hidebox')),
          h('span', { class: 'brand-text' }, h('span', {}, BRAND))),
        ownDrive({ 'data-size': 'sm' })));
    }
  }
}

// Back to the link page's own look (a folder link that couldn't open shows the page's usual states).
export function ghostLook() {
  if (document.body.dataset.look !== 'drive') return;
  for (const l of document.querySelectorAll('link[rel="stylesheet"]')) l.disabled = l.hasAttribute('data-drive') && !l.hasAttribute('data-both');
  delete document.body.dataset.look;
  for (const el of document.querySelectorAll('body > header, body > footer, body > .site-header, body > .site-footer')) {
    if (!el.classList.contains('fv-top')) el.hidden = false;
  }
  document.querySelector('.fv-top')?.remove();
  for (const el of [document.getElementById('main'), document.querySelector('.skip[data-page-class]')]) {
    if (el && el.dataset.pageClass !== undefined) {
      el.className = el.dataset.pageClass;
      delete el.dataset.pageClass;
    }
  }
}

// Before the visit: what it is and how long a visit lasts. Nothing is used until Open it.
// info: the peek ({share, item}); onOpen(): the caller's open.
export function folderReady(root, { cfg, info, onOpen }) {
  const share = info.share ?? {};
  const ticketMin = Math.round((cfg.retention?.ticket_s ?? 1800) / 60);
  const left = share.views_left;
  const until = share.expires_at ? new Date(share.expires_at * 1000) : null;
  const rule = left === 1 ? t('fv.ready_once', { ticket_min: ticketMin })
    : left !== null && left !== undefined ? t('fv.ready_few', { count: left, ticket_min: ticketMin })
      : t('fv.ready_visit', { ticket_min: ticketMin });
  const open = btn(t('viewer.open'), { size: 'lg', glyph: 'folder-open', testid: 'view-open', onclick: onOpen });
  root.dataset.state = 'ready';
  root.dataset.kind = 'folder';
  root.replaceChildren(h('div', { class: 'card fv-card' },
    h('div', { class: 'card-header' },
      h('h1', { class: 'card-title h3', tabindex: '-1' }, t('fv.ready_h')),
      h('p', { class: 'card-description', 'data-testid': 'view-views-left', 'data-left': left ?? '' }, rule),
      until ? h('p', { class: 'small muted' }, t('fv.ready_until', { date: formatDate(until.getTime(), { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) })) : null),
    h('div', { class: 'card-content stack' },
      h('p', { class: 'muted' }, t('fv.ready_count', { count: info.item?.child_count ?? 0 })),
      h('div', { class: 'alert' }, icon('info'), h('div', { class: 'alert-description' }, t('fv.scan')))),
    h('div', { class: 'card-footer' }, open)));
  open.focus({ preventScroll: true });
}

// After the open: the folder, on the whole page.
export function folderOpened(root, opened, { cfg }) {
  const panel = folderPanel(opened, { cfg, heading: 'h1' });
  root.dataset.state = 'opened';
  root.dataset.kind = 'folder';
  root.replaceChildren(panel.el);
  init(root);
  root.querySelector('#fv-title')?.focus({ preventScroll: true });
  return panel;
}

