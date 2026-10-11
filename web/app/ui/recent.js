// SPDX-License-Identifier: MIT
// "Your recent drops (only on this device)" (11-brand §10.2): what this browser sealed lately, with
// no names (the device keeps only ids and manage tokens). States (and the strings for them) load only
// when the list is opened, one manage request per link.
import { h } from '../lib/dom.js';
import { formatDate, formatRelative, t } from '../lib/i18n.js';
import { deleteItem, manageShare } from '../lib/api.js';
import { recentDrops, removeRecentDrop } from '../lib/store.js';
import { toast } from './core.js';
import { more } from './more.js';

// first_opened_min is unix seconds, floored to the minute (server schema, brand P-25).
function stateText(share) {
  if (share.state !== 'active') {
    if (share.max_views === 1 && share.first_opened_min) return t('recent.opened', { time: formatDate(share.first_opened_min * 1000, { dateStyle: 'medium', timeStyle: 'short' }) });
    return t('recent.gone');
  }
  if (share.views_used > 0 && share.max_views !== null) return t('recent.left', { n: share.views_left, m: share.max_views });
  return t('recent.waiting', { relative: formatRelative(share.expires_at * 1000) });
}

function row(drop, live) {
  const status = h('span', { class: 'md-recent-state' }, t('recent.checking'));
  const del = h('button', { type: 'button', class: 'a-linkbtn a-linkbtn--exit' }, t('recent.delete'));
  const li = h('li', { class: 'md-recent-row' },
    h('span', { class: 'mono' }, t('recent.link', { tail: drop.share_id.slice(-4) })), status, del);
  const headers = { 'X-Mutis-Manage': drop.manage_token };
  manageShare(drop.share_id, headers).then(({ share }) => {
    status.textContent = stateText(share);
  }, (e) => {
    if (e?.code === 'not_found' || e?.code === 'gone') {
      removeRecentDrop(drop.share_id);
      li.remove();
    } else {
      status.textContent = t('recent.unknown');
    }
  });
  del.addEventListener('click', async () => {
    try {
      await deleteItem(drop.item_id, headers);
    } catch (e) {
      if (e?.code !== 'not_found' && e?.code !== 'gone') return toast(t('error.network'), live);
    }
    removeRecentDrop(drop.share_id);
    li.remove();
    toast(t('toast.deleted'), live);
  });
  return li;
}

export function recentList({ live }) {
  const list = h('ul', { class: 'md-recent-list' });
  const box = h('details', { class: 'md-recent' }, h('summary', {}, t('recent.h')), list);
  box.addEventListener('toggle', async () => {
    if (!box.open || list.childElementCount) return;
    await more();
    list.append(...recentDrops().map((d) => row(d, live)));
  });
  return box;
}
