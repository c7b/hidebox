// SPDX-License-Identifier: MIT
// "What we know about this link" (spec §12.3.5, 11-brand §10.9): the glass box. Every value the
// server holds for the link and its file, under its real column name, printed from the API's own
// answer (peek for a link holder, manage for the uploader); then what is stored nowhere.
import { h } from './lines.js';
import { formatDate, t } from '../lib/i18n.js';
import { b64uDecode, b64uEncode, hex } from '../lib/b64.js';
import { saveFile } from '../lib/download.js';
import { storedBytes } from '../lib/api.js';
import { linkProof, parseFragment, shareKeys } from '../lib/share.js';
import { errorBanner } from './errors.js';

// Headers that prove a link the card made, from the secrets this tab made it with.
export async function linkAccess(link) {
  const headers = { 'X-Mutis-Access': b64uEncode((await shareKeys(link.s)).accessToken) };
  if (link.mode === 'link_password') headers['X-Mutis-Link'] = b64uEncode((await linkProof(parseFragment(link.fragment).s)).proof);
  return headers;
}

const hourText = (unix) => (unix ? formatDate(unix * 1000, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC' : '—');
const short = (b64) => (b64 ? hex(b64uDecode(b64)).slice(0, 16) + '…' : '—');

function row(column, value, what) {
  return h('div', { class: 'a-known-row' },
    h('dt', {}, h('code', {}, column)),
    h('dd', {}, h('span', { class: 'a-known-value mono' }, value), what ? h('span', { class: 'a-known-what' }, what) : null));
}

function rows({ share, item }, kdf) {
  const password = share.mode !== 'link';
  return [
    h('h4', { class: 'a-known-table' }, 'shares'),
    h('dl', {},
      row('id', share.id, t('known.id')),
      row('mode · state', `${share.mode} · ${share.state}`, t('known.mode')),
      row('max_views · views_used', `${share.max_views ?? '—'} · ${share.views_used}`, t('known.views')),
      row('expires_at', hourText(share.expires_at), t('known.expires')),
      row('created_hour', hourText(share.created_hour), t('known.created')),
      row('wrapped_key', t('known.bytes', { n: 60 }), t('known.wrapped')),
      row('access_hash', t('known.bytes', { n: 32 }), t('known.access')),
      share.mode === 'link_password' ? row('link_hash', t('known.bytes', { n: 32 }), t('known.link_hash')) : null,
      row('kdf', password && kdf ? t('known.kdf_value', { iter: kdf.iter }) : t('known.none'), t('known.kdf'))),
    h('h4', { class: 'a-known-table' }, 'items'),
    h('dl', {},
      row('retention · lane', `${item.retention} · ${item.lane}`, t('known.retention')),
      row('owner', item.owner === 'nobody' ? t('known.owner_nobody') : t('known.owner_locker'), t('known.owner')),
      row('header', t('known.header_value', { size: 32, v: 1, n: item.chunk_count }), t('known.header')),
      row('meta_ct', t('known.encrypted'), t('known.meta')),
      row('chunk_count · size_stored', `${item.chunk_count} · ${t('known.bytes', { n: item.size_stored })}`, t('known.size')),
      row('ct_hash', short(item.ct_hash), t('known.ct_hash')),
      row('created_hour', hourText(item.created_hour), t('known.created'))),
    h('h4', { class: 'a-known-table' }, t('known.request')),
    h('dl', {}, row(t('known.ip'), t('known.ip_value'), t('known.ip_what'))),
  ];
}

// -> {toggle, panel}. load(): {share, item} from peek or manage. access(): the headers that prove the
// link (for "Download the stored bytes"), or null. kdf: the link's PBKDF2 parameters when it has a password.
export function knownPanel({ cfg, load, access = null, kdf = null, toggleTestid = 'known-toggle', id = 'a-known' }) {
  const panel = h('section', { class: 'a-known', id, 'data-testid': 'known-panel', hidden: true, 'aria-labelledby': `${id}-h` });
  const toggle = h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': toggleTestid, 'aria-expanded': 'false', 'aria-controls': id },
    t('known.toggle'));
  let loaded = false;
  toggle.addEventListener('click', async () => {
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (!open || loaded) return;
    loaded = true;
    panel.replaceChildren(h('p', { class: 'a-working mono' }, t('known.loading')));
    try {
      fill(await load());
    } catch (e) {
      loaded = false;
      panel.replaceChildren(errorBanner(e));
    }
  });

  function fill(data) {
    const notStored = ['name', 'contents', 'key', 'password', 'email', 'ip', 'browser'].map((k) => h('li', {}, t(`known.never.${k}`)));
    panel.replaceChildren(...[   // without the null lines, which would read "null"
      h('h3', { id: `${id}-h` }, t('known.title')),
      h('p', { class: 'a-known-sub' }, t('known.sub')),
      ...rows(data, kdf),
      access ? storedButton(data.share.id) : null,
      h('h4', {}, t('known.never_h')),
      h('ul', { class: 'a-known-never' }, notStored),
      h('div', { class: 'a-known-foot' },
        h('p', {}, t('claim.c5', { ticket_min: Math.round(cfg.retention.ticket_s / 60), tombstone_days: cfg.retention.tombstone_days })),
        h('p', {}, t('claim.c5db', { db_backup_days: cfg.retention.db_backup_days })),
        cfg.hosting?.snapshots !== 'off' ? h('p', {}, t('claim.c5snap')) : null,
        h('p', { class: 'a-known-end' }, t('known.end')))].filter(Boolean));
  }

  // P1: the ciphertext exactly as our disk holds it, without using a view.
  function storedButton(shareId) {
    const after = h('p', { class: 'a-known-after', hidden: true }, t('known.stored_after'));
    const button = h('button', { type: 'button', class: 'a-btn' }, t('known.stored'));
    button.addEventListener('click', async () => {
      try {
        const bytes = await storedBytes(shareId, await access());
        saveFile([bytes], `mutis-stored-${shareId}.bin`);
        after.hidden = false;
      } catch (e) {
        after.replaceWith(errorBanner(e));
      }
    });
    return h('div', { class: 'a-known-stored' }, button, h('span', { class: 'a-known-what' }, t('known.stored_what')), after);
  }

  return { toggle, panel };
}
