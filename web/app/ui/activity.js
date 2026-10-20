// SPDX-License-Identifier: MIT
// Activity (16-drive-design §6): what happened to each file and its links, from what our server counts
// (opens per hour per link, never who or an IP address, C40), the payments it counted (GET /me/sales) and the
// browser's own records. Per file, a sheet; for the whole drive, the Activity view, newest first, with the files
// that left: "It left your drive", and once the next checkpoint is on chain, "We wrote that on the Tari chain"
// with its transaction (C42). A link that ends on a file kept in the drive gets no chain line: the file stays.
//
// The view scales (lib/feed.js): what happens together is one row ("Locked and uploaded 20 files to
// hidebox-brand"), open to its list; rows fall into days with their counts; the newest rows come first and
// Show more adds the next ones; chips filter the kinds; the whole log saves as a CSV file made in this browser.
import { BRAND, formatBytes, formatDate, t } from '../lib/i18n.js';
import { FILTERS, dayGroups, dayName, filterEvents, groupEvents, toCsv } from '../lib/feed.js';
import { h, icon, init, openModal, closeModal } from './behaviors.js';
import { badges, button, fileIcon, formatTari, itemName, sheetBox } from './drive-parts.js';

const PAGE = 25;    // rows on the first screen, and how many more each Show more adds
const when = (sec) => formatDate(sec * 1000, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const time = (sec) => formatDate(sec * 1000, { hour: 'numeric', minute: '2-digit' });
const ENDED = new Set(['burned', 'exhausted', 'expired', 'revoked', 'removed', 'owner_deleted']);
// Within an hour, what happened last comes first: it left, then its opens and payments, then the link, then the upload.
// A folder is made before the files that go in it.
const RANK = { left: 5, ended: 4, opened: 3, paid: 3, made: 2, uploaded: 1, folder: 0 };

// The payments our server counted for one link (GET /me/sales, newest 50), the payer-kept ones left out.
const paymentsOf = (drive, share) => (drive.sales?.paid ?? []).filter((p) => p.share_id === share.id && p.owner_ok !== false);

// Events of one kept item: [{k, at (unix s, or null), item, …}], newest first. A folder is made, never uploaded.
export function itemEvents(item, drive = null) {
  const out = [{ k: item.folder ? 'folder' : 'uploaded', at: item.row.created_hour, item }];
  for (const s of item.row.shares ?? []) {
    out.push({ k: 'made', at: s.created_hour, item, share: s });
    const buckets = Array.isArray(s.opens) ? s.opens : null;
    if (buckets) {
      for (const [hour, n] of buckets) out.push({ k: 'opened', at: hour, item, share: s, n });
    } else if (s.views_used > 0) {
      out.push({ k: 'opened', at: null, item, share: s, n: s.views_used });
    }
    if (drive) for (const p of paymentsOf(drive, s)) out.push({ k: 'paid', at: p.seen_at, item, share: s, pay: p });
    if (ENDED.has(s.state)) out.push({ k: 'ended', at: s.ended_hour ?? s.ended_at ?? null, item, share: s });
  }
  return out.sort((a, b) => ((b.at ?? b.share?.created_hour ?? 0) - (a.at ?? a.share?.created_hour ?? 0)) || ((RANK[b.k] ?? 0) - (RANK[a.k] ?? 0)));
}

const EV = {
  uploaded: ['lock', null, () => t('drive.act.uploaded')],
  folder: ['folder-plus', null, () => t('drive.act.folder')],
  made: ['link', null, () => t('drive.act.made')],
  opened: ['eye', null, (e) => t('drive.act.opened', { count: e.n })],
  paid: ['coins', 'tari', () => t('drive.act.paid')],
  ended: ['check', 'success', () => t('drive.act.ended')],
  left: ['receipt-text', 'tari', () => t('drive.act.left')],
};

// A row of several: the kind's sentence with the count and the folder (literal keys, so the strings check sees them).
const GROUP = {
  uploaded: 'drive.act.g.uploaded', folder: 'drive.act.g.folder', made: 'drive.act.g.made', opened: 'drive.act.g.opened',
  paid: 'drive.act.g.paid', ended: 'drive.act.g.ended', left: 'drive.act.g.left',
};
const CHIP = { all: 'drive.act.f.all', uploads: 'drive.act.f.uploads', links: 'drive.act.f.links', opens: 'drive.act.f.opens', payments: 'drive.act.f.payments' };

// Files that left keep no folder on our server: their rows stay apart from the drive's own.
const GONE = 'gone';
const testBadge = () => h('span', { class: 'badge', 'data-variant': 'secondary' }, t('rec.test_money'));
const amountOf = (e) => (e.pay ? BigInt(e.pay.value_ut) : 0n);

function sub(e) {
  if (e.k === 'uploaded') return formatBytes(e.item.row.size_stored);
  if (e.k === 'opened') return e.share?.max_views ? t('drive.act.opened_d', { used: e.share.views_used, max: e.share.max_views }) : null;
  if (e.k === 'paid') return [h('span', { class: 'tari-text' }, t('sales.amount', { price: formatTari(e.pay.value_ut) })), e.pay.demo ? [' ', testBadge()] : null];
  if (e.k === 'ended') return t('drive.act.ended_d');
  return null;
}

// The chain line of a file that left: its exit leaf's checkpoint (GET /seallog/proof/{id}?kind=exit), or
// when the next one is due. A folder has no ciphertext, so no exit leaf and no line (`exit_receipt` false).
// A committed proof never changes, so it is asked once per page load; a pending one on each view.
function receiptLine(drive, e) {
  if (!drive.cfg.features?.seallog || !e.row.exit_receipt) return null;
  const line = h('span', { class: 't-meta', 'data-testid': 'exit-receipt' });
  const show = (r) => {
    const tx = r?.checkpoint?.tx_id;
    if (tx) {
      line.dataset.state = 'onchain';
      return line.replaceChildren(t('drive.act.record'), ' ',
        h('a', { class: 'mono tx-link', href: `/verify/tx/${tx}`, 'aria-label': t('drive.act.check'), 'data-testid': 'exit-tx' }, `tx ${tx.slice(0, 8)}…`));
    }
    line.dataset.state = 'pending';
    return line.replaceChildren(t('drive.act.record_wait', { checkpoint_min: Math.round(drive.cfg.seal_log.checkpoint_interval_s / 60) }));
  };
  const proofs = (drive.exitProofs ??= new Map());
  const id = e.row.item_id;
  show(proofs.get(id) ?? null);
  if (proofs.has(id)) return line;
  import('../lib/api-drive.js').then(({ exitProof }) => exitProof(id)).then((r) => {
    if (r?.checkpoint?.tx_id) proofs.set(id, r);
    show(r);
  }, () => null);
  return line;
}

const nameButton = (drive, e) => (e.gone || !e.item
  ? h('span', {}, e.name)
  : h('button', { class: 'link-btn', type: 'button', onclick: () => openActivity(drive, e.item) }, e.name));

// One event: the kind, the name when the list is drive-wide, what it was, its chain line, its time.
function timelineRow(drive, e, { named = false, at = when } = {}) {
  const [glyph, tone, title] = EV[e.k];
  const meta = [sub(e), e.at ? at(e.at) : null].filter(Boolean);   // what it was and when, on one line
  return h('li', { 'data-event': e.k, 'data-testid': 'activity-event', 'data-name': named ? e.name : null, tabindex: '-1' },
    h('span', { class: 't-icon', 'data-tone': tone }, icon(glyph)),
    h('div', { class: 't-body' },
      h('span', { class: 't-title' }, title(e), named ? [h('span', { class: 'muted' }, ' · '), nameButton(drive, e)] : null),
      meta.length ? h('span', { class: 't-meta' }, meta.flatMap((m, i) => (i ? [' · ', m] : [m]))) : null,
      e.k === 'left' ? receiptLine(drive, e) : null));
}

// One file of a row of several: its name, then what it was (size, opens, amount, chain line).
function memberRow(drive, e) {
  const s = e.k === 'opened' ? t('drive.act.opened', { count: e.n }) : ['folder', 'made', 'ended'].includes(e.k) ? null : sub(e);
  return h('li', { 'data-event': e.k, 'data-testid': 'activity-event', 'data-name': e.name },
    icon(e.item && !e.gone ? fileIcon(e.item) : 'file'),
    h('span', { class: 'feed-name' }, nameButton(drive, e)),
    s ? h('span', { class: 't-meta' }, s) : null,
    e.k === 'left' ? receiptLine(drive, e) : null);
}

// A row of several events: "Locked and uploaded 20 files to hidebox-brand", its size and hour, folded open to the files.
function groupRow(drive, row, folderName, open) {
  const n = row.events.length;
  // Opens and links count per link: a file with two links opened in the same hour is still one file.
  const files = new Set(row.events.map((e) => e.item?.id ?? e.name)).size;
  const [glyph, tone] = EV[row.k];
  const listId = `ag-${row.key.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  const list = h('ul', { class: 'feed-members', id: listId, role: 'list', hidden: !open.has(row.key) }, row.events.map((e) => memberRow(drive, e)));
  const label = h('span', {});
  const toggle = h('button', { class: 'btn feed-toggle', 'data-variant': 'ghost', 'data-size': 'sm', type: 'button', 'aria-controls': listId, 'data-testid': 'activity-expand' },
    icon('chevron-right'), label);
  const sync = () => {
    const shown = !list.hidden;
    toggle.setAttribute('aria-expanded', String(shown));
    label.textContent = shown ? t('drive.act.hide') : t('drive.act.show', { count: n });
  };
  toggle.addEventListener('click', () => {
    list.hidden = !list.hidden;
    if (list.hidden) open.delete(row.key);
    else open.add(row.key);
    sync();
  });
  sync();
  const opens = row.events.reduce((a, e) => a + (e.n ?? 0), 0);
  const size = row.k === 'uploaded' ? formatBytes(row.events.reduce((a, e) => a + (e.item?.row.size_stored ?? 0), 0)) : null;
  const money = row.k === 'paid' ? h('span', { class: 'tari-text' }, t('sales.amount', { price: formatTari(row.events.reduce((a, e) => a + amountOf(e), 0n)) })) : null;
  const meta = [size, money, row.at ? time(row.at) : null].filter(Boolean);
  return h('li', { 'data-testid': 'activity-group', 'data-group': row.k, 'data-count': String(n), tabindex: '-1' },
    h('span', { class: 't-icon', 'data-tone': tone }, icon(glyph)),
    h('div', { class: 't-body' },
      h('span', { class: 't-title' }, row.folder === GONE && row.k === 'opened' ? t('drive.act.g.opened_gone', { count: files, opens })
        : t(GROUP[row.k], { count: row.k === 'opened' ? files : n, folder: folderName, opens })),
      meta.length ? h('span', { class: 't-meta' }, meta.flatMap((m, i) => (i ? [' · ', m] : [m]))) : null,
      toggle, list));
}

// The sheet of one item: its badges, its events, and What our server knows about it.
export function openActivity(drive, item) {
  const events = itemEvents(item, drive);
  const box = sheetBox({
    id: 'activity-sheet', title: itemName(item), testid: 'activity-sheet',
    head: h('div', { class: 'row wrap' }, badges(item)),
    description: t('drive.act.title'),
    body: [h('ol', { class: 'timeline' }, events.map((e) => timelineRow(drive, e))), h('p', { class: 'small muted' }, t('drive.act.count'))],
    footer: [button(t('drive.act.known'), { variant: 'outline', glyph: 'shield-check', testid: 'open-known', onclick: () => {
      closeModal(box);
      setTimeout(() => import('./drive-known.js').then((m) => m.openKnown(drive, item)), 200);
    } })],
  });
  document.getElementById(box.id)?.remove();
  document.body.append(box);
  init(box);
  openModal(box);
  return box;
}

// The whole log as CSV, every event (whatever the chips show), made here and saved through a download link.
async function saveLog(all, folderName) {
  const head = ['time_utc', 'event', 'name', 'folder', 'size_bytes', 'opens', 'amount_ttari', 'demo_wallet', 'tx_id'];
  const rows = all.map((e) => [
    e.at ? new Date(e.at * 1000).toISOString().replace('.000Z', 'Z') : '',
    EV[e.k][2](e), e.name, e.gone ? '' : folderName(e.folder),
    e.k === 'uploaded' ? e.item?.row.size_stored ?? '' : '',
    e.k === 'opened' ? e.n : '',
    e.pay ? formatTari(e.pay.value_ut) : '',
    e.pay ? (e.pay.demo ? 'yes' : 'no') : '',
    e.pay?.tx_id ?? '',
  ]);
  const { saveFile } = await import('../lib/download.js');
  saveFile([toCsv([head, ...rows])], `${BRAND}-activity-${new Date().toISOString().slice(0, 10)}.csv`);
}

// The Activity view: every event of the drive, grouped, by day, newest first, and the files that left.
export async function renderFeed(drive, page) {
  await drive.ready();
  const pay = drive.cfg.features?.pay_to_open
    ? import('./sales.js').then((m) => m.fetchSales(drive)).catch(() => null)   // payments: a list that can't load leaves them out
    : null;
  let gone = [];
  if (drive.folders) {
    try {
      const { listAll } = await import('../lib/api-drive.js');
      const rows = await listAll({ view: 'gone' }, drive.headers());
      const opened = await drive.index.openList(rows);
      // A file that left shows its opens first (Opened, then It left your drive; §10 track one step 5).
      gone = opened.flatMap((it) => [
        ...(it.row.opens ?? []).map(([hour, n]) => ({ k: 'opened', at: hour, item: it, share: null, n, gone: true, name: itemName(it) })),
        { k: 'left', at: it.row.exit_hour ?? null, item: it, row: it.row, name: itemName(it), gone: true }]);
    } catch {
      gone = [];
    }
  }
  await pay;
  const all = [];
  for (const it of drive.index.items.values()) {
    if (!drive.index.visible(it)) continue;
    for (const e of itemEvents(it, drive)) all.push({ ...e, name: itemName(it), folder: it.parentId ?? null });
  }
  all.push(...gone.map((e) => ({ ...e, folder: GONE })));
  // A payment to a link whose file is no longer in the drive (it left, or sits in the trash) still shows, unnamed.
  const listed = new Set(all.filter((e) => e.pay).map((e) => e.pay.utxo_id));
  for (const p of drive.sales?.paid ?? []) {
    if (p.owner_ok === false || listed.has(p.utxo_id)) continue;
    all.push({ k: 'paid', at: p.seen_at, item: null, share: null, pay: p, name: t('sales.what'), folder: GONE, gone: true });
  }
  all.sort((a, b) => ((b.at ?? 0) - (a.at ?? 0)) || ((RANK[b.k] ?? 0) - (RANK[a.k] ?? 0)));

  const folderName = (id) => (id && drive.index.get(id) ? itemName(drive.index.get(id)) : t('drive.side.mine'));
  const state = { filter: 'all', shown: PAGE, query: drive.query ?? '', open: new Set() };
  const list = h('div', { class: 'stack feed-days', 'data-testid': 'activity-feed' });
  const chips = Object.keys(FILTERS).filter((f) => f !== 'payments' || drive.cfg.features?.pay_to_open).map((f) =>
    h('button', { class: 'toggle', 'data-variant': 'outline', 'data-size': 'sm', type: 'button', 'aria-pressed': String(f === state.filter), 'data-filter': f, 'data-testid': `activity-filter-${f}`,
      onclick: (ev) => {
        state.filter = f;
        state.shown = PAGE;
        for (const c of chips) c.setAttribute('aria-pressed', String(c === ev.currentTarget));
        draw();
      } }, t(CHIP[f])));
  const save = button(t('drive.act.save'), { variant: 'outline', glyph: 'download', testid: 'activity-save', onclick: () => saveLog(all, folderName) });
  const knownBtn = button(t('drive.act.known'), { variant: 'outline', glyph: 'shield-check', testid: 'open-known', onclick: () => import('./drive-known.js').then((m) => m.openKnown(drive, null)) });

  function draw(focusFrom = null) {
    const q = state.query.trim().toLowerCase();
    const events = filterEvents(all, state.filter).filter((e) => !q || String(e.name ?? '').toLowerCase().includes(q));
    const rows = groupEvents(events, RANK);
    const counts = new Map(dayGroups(rows).map((d) => [d.day, d.count]));   // a day's count is the whole day's, shown or not yet
    const days = dayGroups(rows.slice(0, state.shown));
    let i = 0;
    let first = null;
    list.replaceChildren(...[
      ...days.map((d) => {
        const named = dayName(d.day);
        const label = named === 'today' ? t('drive.act.today') : named === 'yesterday' ? t('drive.act.yesterday')
          : d.day === null ? t('drive.act.earlier') : formatDate(d.day, { weekday: 'short', month: 'short', day: 'numeric' });
        const id = `day-${d.day ?? 'none'}`;
        const count = counts.get(d.day) ?? d.count;
        return h('section', { class: 'feed-group', 'aria-labelledby': id, 'data-testid': 'activity-day', 'data-count': String(count) },
          h('h2', { class: 'section-label feed-day', id }, h('span', {}, label), h('span', { class: 'feed-count' }, t('drive.act.day_n', { count }))),
          h('ol', { class: 'timeline feed card' }, d.rows.map((row) => {
            const li = row.events.length > 1 ? groupRow(drive, row, folderName(row.folder), state.open)
              : timelineRow(drive, { ...row.events[0] }, { named: true, at: d.day === null ? when : time });
            if (focusFrom !== null && i++ === focusFrom) first = li;
            return li;
          })));
      }),
      rows.length > state.shown ? h('div', { class: 'row' }, button(t('drive.act.more'), { variant: 'outline', testid: 'activity-more', onclick: () => {
        const from = state.shown;
        state.shown += PAGE;
        draw(from);
      } })) : null,
      rows.length ? null : h('p', { class: 'muted small', 'data-testid': 'activity-none' }, t('drive.act.none'))].filter(Boolean));
    list.dataset.rows = String(rows.length);
    first?.focus();
  }

  if (!all.length) {
    page.replaceChildren(
      h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.activity')), knownBtn),
      h('p', { class: 'page-desc' }, `${t('drive.act.desc')} ${t('drive.act.count')}`),
      h('div', { class: 'empty', 'data-testid': 'activity-feed' },
        h('div', { class: 'empty-header' }, h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('activity')),
          h('h2', { class: 'empty-title' }, t('drive.act.empty')), h('p', { class: 'empty-description' }, t('drive.act.empty_d')))));
    return;
  }
  page.replaceChildren(
    h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.activity')), save, knownBtn),
    h('p', { class: 'page-desc' }, `${t('drive.act.desc')} ${t('drive.act.count')}`),
    h('div', { class: 'feed-filters', role: 'group', 'aria-label': t('drive.act.filter') }, chips),
    list);
  draw();
  // Search filters this list in place, by name, like My drive.
  const onFilter = (e) => {
    state.query = e.detail ?? '';
    state.shown = PAGE;
    draw();
  };
  document.addEventListener('drive:filter', onFilter);
  page.addEventListener('drive:gone', () => document.removeEventListener('drive:filter', onFilter), { once: true });
}
