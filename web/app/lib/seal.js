// SPDX-License-Identifier: MIT
// Seal a file or a text and give it a link (§2.4): encrypt in this tab, upload only ciphertext with
// two or three chunks in flight, then create a link whose secret never leaves the client. Used by the
// drop widget, the dead-drop page, /send, and the sidecar's hourly canary.
import { b64uDecode, b64uEncode } from './b64.js';
import { equal, utf8 } from './bytes.js';
import { randomBytes } from './crypto.js';
import { ctHash, encryptFile, encryptMeta, deriveItemKeys } from './format.js';
import { linkFragment, linkProof, newShareSecret, shareKeys, shareUrl, wrapFileKey } from './share.js';
import { ApiError, completeUpload, createShare, createUpload, deleteUpload, putChunk } from './api.js';
import { withPow } from './pow.js';

// The same number /config serves as text_max_chars (spec §9.4).
export const TEXT_MAX_CHARS = 10000;
const IN_FLIGHT = 3;

// Thrown when an upload stops part-way; pass `resume` back to sealItem() to continue from the first
// missing chunk with the same key, salt and upload. code 'aborted' (the user pressed Stop) has no
// resume: the upload was deleted.
export class SealError extends Error {
  constructor(code, cause, resume = null) {
    super(cause?.message ?? code);
    this.name = 'SealError';
    this.code = code;
    this.cause = cause;
    this.resume = resume;
  }
}

// Text length counts Unicode code points; at 4 bytes each at most, 10,000 of them stay under the
// 65,536-byte cap of §9.4, so one check enforces both.
function sourceBytes(source) {
  if (typeof source.text !== 'string') return { data: source.file, meta: { kind: 'file', name: source.name, type: source.type, mtime: source.mtime, stripped: source.stripped } };
  if (Array.from(source.text).length > TEXT_MAX_CHARS) throw new RangeError('text too long');
  return { data: utf8(source.text), meta: { kind: 'text' } };
}

const retryable = (e) => e instanceof ApiError && (e.status === 0 || e.status >= 500 || e.code === 'rate_limited');

async function putWithRetry(uploadId, chunk, headers, signal) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await putChunk(uploadId, chunk.index, chunk.ciphertext, b64uEncode(chunk.sha256), { headers, signal });
    } catch (e) {
      if (attempt >= 2 || !retryable(e) || signal?.aborted) throw e;
      await new Promise((r) => setTimeout(r, 1000 * 3 ** attempt));
    }
  }
}

