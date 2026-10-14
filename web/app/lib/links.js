// SPDX-License-Identifier: MIT
// The drive's links (16-drive-design §3, 16-drive-architecture §2.3): a link on a file or a folder of the
// drive, under one of the named rules, made in this browser. Every link has its own 32-byte secret after
// the `#` (spec §4.6); with a secret word the link carries s0 and the word makes the key. A folder link
// wraps the folder's key, which opens everything below it and nothing above. Links this browser made
// are remembered next to the drive's key (IndexedDB, this device only), so the Links tab can copy them
// again; another device lists the same links without their secrets.
import { b64uEncode } from './b64.js';
import { createShare, deleteShare } from './api.js';
import { linkFragment, linkProof, newShareSecret, shareKeys, shareUrl, wrapFileKey } from './share.js';
import { idbGet, idbPut } from './idb.js';

// "A few times" is a fixed number (16-drive-design §0 item 4: the select was deleted).
export const FEW = 3;
// The courier's inner flags (16-drive-architecture §2.3): bit 1 says the link opens a folder.
export const FLAG_FOLDER = 2;
const DAY = 86400;
// "It ends": Tomorrow, In a week, When I stop it.
export const ENDS = { day: DAY, week: 7 * DAY, never: null };

const nowS = () => Math.floor(Date.now() / 1000);

// The exit rule of a link, as POST /items/{id}/shares takes it.
// rule: {opens: 'once' | 'few' | 'nolimit', ends: 'day' | 'week' | 'never'}
// limits: the drive's class from /config. On a drive's first day the server allows no link without a
// count, so "No limit" there is the most opens that day allows (the dialog says so).
export function exitRule(rule, { firstDay = false, limits = null, now = nowS() } = {}) {
  const maxViews = rule.opens === 'once' ? 1 : rule.opens === 'few' ? FEW : firstDay ? (limits?.max_views ?? null) : null;
  const span = ENDS[rule.ends];
  return { max_views: maxViews, expires_at: span == null ? null : now + span };
}

// item: an opened drive item ({id, fk, headerHash}); rule as exitRule() plus {word, thenDelete}, or
// {maxViews, expiresAt} given directly (Send by Tari). -> {shareId, url, fragment, s, maxViews,
// expiresAt, itemExpiresAt}
export async function makeLink(item, rule, { headers, origin = globalThis.location?.origin, firstDay = false, limits = null } = {}) {
  const body = 'maxViews' in rule
    ? { max_views: rule.maxViews, expires_at: rule.expiresAt ?? null }
    : exitRule(rule, { firstDay, limits });
  let s;
  let fragment;
  if (rule.word) {
    // Loaded only when someone asks for a word: it carries the key stretching.
    const { linkPasswordSecret, newKdfParams } = await import('./password.js');
    const s0 = newShareSecret();
    body.mode = 'link_password';
    body.kdf = newKdfParams();
    s = await linkPasswordSecret(s0, rule.word, body.kdf);
    body.link_verifier = b64uEncode((await linkProof(s0)).verifier);
    fragment = linkFragment(2, s0);
  } else {
    s = newShareSecret();
    body.mode = 'link';
    body.kdf = null;
    body.link_verifier = null;
    fragment = linkFragment(1, s);
  }
  if (rule.thenDelete) body.then_delete = true;
  const { wrapKey, accessVerifier } = await shareKeys(s);
  body.wrapped_key = b64uEncode(await wrapFileKey(wrapKey, item.headerHash, item.fk));
  body.access_verifier = b64uEncode(accessVerifier);
  const res = await createShare(item.id, body, headers);
  return {
    shareId: res.share_id, url: origin ? shareUrl(origin, res.share_id, fragment) : null, fragment, s,
    maxViews: res.max_views, expiresAt: res.expires_at, itemExpiresAt: res.item_expires_at ?? null,
  };
}

// Stop a link now (DELETE /s/{id}, the owner's session). A file set to leave with its link leaves.
export const stopLink = (shareId, headers) => deleteShare(shareId, headers);

// --- what this browser remembers about its links -----------------------------------------------------

const key = (identity) => `links:${identity.id}`;

// The links this browser sent by Tari, by share id, so a row can wear "Sent by Tari" (the server can't
// tell: to it, a sent link is a link). Filled by knownLinks() and rememberLink().
export const SENT = new Set();

// -> {shareId: {url, at, word?, sent?: {address, kind, tx}}}
export async function knownLinks(identity) {
  let all = {};
  try {
    all = (await idbGet('identity', key(identity))) ?? {};
  } catch {
    // Storage blocked: nothing remembered.
  }
  for (const [id, rec] of Object.entries(all)) if (rec?.sent) SENT.add(id);
  return all;
}

export async function rememberLink(identity, shareId, record) {
  try {
    const all = await knownLinks(identity);
    all[shareId] = { ...all[shareId], ...record, at: all[shareId]?.at ?? nowS() };
    if (record.sent) SENT.add(shareId);
    await idbPut('identity', key(identity), all);
  } catch {
    // Storage blocked: the link still works; this browser just can't copy it again later.
  }
}
