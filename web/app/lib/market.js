// SPDX-License-Identifier: MIT
// The market (docs/market.md): what public shops sell, and asks. A public shop's key never reaches our server, so a
// shopper without the shop's whole link can't open a listing's half of its pay link's key (sA) alone. They ask: this
// browser draws a secret for the ask, from which come the ask's id, a token, and an Ootle key pair made for this ask
// alone; the seller's drive answers with sA sealed to that pair (the address wrap of Send by Tari, kind 3: both keys of
// the pair are needed), bound to the ask and the listing; this browser opens it and goes to the pay link, /p/<id>#5<sA>.
// Our server relays the sealed answer, which it can't open. Nobody pays before the answer has come.
import { b64uDecode, b64uEncode } from './b64.js';
import { concat, equal, utf8 } from './bytes.js';
import { hkdf, randomBytes, sha256 } from './crypto.js';
import { enc, request } from './api.js';
import { withPow } from './pow.js';
import { deriveOotleKeys, INNER_LENGTH, sealToKeys, unwrapBlob } from './ootle.js';
import { buyUrl, openListing } from './shop.js';
import { forgetAsk, keepAsk, savedAskFor, savedAsks } from './asks.js';

export { forgetAsk, keepAsk, savedAskFor, savedAsks };

const V2 = 'mutis/v2';
const KIND = '8';                       // fragment kind 8: a market ask's secret (6 a shop's key, 5 a pay link)
const BIND = 'mutis-market-ask-v1|';
const VERSION = 1;
const ID = /^[A-Za-z0-9_-]{22}$/;

// ---------- the API (docs/api.md "Market") ----------

export function browse({ q = '', kind = '', cursor = '' } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (kind) params.set('kind', kind);
  if (cursor) params.set('cursor', cursor);
  const query = params.toString();
  return request('GET', `/market${query ? `?${query}` : ''}`);
}

const askRead = (askId, token) => request('GET', `/market/asks/${enc(askId)}`, { headers: { 'X-Mutis-Ask': b64uEncode(token) } });
export const waitingAsks = (headers) => request('GET', '/me/market/asks', { headers });
const putAnswer = (askId, body, headers) => request('PUT', `/me/market/asks/${enc(askId)}`, { json: body, headers, expect: 'none' });

// ---------- an ask's keys ----------

// Everything of an ask comes from its secret: its id (our server keeps it), the token that reads it (our server keeps
// its hash), and its key pair (our server keeps the public halves, which the seller's drive seals to).
export async function askParts(secret) {
  if (!(secret instanceof Uint8Array) || secret.length !== 32) throw new TypeError('an ask secret is 32 bytes');
  const [id, token, keys] = await Promise.all([hkdf(secret, V2, 'market-ask-id', 16), hkdf(secret, V2, 'market-ask', 32),
    deriveOotleKeys(secret, 'ask')]);
  return { askId: b64uEncode(id), token, keys };
}

// What a sealed answer binds to: this ask and this listing, so an answer moved to another ask or listing doesn't open.
const binding = (askId, shareId) => sha256(utf8(BIND + askId + '|' + shareId));

// The 65 bytes the seller's drive seals: a version, sA, the binding.
export async function answerInner(askId, shareId, sA) {
  if (sA.length !== 32) throw new TypeError('sA must be 32 bytes');
  const inner = concat(Uint8Array.of(VERSION), sA, await binding(askId, shareId));
  if (inner.length !== INNER_LENGTH) throw new TypeError('inner payload must be 65 bytes');
  return inner;
}

// The shopper's side: sA from a sealed answer, or a TypeError when it isn't one for this ask and listing.
export async function openAnswer(parts, shareId, sealed) {
  const inner = await unwrapBlob(parts.keys, sealed, 3);
  if (inner.length !== INNER_LENGTH || inner[0] !== VERSION || !equal(inner.subarray(33), await binding(parts.askId, shareId))) {
    throw new TypeError('not an answer to this ask');
  }
  return inner.slice(1, 33);
}

