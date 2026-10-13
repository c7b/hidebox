// SPDX-License-Identifier: MIT
// Activity (16-drive-design §6): what happened to each file and its links, from what our server counts
// (opens per hour per link, never who or an IP address, C40) and the browser's own records. Per file, a
// sheet; for the whole drive, the Activity view, newest first, with the files that left: "It left your
// drive", and once the next checkpoint is on chain, "We wrote that on the Tari chain" with its
// transaction (C42). A link that ends on a file kept in the drive gets no chain line: the file stays.
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { h, icon, init, openModal, closeModal } from './behaviors.js';
import { badges, button, itemName, sheetBox } from './drive-parts.js';

const HOUR = 3600;
const when = (sec) => formatDate(sec * 1000, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const ENDED = new Set(['burned', 'exhausted', 'expired', 'revoked', 'removed', 'owner_deleted']);

// Events of one kept item: [{k, at (unix s, or null), …}], newest first.
export function itemEvents(item) {
  const out = [{ k: 'uploaded', at: item.row.created_hour, item }];
  for (const s of item.row.shares ?? []) {
    out.push({ k: 'made', at: s.created_hour, item, share: s });
    const buckets = Array.isArray(s.opens) ? s.opens : null;
    if (buckets) {
      for (const [hour, n] of buckets) out.push({ k: 'opened', at: hour, item, share: s, n });
    } else if (s.views_used > 0) {
      out.push({ k: 'opened', at: null, item, share: s, n: s.views_used });
    }
    for (const c of s.paid?.claims ?? []) if (c.paid_hour) out.push({ k: 'paid', at: c.paid_hour, item, share: s, claim: c });
    if (ENDED.has(s.state)) out.push({ k: 'ended', at: s.ended_hour ?? s.ended_at ?? null, item, share: s });
  }
  return out.sort((a, b) => (b.at ?? b.share?.created_hour ?? 0) - (a.at ?? a.share?.created_hour ?? 0));
}

const EV = {
  uploaded: ['lock', null, () => t('drive.act.uploaded')],
  made: ['link', null, () => t('drive.act.made')],
  opened: ['eye', null, (e) => t('drive.act.opened', { count: e.n })],
  paid: ['coins', 'tari', () => t('drive.act.paid')],
  ended: ['check', 'success', () => t('drive.act.ended')],
  left: ['receipt-text', 'tari', () => t('drive.act.left')],
};

function sub(e) {
  if (e.k === 'uploaded') return e.item.folder ? null : formatBytes(e.item.row.size_stored);
  if (e.k === 'made') return null;
  if (e.k === 'opened') return e.share.max_views ? t('drive.act.opened_d', { used: e.share.views_used, max: e.share.max_views }) : null;
  if (e.k === 'paid') return t('drive.act.paid_d');
  if (e.k === 'ended') return t('drive.act.ended_d');
  return null;
}

// The chain line of a file that left: its exit leaf's checkpoint, or when the next one is due.
function receiptLine(drive, e) {
  if (!drive.cfg.features?.seallog) return null;
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
  const known = e.row.exit ?? null;
  if (known) show(known);
  else {
    show(null);
    const share = (e.row.shares ?? [])[0];
    if (share) import('../lib/api.js').then(({ exitReceipt }) => exitReceipt(share.id)).then(show, () => null);
  }
  return line;
}

function timelineRow(drive, e, { named = false, onName = null } = {}) {
  const [glyph, tone, title] = EV[e.k];
  const name = named ? (onName ? h('button', { class: 'link-btn', type: 'button', onclick: onName }, e.name) : h('span', {}, e.name)) : null;
  const s = sub(e);
  return h('li', { 'data-event': e.k, 'data-testid': 'activity-event', 'data-name': named ? e.name : null }, h('span', { class: 't-icon', 'data-tone': tone }, icon(glyph)),
    h('div', { class: 't-body' },
      h('span', { class: 't-title' }, title(e), name ? h('span', { class: 'muted' }, ' · ') : null, name),
      s ? h('span', { class: 't-meta' }, s) : null,
      e.k === 'left' ? receiptLine(drive, e) : null,
      e.at ? h('span', { class: 't-meta' }, when(e.at)) : null));
}

// The sheet of one item: its badges, its events, and What our server knows about it.
export function openActivity(drive, item) {
  const events = itemEvents(item);
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

// The Activity view: every event of the drive, Today then Earlier, and the files that left.
export async function renderFeed(drive, page) {
  await drive.ready();
  const events = [];
  for (const it of drive.index.items.values()) if (drive.index.visible(it)) for (const e of itemEvents(it)) events.push({ ...e, name: itemName(it) });
  let gone = [];
  if (drive.folders) {
    try {
      const { listAll } = await import('../lib/api-drive.js');
      const rows = await listAll({ view: 'gone' }, drive.headers());
      const opened = await drive.index.openList(rows);
      gone = opened.map((it) => ({ k: 'left', at: it.row.exit_hour ?? null, item: it, row: it.row, name: itemName(it) }));
    } catch {
      gone = [];
    }
  }
  const all = [...events, ...gone].sort((a, b) => (b.at ?? 0) - (a.at ?? 0));
  const today = Math.floor(Date.now() / 1000) - 24 * HOUR;
  const groups = [[t('drive.act.today'), all.filter((e) => (e.at ?? 0) >= today)], [t('drive.act.earlier'), all.filter((e) => (e.at ?? 0) < today)]]
    .filter(([, list]) => list.length);
  const knownBtn = button(t('drive.act.known'), { variant: 'outline', glyph: 'shield-check', testid: 'open-known', onclick: () => import('./drive-known.js').then((m) => m.openKnown(drive, null)) });
  page.replaceChildren(
    h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.activity')), knownBtn),
    h('p', { class: 'page-desc' }, `${t('drive.act.desc')} ${t('drive.act.count')}`),
    all.length
      ? h('div', { class: 'stack', 'data-testid': 'activity-feed' }, groups.map(([label, list]) => h('section', { class: 'feed-group', 'aria-label': label },
        h('h2', { class: 'section-label' }, label),
        h('ol', { class: 'timeline feed card' }, list.map((e) => timelineRow(drive, e, { named: true, onName: e.k === 'left' ? null : () => openActivity(drive, e.item) }))))))
      : h('div', { class: 'empty', 'data-testid': 'activity-feed' },
        h('div', { class: 'empty-header' }, h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('activity')),
          h('h2', { class: 'empty-title' }, t('drive.act.empty')), h('p', { class: 'empty-description' }, t('drive.act.empty_d')))));
}
