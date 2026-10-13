// SPDX-License-Identifier: MIT
// Received (16-drive-design §6, 16-drive-architecture §3.3; Google's "Shared with me"), lane app2: what
// others sent to this drive's Tari address and what was left at its drop link, found by this browser
// alone. Every browser downloads the same mirror of all TARI outputs and tries each one with its own
// view key, so our server never learns which outputs are this drive's. A Tari arrival names no sender
// ("By Tari, sender hidden": a stealth output and the 65-byte courier payload carry no origin). Open one
// here (a file, or a folder and its visit); Save to my drive locks it again as the drive's own: there
// is no copy on our server's side. When the chain can't be reached, what was found before stays.
import { formatRelative, t } from '../lib/i18n.js';
import { ApiError } from '../lib/api.js';
import { FLAG_FOLDER } from '../lib/links.js';
import { sanitizeFileName } from '../lib/filetype.js';
import { h, icon, init, openModal, toast } from './behaviors.js';
import { alert, button, errorAlert, formatBytes, formatTari } from './drive-parts.js';
import { tariRow } from './drive-list.js';

const RESCAN_MS = 15000;

function statusOf(d) {
  if (d.exited) return 'gone';
  if (d.saved) return 'saved';
  if (d.opened) return 'opened';
  return d.openable ? 'new' : 'unreadable';
}

function statusBadge(state) {
  const [variant, key] = {
    new: [null, 'rec.new'], opened: ['secondary', 'rec.opened'], saved: ['success', 'rec.saved'],
    gone: ['outline', 'rec.gone'], unreadable: ['outline', 'rec.unreadable'], waiting: ['outline', 'rec.waiting'],
  }[state];
  return h('span', { class: 'badge', 'data-variant': variant, 'data-testid': 'received-status', 'data-state': state }, t(key));
}

// The drop link card: one active drop link, Copy (this page's primary) and New drop link.
function dropCard(drive) {
  const card = h('section', { class: 'card drop-card', 'aria-labelledby': 'rec-drop-h', 'data-testid': 'received-drop' });
  const draw = () => {
    const identity = drive.identity;
    const active = identity.drops?.filter((d) => d.state === 'active').at(-1) ?? null;
    const errors = h('div', {});
    const head = h('div', { class: 'card-header' },
      h('h2', { class: 'card-title', id: 'rec-drop-h' }, t('rec.drop')),
      h('p', { class: 'card-description' }, t('rec.drop_d')));
    const run = (fn, label) => async (e) => {
      const b = e.currentTarget;
      const before = [...b.childNodes];
      b.disabled = true;
      b.replaceChildren(t(label));
      errors.replaceChildren();
      try {
        const { withOotle } = await import('../lib/identity.js');
        await withOotle(identity);
        await fn(await import('../lib/drop.js'));
        draw();
      } catch (err) {
        b.replaceChildren(...before);
        b.disabled = false;
        errors.replaceChildren(errorAlert(err));
      }
    };
    if (!active) {
      card.replaceChildren(head, h('div', { class: 'card-content' },
        h('div', { class: 'row' }, button(t('rec.drop_make'), { glyph: 'link', testid: 'drop-create', onclick: run((lib) => lib.createDrop(identity, ''), 'rec.drop_making') })),
        errors));
      return;
    }
    const url = `${drive.cfg.origin || location.origin}/d/${active.drop_id}`;
    const copy = button(t('share.copy'), { glyph: 'copy', testid: 'drop-copy' });
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(url);
        toast(t('drive.toast.copied'), { type: 'success' });
      } catch {
        toast(t('error.clipboard'), { type: 'error' });
      }
    });
    head.append(h('div', { class: 'card-action' },
      button(t('rec.drop_new'), { variant: 'ghost', size: 'sm', glyph: 'plus', onclick: run((lib) => lib.rotateDrop(identity, active.i), 'rec.drop_making') })));
    card.replaceChildren(head, h('div', { class: 'card-content' },
      h('div', { class: 'link-row' }, h('input', { class: 'input', readonly: true, value: url, 'aria-label': t('rec.drop'), 'data-testid': 'drop-link' }), copy),
      active.label ? h('p', { class: 'small muted' }, t('rec.drop_named', { label: active.label })) : null,
      errors));
  };
  draw();
  return card;
}