// ---------- links ----------

export function askFragment(secret) {
  return KIND + b64uEncode(secret);
}

// `#8…` -> the ask's secret, or null.
export function parseAskFragment(hash) {
  const f = String(hash ?? '').replace(/^#/, '');
  if (f[0] !== KIND || f.length !== 44) return null;
  try {
    const s = b64uDecode(f.slice(1));
    return s.length === 32 ? s : null;
  } catch {
    return null;
  }
}

// ---------- the shopper ----------

// Ask the listing's seller (POST /market/asks with a proof of work). -> the kept entry.
export async function ask(listing, { signal, onProgress } = {}) {
  const secret = randomBytes(32);
  const parts = await askParts(secret);
  const body = {
    ask_id: parts.askId, share_id: listing.share_id, owner_pk: b64uEncode(parts.keys.ownerPk),
    view_pk: b64uEncode(parts.keys.viewPk), token_hash: b64uEncode(await sha256(parts.token)),
  };
  await withPow('ask', (pow, judge) => request('POST', '/market/asks', { json: { ...body, pow }, headers: judge }), { signal, onProgress });
  const entry = {
    s: b64uEncode(secret), askId: parts.askId, shareId: listing.share_id, shop: listing.shop?.path ?? null,
    title: listing.title, priceUt: listing.price_ut, at: Math.floor(Date.now() / 1000),
  };
  keepAsk(entry);
  return entry;
}

// Where an ask stands: {state: 'waiting'} | {state: 'answered', buy (the pay link)} | {state: 'ended'} (it ran out or
// its listing left the market) | {state: 'bad'} (an answer that doesn't open for this ask: shown, never followed).
export async function askState(entry, origin = globalThis.location?.origin) {
  const parts = await askParts(b64uDecode(entry.s));
  let got;
  try {
    got = await askRead(parts.askId, parts.token);
  } catch (e) {
    if (e?.code === 'not_found') return { state: 'ended' };
    throw e;
  }
  if (got.state !== 'answered' || typeof got.answer !== 'string') return { state: 'waiting', expiresAt: got.expires_at };
  try {
    const sA = await openAnswer(parts, entry.shareId, b64uDecode(got.answer));
    return { state: 'answered', buy: buyUrl(origin, entry.shareId, sA) };
  } catch {
    return { state: 'bad' };
  }
}

// ---------- the seller's drive ----------

// Answer what waits for this drive's public shop: each listing's sA, opened here with the shop key, sealed to the ask's
// key pair. `state` is lib/shop.js myShop()'s. An ask whose keys don't seal (not points) is refused, so it ends. A
// listing this page doesn't know yet is left for the next round. -> how many were answered.
export async function answerAsks(state, headers) {
  if (!state || state.shop.mode !== 'public' || state.shop.state !== 'open') return 0;
  const { asks = [] } = await waitingAsks(headers);
  const listed = new Map((state.shop.listings ?? []).map((l) => [l.share_id, l]));
  let answered = 0;
  for (const a of asks) {
    const l = listed.get(a.share_id);
    if (!l || !ID.test(a.ask_id ?? '')) continue;
    let sA;
    try {
      sA = await openListing(state.key, l.share_id, b64uDecode(l.link_ct));
    } catch {
      continue;            // sealed under a key this page doesn't hold: the drive's next round, with the shop as it is
    }
    let sealed;
    try {
      sealed = await sealToKeys({ ownerPk: b64uDecode(a.owner_pk), viewPk: b64uDecode(a.view_pk) },
        await answerInner(a.ask_id, a.share_id, sA), 3);
    } catch {
      await putAnswer(a.ask_id, { refused: true }, headers).catch(() => {});      // not keys anyone can open with
      continue;
    } finally {
      sA.fill(0);
    }
    try {
      await putAnswer(a.ask_id, { answer: b64uEncode(sealed) }, headers);
      answered++;
    } catch {
      // ended meanwhile (404), or answered from another tab (409): the next ask goes on
    }
  }
  return answered;
}
