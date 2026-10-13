// SPDX-License-Identifier: MIT
// What our server knows (16-drive-design §6, claim C44 with C40, C41, C35 and C4): the glass box, a sheet
// in words. Opened from a file, each line also shows what our server holds for that file, so the list
// can be checked against the row it describes.
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { activeShares, ruleOf } from '../lib/drive.js';
import { h, icon, init, openModal } from './behaviors.js';
import { ruleBadge, sheetBox } from './drive-parts.js';

function line(glyph, key, value = null, testid = null) {
  return h('li', { 'data-testid': testid }, h('span', { class: 't-icon' }, icon(glyph)),
    h('div', { class: 't-body' }, h('span', { class: 't-title' }, t(key)), value ? h('span', { class: 't-meta' }, value) : null));
}

// opens per hour of the item's links, as our server counts them: "3 in 2 hours"
function opensValue(item) {
  let n = 0;
  const hours = new Set();
  for (const s of item.row.shares ?? []) {
    if (Array.isArray(s.opens)) for (const [hour, k] of s.opens) { n += k; hours.add(hour); }
    else n += s.views_used ?? 0;
  }
  return hours.size ? t('drive.known.opens_v', { count: n, hours: hours.size }) : t('drive.known.opens_n', { count: n });
}

export function openKnown(drive, item = null) {
  const shares = item ? activeShares(item) : [];
  const siblings = item ? drive.index.children(item.parentId).length - 1 : 0;
  const lines = [
    line('scale', 'drive.known.size', item && !item.folder ? formatBytes(item.row.size_stored) : null, 'known-size'),
    line('clock', 'drive.known.hour', item ? formatDate(item.row.created_hour * 1000, { dateStyle: 'medium', timeStyle: 'short' }) : null, 'known-hour'),
    line('repeat', 'drive.known.rule', item ? h('span', { class: 'row' }, ruleBadge(ruleOf(item)), shares[0]?.views_left != null ? t('drive.known.left', { count: shares[0].views_left }) : null) : null, 'known-rule'),
    line('activity', 'drive.known.opens', item ? opensValue(item) : null, 'known-opens'),
    drive.folders ? line('folder', 'drive.known.folder', item ? t('drive.known.folder_v', { count: siblings }) : null, 'known-folder') : null,
    drive.cfg.features?.pay_to_open ? line('coins', 'drive.known.paid') : null,
  ].filter(Boolean);
  const box = sheetBox({
    id: 'known-sheet', title: t('drive.known.title'), description: t('drive.known.desc'), testid: 'known-sheet',
    body: [
      h('ol', { class: 'timeline known' }, lines),
      h('div', { class: 'alert', 'data-variant': 'tari', 'data-testid': 'known-never' }, icon('shield-check'),
        h('div', { class: 'alert-title' }, t('drive.known.never_h')), h('div', { class: 'alert-description' }, t('drive.known.never'))),
      h('p', { class: 'small muted' }, t('drive.known.live'))],
    footer: [h('a', { class: 'btn', 'data-variant': 'ghost', href: '/made#who' }, icon('book-open'), t('drive.nav.made'))],
  });
  document.getElementById(box.id)?.remove();
  document.body.append(box);
  init(box);
  openModal(box);
  return box;
}