// source: {file, name, type, mtime, stripped} or {text}.
// opts: {headers (Bearer, X-Mutis-Canary or none), anonymous (solve the upload PoW, or send the judge
//        pass), expiresAt (unix seconds, required unless the item is kept), dropId, keepFor (P1: an
//        Identity; the item is kept, its key wrapped under the vault key), headBytes (keep the first
//        n bytes of the stored ciphertext, for a picture of what our server holds), parent (a drive
//        folder, opened: {id, fk, salt}; the kept item goes inside it with its parent_wrap),
//        onPhase(phase, fraction), signal, resume}
// -> {itemId, uploadId, manageToken, expiresAt (the item's; null when kept), uploadExpiresAt (when
//     this upload session ends, 2 h after it started), fk, headerHash, sizeStored, chunkCount,
//     ctHash (b64u, the ciphertext hash this tab computed; the server's matched it), head (the first
//     headBytes bytes of chunk 0 as stored, or null), headers}
export async function sealItem(source, { headers = {}, anonymous = false, expiresAt = null, dropId = null, keepFor = null, parent = null, headBytes = 0, onPhase, signal, resume } = {}) {
  if (!keepFor && !Number.isSafeInteger(expiresAt)) throw new TypeError('expiresAt is required unless the item is kept');
  const { data, meta } = sourceBytes(source);
  const fk = resume?.fk ?? randomBytes(32);
  const chunks = encryptFile(data, {
    fk, salt: resume?.salt, fromIndex: resume?.fromIndex ?? 0,
    onProgress: (f) => onPhase?.('encrypting', f),
  });
  const first = (await chunks.next()).value;
  const { header, headerHash, chunkCount, sizeStored, salt } = first;
  let up = resume?.upload;
  if (!up) {
    const { metaKey } = await deriveItemKeys(fk, salt);
    const metaCt = await encryptMeta(metaKey, headerHash, { ...meta, size: data instanceof Uint8Array ? data.length : data.size });
    const body = {
      retention: keepFor ? 'kept' : 'ephemeral', header: b64uEncode(header), meta_ct: b64uEncode(metaCt), chunk_count: chunkCount,
      size_stored: sizeStored, owner_wrap: keepFor ? b64uEncode(await wrapFileKey(keepFor.vaultKey, headerHash, fk)) : null,
      expires_at: keepFor ? null : expiresAt, drop_id: dropId,
    };
    if (keepFor && parent) {
      const { wrapForFolder } = await import('./folder.js');
      body.parent_id = parent.id;
      body.parent_wrap = b64uEncode(await wrapForFolder(parent, { fk, headerHash }));
    }
    const res = anonymous
      ? await withPow('upload', (pow, judge) => createUpload({ ...body, pow }, { ...headers, ...judge }), { signal, onProgress: (f) => onPhase?.('pow', f) })
      : await createUpload(body, headers);
    up = { uploadId: res.upload_id, itemId: res.item_id, manageToken: res.manage_token, expiresAt: body.expires_at, uploadExpiresAt: res.expires_at };
  }
  const itemHeaders = up.manageToken ? { ...headers, 'X-Mutis-Manage': up.manageToken } : headers;
  const hashes = resume?.hashes ?? [];
  let head = resume?.head ?? null;
  const pending = new Map(); // chunk index -> its upload; finished uploads leave the map
  let failure = null;
  let uploaded = 0;
  let next = resume?.fromIndex ?? 0;
  try {
    for await (const chunk of chunks) {
      hashes[chunk.index] = chunk.sha256;
      if (chunk.index === 0 && headBytes) head = chunk.ciphertext.slice(0, headBytes);
      pending.set(chunk.index, putWithRetry(up.uploadId, chunk, headers, signal).then(() => {
        pending.delete(chunk.index);
        uploaded += chunk.ciphertext.length;
        onPhase?.('uploading', uploaded / sizeStored);
      }, (e) => { failure ??= e; }));
      if (pending.size >= IN_FLIGHT) await Promise.race(pending.values());
      if (failure) throw failure;
      next = chunk.index + 1;
    }
    await Promise.all(pending.values());
    if (failure) throw failure;
  } catch (e) {
    if (signal?.aborted) {
      // Stop: give the reserved space back now instead of when the upload session expires.
      await deleteUpload(up.uploadId, headers).catch(() => null);
      throw new SealError('aborted', e);
    }
    const fromIndex = pending.size ? Math.min(...pending.keys()) : next;
    throw new SealError(e instanceof ApiError ? e.code : 'read', e, { fk, salt, fromIndex, hashes, head, upload: up });
  }
  onPhase?.('finishing', 1);
  const done = await completeUpload(up.uploadId, headers);
  if (!equal(b64uDecode(done.ct_hash), await ctHash(hashes))) throw new SealError('integrity', new Error('server stored different bytes'));
  return { ...up, fk, headerHash, sizeStored, chunkCount, ctHash: done.ct_hash, head, headers: itemHeaders };
}

// mode: 'link' (key after #), 'link_password' (link + password, the default with a password) or
// 'password' (password only; no fragment). expiresAt defaults to the item's own expiry (the server
// applies the same default; a kept item's link then has none). `url` is null without an origin
// (the sidecar never shows one). -> {shareId, url, fragment, s, state, maxViews, expiresAt}
export async function createLink(item, { mode = 'link', password, maxViews = 1, expiresAt, origin = globalThis.location?.origin } = {}) {
  const body = { mode, link_verifier: null, kdf: null, max_views: maxViews, expires_at: expiresAt ?? item.expiresAt ?? null };
  let s;
  let fragment = null;
  if (mode === 'link') {
    s = newShareSecret();
    fragment = linkFragment(1, s);
  } else if (mode === 'link_password' || mode === 'password') {
    // Loaded only when someone picks a password: it carries the common-password list.
    const { linkPasswordSecret, newKdfParams, passwordOnlySecret } = await import('./password.js');
    body.kdf = newKdfParams();
    if (mode === 'link_password') {
      const s0 = newShareSecret();
      s = await linkPasswordSecret(s0, password, body.kdf);
      body.link_verifier = b64uEncode((await linkProof(s0)).verifier);
      fragment = linkFragment(2, s0);
    } else {
      s = await passwordOnlySecret(password, body.kdf);
    }
  } else {
    throw new TypeError('unknown link mode');
  }
  const { wrapKey, accessVerifier } = await shareKeys(s);
  body.wrapped_key = b64uEncode(await wrapFileKey(wrapKey, item.headerHash, item.fk));
  body.access_verifier = b64uEncode(accessVerifier);
  const res = await createShare(item.itemId, body, item.headers);
  return {
    shareId: res.share_id, url: origin ? shareUrl(origin, res.share_id, fragment) : null, fragment, s,
    state: res.state, maxViews: res.max_views, expiresAt: res.expires_at,
  };
}