export async function render(drive, page) {
  const list = h('tbody', {});
  const table = h('div', { class: 'files', 'data-plain': '', hidden: true }, h('div', { class: 'table-container' }, h('table', { class: 'table' },
    h('thead', {}, h('tr', {}, h('th', {}, t('rec.what')), h('th', { class: 'col-wide' }, t('rec.from')), h('th', { class: 'col-wide' }, t('rec.when')),
      h('th', { class: 'col-wide' }, t('rec.status')), h('th', {}, h('span', { class: 'sr-only' }, t('drive.col.actions'))))),
    list)));
  const empty = h('div', { class: 'empty', 'data-testid': 'inbox-empty' }, h('div', { class: 'empty-header' },
    h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('inbox')),
    h('h2', { class: 'empty-title' }, t('drive.rec.title')), h('p', { class: 'empty-description' }, t('drive.rec.empty'))));
  const scanLine = h('p', { class: 'scanline', role: 'status', 'data-testid': 'inbox-scan' }, spinner(), h('span', {}, t('rec.scanning')));
  const problems = h('div', {});
  page.replaceChildren(
    h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.received'))),
    h('p', { class: 'page-desc' }, t('drive.rec.desc')),
    drive.cfg.features?.drops === false ? null : dropCard(drive),
    scanLine, problems,
    h('section', { 'aria-label': t('rec.files'), 'data-testid': 'received-root' }, table, empty),
    tariRow(drive));
  init(page);

  let identity;
  let lib;
  try {
    const { withOotle } = await import('../lib/identity.js');
    identity = await withOotle(drive.identity);
    lib = await import('../lib/scan.js');
  } catch (e) {
    scanLine.replaceChildren(icon('triangle-alert'), h('span', {}, t('rec.offline_h')));
    problems.replaceChildren(errorAlert(e));
    return;
  }

  const rows = new Map();
  const labelOf = (d) => {
    if (d.source !== 'drop') return t('rec.via_tari');
    const label = identity.drops?.find((x) => x.i === d.dropIndex)?.label;
    return label ? t('rec.via_drop', { label }) : t('rec.via_drop_n');
  };

  async function folderFlag(d) {
    if (d.folder !== undefined || !d.openable) return;
    try {
      d.folder = Boolean((await lib.deliverySecret(identity, d)).flags & FLAG_FOLDER);
    } catch {
      d.folder = false;
    }
  }

  function row(d) {
    const state = statusOf(d);
    const what = d.name ? sanitizeFileName(d.name) : d.folder ? t('rec.locked_folder') : t('rec.locked');
    const via = labelOf(d);
    const came = d.found ? formatRelative(d.found * 1000) : '';
    const open = d.openable && !d.exited
      ? button(t('rec.open'), { variant: 'outline', size: 'sm', testid: 'received-open-button', onclick: (e) => openDelivery(d, e.currentTarget) }) : null;
    return h('tr', { 'data-testid': 'received-row', 'data-source': d.source, 'data-state': state, 'data-utxo': d.utxoId },
      h('td', {}, h('div', { class: 'file-name', 'data-testid': 'inbox-item', 'data-source': d.source, 'data-state': d.exited ? 'exited' : d.openable ? 'ready' : 'unreadable' },
        icon(d.source === 'drop' ? 'inbox' : 'send'),
        h('div', { class: 'file-text' }, h('span', { class: 'name' }, what),
          h('span', { class: 'file-meta' }, h('span', {}, via), came ? h('span', {}, `· ${came}`) : null, statusBadge(state))))),
      h('td', { class: 'col-wide num-cell' }, d.source === 'drop' ? via : h('span', { class: 'row' }, icon('lock'), via)),
      h('td', { class: 'col-wide num-cell', title: d.epoch !== null && d.epoch !== undefined ? t('rec.epoch', { epoch: d.epoch }) : null }, came),
      h('td', { class: 'col-wide' }, statusBadge(state)),
      h('td', {}, open));
  }

  // Purchases (pay to open): the claims this browser made, kept on this device (lib/purchases.js).
  let bought = [];
  function purchaseRow(p) {
    const state = p.state === 'waiting' ? 'waiting' : p.state === 'gone' ? 'gone' : p.state === 'opened' ? 'opened' : 'new';
    const what = p.name ? sanitizeFileName(p.name) : t('rec.bought_item');
    const price = p.price_ut ? t('rec.via_bought', { price: formatTari(p.price_ut) }) : t('rec.via_bought_n');
    const money = p.demo ? h('span', { class: 'badge', 'data-variant': 'tari' }, icon('coins'), t('rec.test_money')) : null;
    const came = p.at ? formatRelative(p.at * 1000) : '';
    const open = state === 'gone' || !p.url ? null
      : h('a', { class: 'btn', 'data-variant': 'outline', 'data-size': 'sm', href: p.url, 'data-testid': 'received-open-purchase' }, t('rec.open'));
    return h('tr', { 'data-testid': 'received-row', 'data-source': 'purchase', 'data-state': state, 'data-share': p.shareId },
      h('td', {}, h('div', { class: 'file-name' }, icon('coins'),
        h('div', { class: 'file-text' }, h('span', { class: 'name' }, what),
          h('span', { class: 'file-meta' }, h('span', {}, price), came ? h('span', {}, `· ${came}`) : null, money, statusBadge(state))))),
      h('td', { class: 'col-wide num-cell' }, h('span', { class: 'row' }, price, money)),
      h('td', { class: 'col-wide num-cell' }, came),
      h('td', { class: 'col-wide' }, statusBadge(state)),
      h('td', {}, open));
  }

  function draw() {
    const all = [...rows.values()].sort((a, b) => (b.seq ?? 0) - (a.seq ?? 0));
    list.replaceChildren(...all.map(row), ...bought.map(purchaseRow));
    table.hidden = !all.length && !bought.length;
    empty.hidden = Boolean(all.length || bought.length);
  }

  async function add(d) {
    await folderFlag(d);
    rows.set(d.utxoId, d);
    draw();
  }

  async function update(d, patch) {
    Object.assign(d, patch);
    await lib.updateDelivery(identity, d.utxoId, patch).catch(() => null);
    draw();
  }

  // ---------- opening one ----------

  async function openDelivery(d, trigger) {
    const body = h('div', { class: 'stack', 'data-testid': 'received-open', 'data-state': 'opening' }, h('p', { class: 'row muted' }, spinner(), t('rec.opening')));
    const title = h('h2', { class: 'dialog-title', tabindex: '-1', 'data-autofocus': '' }, d.folder ? t('rec.locked_folder') : t('rec.locked'));
    const box = h('div', { class: 'dialog', role: 'dialog', id: 'rec-open', hidden: true, 'data-size': 'lg' },
      h('div', { class: 'dialog-header' }, title, h('p', { class: 'dialog-description' }, labelOf(d))),
      body,
      h('div', { class: 'dialog-footer' }, button(t('drive.close'), { variant: 'outline', 'data-close': '' })),
      h('button', { class: 'dialog-close', type: 'button', 'data-close': '', 'aria-label': t('drive.close') }, icon('x')));
    document.getElementById('rec-open')?.remove();
    document.body.append(box);
    init(box);
    let panel = null;
    openModal(box, { returnFocus: trigger, onClose: () => { panel?.stop(); setTimeout(() => box.remove(), 600); } });
    try {
      const [inner, open] = await Promise.all([lib.deliverySecret(identity, d), import('../lib/open.js')]);
      const status = await open.linkStatus(inner.shareId);
      const access = await open.accessFor(status, { s: inner.s });
      const opened = await open.openItem(inner.shareId, access, {});
      if (opened.kind === 'folder') {
        const { folderPanel } = await import('./folder-view.js');
        panel = folderPanel(opened, { cfg: drive.cfg, heading: 'h3', onSaveToDrive: (plan) => keep(d, plan) });
        title.textContent = opened.root.name || t('rec.locked_folder');
        body.replaceChildren(h('div', { 'data-testid': 'inbox-opened', 'data-state': 'opened' }, panel.el));
      } else {
        const parts = await open.fetchContent(opened);
        const name = opened.meta.kind === 'text' ? t('fv.note') : sanitizeFileName(opened.meta.name);
        title.textContent = name;
        body.replaceChildren(await fileBody(d, opened, parts, name));
      }
      body.dataset.state = 'opened';
      init(body);
      await update(d, { opened: true, name: opened.kind === 'folder' ? opened.root.name : (opened.meta.kind === 'text' ? '' : opened.meta.name), folder: opened.kind === 'folder' });
    } catch (e) {
      body.dataset.state = 'error';
      if (e instanceof ApiError && e.code === 'gone') {
        await update(d, { exited: true });
        body.replaceChildren(alert({ glyph: 'circle-check', title: t('rec.gone_h'), description: t('rec.gone_d'), role: 'status', testid: 'received-gone' }));
        return;
      }
      body.replaceChildren(errorAlert(e));
    }
  }

  async function fileBody(d, opened, parts, name) {
    const { checkRisky } = await import('../lib/filetype.js');
    const { makePreview } = await import('../lib/preview.js');
    const { saveFile } = await import('../lib/download.js');
    const risk = opened.meta.kind === 'text' ? { risky: false, active: false } : checkRisky(name, parts[0]?.subarray(0, 0x8006) ?? null);
    const shown = risk.risky || risk.active ? null : makePreview(parts, opened.meta, { label: name });
    const save = button(t('fv.save'), { variant: 'outline', glyph: 'download', testid: 'received-save-file', onclick: () => saveFile(parts, name) });
    const keepIt = button(t('rec.save'), { glyph: 'hard-drive', testid: 'received-keep', onclick: async (e) => {
      const b = e.currentTarget;
      b.disabled = true;
      try {
        await keep(d, { files: [{ path: [], name, parts, type: opened.meta.type, mtime: opened.meta.mtime }], dirs: [] });
      } finally {
        b.disabled = false;
      }
    } });
    return h('div', { class: 'stack', 'data-testid': 'inbox-opened', 'data-state': 'opened' },
      shown ? h('div', { class: 'fv-media' }, shown.el) : h('div', { class: 'locked-note' }, icon('file'), t(risk.risky ? 'fv.program' : 'fv.no_preview')),
      h('p', { class: 'small muted' }, formatBytes(opened.meta.size ?? 0)),
      h('div', { class: 'row wrap' }, keepIt, save),
      h('p', { class: 'small muted path-line' }, icon('info'), h('span', {}, t('fv.scan'))));
  }

  // Save to my drive: lock the plaintext again as the drive's own kept files (the upload panel shows it).
  async function keep(d, plan) {
    const { upload } = await import('./drive-upload.js');
    const dirs = [...new Map(plan.dirs.map((p) => [p.join('/'), p])).values()].sort((a, b) => a.length - b.length);
    if (plan.folder && !dirs.some((p) => p.length === 1)) dirs.unshift([plan.folder]);
    const files = plan.files.map((f) => ({ path: f.path, file: new File(f.parts, f.name, { type: f.type || 'application/octet-stream', lastModified: f.mtime || Date.now() }) }));
    await upload(drive, { files, dirs: drive.folders ? dirs : [] });
    await update(d, { saved: true });
    toast(t('rec.saved_toast'), { type: 'success' });
    // The upload re-renders the current view when it finishes; draw Received again with the new state.
    if (!page.isConnected || !list.isConnected) drive.render();
  }

  // ---------- the scan ----------

  bought = await (await import('../lib/purchases.js')).purchases(identity);
  const stored = await lib.inboxState(identity);
  for (const d of stored.deliveries) await folderFlag(d);
  for (const d of stored.deliveries) rows.set(d.utxoId, d);
  draw();

  let running = false;
  let checked = 0;
  async function run() {
    if (running || !page.isConnected) return;
    running = true;
    const base = checked;
    try {
      await lib.scan(identity, {
        onDelivery: (d) => { add(d); },
        onProgress: (p) => {
          checked = base + p.checked;
          scanLine.dataset.checked = String(checked);
          scanLine.dataset.head = String(p.head);
        },
      });
      problems.replaceChildren();
      scanLine.dataset.checked = String(checked);
      scanLine.replaceChildren(icon('circle-check'), h('span', {}, t('rec.scan', { count: checked })));
    } catch (e) {
      // The chain mirror or our server can't be reached: say so, keep what was found before.
      scanLine.replaceChildren(icon('cloud'), h('span', {}, t('rec.offline_h')));
      problems.replaceChildren(alert({ glyph: 'info', title: t('rec.offline_h'), description: t('rec.offline'), role: 'status', testid: 'received-offline' }));
    } finally {
      running = false;
      if (page.isConnected) setTimeout(() => document.visibilityState === 'visible' && run(), RESCAN_MS);
    }
  }
  run();
}

function spinner() {
  const s = icon('loader-circle');
  s.classList.add('spinner');
  return s;
}
