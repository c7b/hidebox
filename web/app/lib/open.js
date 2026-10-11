// SPDX-License-Identifier: MIT
// Open a link (§2.4 "Open", §5.3): status → access token → peek (no view used) → open (the atomic
// view, only after the user taps "Open it") → fetch ciphertext → decrypt in this tab. Each step is
// separate so the viewer can stop for a password, the glass box or the program warning.
import { b64uDecode, b64uEncode } from './b64.js';
import { sha256 } from './crypto.js';
import { decryptBlob, decryptMeta, deriveItemKeys, parseHeader } from './format.js';
import { linkProof, shareKeys, unwrapFileKey } from './share.js';
import { ApiError, blobDone, blobRange, openShare, peekShare, shareStatus } from './api.js';
import { solvePow } from './pow.js';

// -> {state, mode, needs_password, kdf}; a link that ended throws ApiError 'gone' (details.reason).
export const linkStatus = shareStatus;

// The headers that prove access, from what the link or delivery carried: {s} for a plain link or a
// Tari delivery, {s0, password} for link + password, {password} for password only.
export async function accessFor(status, { s, s0, password } = {}) {
  let secret = s;
  const headers = {};
  if (status.mode === 'link_password' || status.mode === 'password') {
    const { linkPasswordSecret, passwordOnlySecret } = await import('./password.js');
    if (status.mode === 'link_password') {
      secret = await linkPasswordSecret(s0, password, status.kdf);
      headers['X-Mutis-Link'] = b64uEncode((await linkProof(s0)).proof);
    } else {
      secret = await passwordOnlySecret(password, status.kdf);
    }
  }
  if (!secret) throw new TypeError('missing link secret');
  const { wrapKey, accessToken } = await shareKeys(secret);
  headers['X-Mutis-Access'] = b64uEncode(accessToken);
  return { wrapKey, headers };
}

// After a few wrong tries on a password-only link the server wants a PoW with each try (428
// pow_required, §4.7). This solves it and tries once more. A 428 with retryAfter means "wait first":
// it is passed on for the UI to count down.
async function withPasswordPow(call, opts) {
  try {
    return await call({});
  } catch (e) {
    if (!(e instanceof ApiError && e.code === 'pow_required' && e.details.purpose === 'password' && !e.retryAfter)) throw e;
    return call({ pow: await solvePow('password', { ...opts, minDifficulty: e.details.difficulty ?? 0 }) });
  }
}

// "What we know about this link": uses no view. opts: {signal, onProgress} for a password PoW.
export async function peek(shareId, access, opts = {}) {
  return withPasswordPow((body) => peekShare(shareId, access.headers, body), opts);
}

// Header + the file key's wrap (by a link or by the vault key) + metadata -> everything a reader needs.
async function unlock(headerB64u, wrapKey, wrappedB64u, metaB64u) {
  const header = b64uDecode(headerB64u);
  const { chunkCount, salt } = parseHeader(header);
  const headerHash = await sha256(header);
  const fk = await unwrapFileKey(wrapKey, headerHash, b64uDecode(wrappedB64u));
  const { contentKey, metaKey } = await deriveItemKeys(fk, salt);
  const meta = await decryptMeta(metaKey, headerHash, b64uDecode(metaB64u));
  return { meta, fk, contentKey, headerHash, chunkCount };
}

const transfer = (res) => ({
  sizeStored: res.size_stored, ticket: res.ticket, ticketExpiresAt: res.ticket_expires_at,
  inline: res.inline_ct ? b64uDecode(res.inline_ct) : null,
});

// Consumes one view. -> {meta, burned, viewsLeft, ...what fetchContent needs}
export async function openItem(shareId, access, opts = {}) {
  const res = await withPasswordPow((body) => openShare(shareId, access.headers, body), opts);
  const unlocked = await unlock(res.header, access.wrapKey, res.wrapped_key, res.meta_ct);
  return { ...unlocked, ...transfer(res), burned: res.burned, viewsLeft: res.views_left };
}

// P1, kept files: a row of GET /me/items opened with this locker's vault key (no view is used).
export async function openKept(identity, row, headers) {
  const unlocked = await unlock(row.header, identity.vaultKey, row.owner_wrap, row.meta_ct);
  const { openMyItem } = await import('./api-locker.js');
  const res = await openMyItem(row.item_id, headers);
  return { ...unlocked, ...transfer({ size_stored: row.size_stored, ...res }), burned: false, viewsLeft: null };
}

// Downloads (or takes the inline copy) and decrypts everything; returns plaintext parts only after
// every chunk verified. Then tells the server the ticket is finished.
export async function fetchContent(opened, { onProgress, signal } = {}) {
  const readChunk = opened.inline
    ? async (i, start, end) => opened.inline.subarray(start, end)
    : (i, start, end) => blobRange(opened.ticket, start, end, signal);
  const parts = await decryptBlob({
    contentKey: opened.contentKey, headerHash: opened.headerHash, chunkCount: opened.chunkCount,
    sizeStored: opened.sizeStored, plainLength: opened.meta.size, readChunk, onProgress,
  });
  // Best effort: a ticket nobody finishes expires by itself after 30 minutes.
  if (opened.ticket) await blobDone(opened.ticket).catch(() => null);
  return parts;
}
