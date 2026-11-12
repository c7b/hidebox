// SPDX-License-Identifier: MIT
// A drive's shop (docs/shop.md): a public page that lists some of the drive's pay links, with the words its owner
// chose to publish. Buying is the pay link's own page (/p/<id>#5…, lib/pay.js), unchanged.
//
// The shop's link is /shop/<username>#6<shop key> (docs/shop.md "The address"; a shop made before names: /shop/<id>#6…).
// The username is the owner's pick: ASCII a-z, 0-9 and single hyphens, 3 to 30 characters (our server decides; the
// checks here only say why early). The shop key is drawn here and, in a private shop, never leaves the browser in the
// clear: our server keeps it wrapped under a key from the drive's vault key (`key_wrap`), so the owner's drive on any
// device can show the shop's link again, and reading the shop takes a token only the key makes (readToken). A public
// shop is readable by anyone and listed in the market (lib/market.js, docs/market.md), and its key still never reaches
// our server: a visitor without the whole link asks the seller's drive for a listing's half instead. Each listing carries its pay link's own half
// of its key (sA, the part after a /p/ link's #) sealed with the shop key and bound to the link's id (`link_ct`): a
// visitor with the shop's whole link opens it and builds the /p/ link; our server, which holds the other half (sB)
// of every pay link, can't put the two together from what it stores.
import { b64uDecode, b64uEncode } from './b64.js';
import { concat, utf8 } from './bytes.js';
import { aesGcmDecrypt, aesGcmEncrypt, hkdf, randomBytes, sha256 } from './crypto.js';
import { enc, request } from './api.js';
import { parsePayFragment, payFragment } from './pay.js';

const V2 = 'mutis/v2';
const KIND = '6';                       // fragment kind 6: a shop's key (1, 2 links; 3, 4 Tari sends; 5 a pay link)
const KEY_AAD = utf8('mutis-shop-key-v1');
const LISTING_AAD = 'mutis-shop-listing-v1:';
const SHOP_ID = /^[A-Za-z0-9_-]{22}$/;
// A username as our server stores it (server/mutis/shop.py username()).
export const USERNAME = /^(?=.{3,30}$)[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SHOP_REF = (ref) => USERNAME.test(ref) || SHOP_ID.test(ref);

// ---------- the API (docs/api.md "Shop"); the owner's routes take the drive's session ----------

export const getMyShop = (headers) => request('GET', '/me/shop', { headers });
export const putMyShop = (body, headers) => request('PUT', '/me/shop', { json: body, headers });
export const deleteMyShop = (headers) => request('DELETE', '/me/shop', { headers, expect: 'none' });
export const putListing = (shareId, body, headers) => request('PUT', `/me/shop/listings/${enc(shareId)}`, { json: body, headers });
export const deleteListing = (shareId, headers) => request('DELETE', `/me/shop/listings/${enc(shareId)}`, { headers, expect: 'none' });
// The shop's data: no session. A private shop answers only to its read token; a public one to anyone, with its key.
export const publicShop = (ref, token = null) => request('GET', `/shop/${enc(ref)}`,
  token ? { headers: { 'X-Mutis-Shop': b64uEncode(token) } } : {});

// ---------- keys ----------

export const newShopKey = () => randomBytes(32);
const wrapKey = (vaultKey) => hkdf(vaultKey, V2, 'shop-key-wrap', 32);
const listingKey = (shopKey) => hkdf(shopKey, V2, 'shop-listing', 32);
const listingAad = (shareId) => utf8(LISTING_AAD + shareId);

// What a holder of the shop key shows to read a private shop, and the hash our server keeps of it.
export const readToken = (shopKey) => hkdf(shopKey, V2, 'shop-read', 32);
export const tokenHash = async (shopKey) => sha256(await readToken(shopKey));

// Why a typed name won't do, before our server says so: 'short', 'long', 'chars' (anything but a-z, 0-9, hyphens),
// 'hyphens' (at either end, or two together); null when it may. Capitals fold.
export function nameProblem(text) {
  const v = String(text ?? '');
  if (v.length < 3) return 'short';
  if (v.length > 30) return 'long';
  if (!/^[A-Za-z0-9-]+$/.test(v)) return 'chars';
  return USERNAME.test(v.toLowerCase()) ? null : 'hyphens';
}

// The shop key wrapped under the drive's: iv ‖ AES-GCM (60 bytes), what our server keeps.
export async function wrapShopKey(vaultKey, shopKey, { iv = randomBytes(12) } = {}) {
  if (shopKey.length !== 32) throw new TypeError('a shop key is 32 bytes');
  return concat(iv, await aesGcmEncrypt(await wrapKey(vaultKey), iv, shopKey, KEY_AAD));
}

export async function unwrapShopKey(vaultKey, wrapped) {
  if (wrapped.length !== 60) throw new TypeError('a wrapped shop key is 60 bytes');
  return aesGcmDecrypt(await wrapKey(vaultKey), wrapped.subarray(0, 12), wrapped.subarray(12), KEY_AAD);
}

// A pay link's sA sealed for the shop, bound to the link's id (a listing moved to another link doesn't open).
export async function sealListing(shopKey, shareId, sA, { iv = randomBytes(12) } = {}) {
  if (sA.length !== 32) throw new TypeError('sA must be 32 bytes');
  return concat(iv, await aesGcmEncrypt(await listingKey(shopKey), iv, sA, listingAad(shareId)));
}

export async function openListing(shopKey, shareId, sealed) {
  if (sealed.length !== 60) throw new TypeError('a sealed listing is 60 bytes');
  return aesGcmDecrypt(await listingKey(shopKey), sealed.subarray(0, 12), sealed.subarray(12), listingAad(shareId));
}

// ---------- links ----------

export function shopFragment(shopKey) {
  if (shopKey.length !== 32) throw new TypeError('a shop key is 32 bytes');
  return KIND + b64uEncode(shopKey);
}

// `#6…` -> the shop key, or null.
export function parseShopFragment(hash) {
  const f = String(hash ?? '').replace(/^#/, '');
  if (f[0] !== KIND || f.length !== 44) return null;
  try {
    const key = b64uDecode(f.slice(1));
    return key.length === 32 ? key : null;
  } catch {
    return null;
  }
}

// A private shop's link carries its key after the #; a public shop's address is enough on its own.
export function shopUrl(origin, ref, shopKey) {
  if (!SHOP_REF(ref)) throw new TypeError('bad shop address');
  return shopKey ? `${origin}/shop/${ref}#${shopFragment(shopKey)}` : `${origin}/shop/${ref}`;
}

const refOf = (shop) => shop.username ?? shop.shop_id;

// What "Buy and open" opens: the pay link itself, /p/<id>#5<sA>.
export function buyUrl(origin, shareId, sA) {
  if (!SHOP_ID.test(shareId)) throw new TypeError('bad share id');
  return `${origin}/p/${shareId}#${payFragment(sA)}`;
}

// sA of a pay link this browser made (lib/links.js remembers its URL), or null.
export function sAOf(url) {
  try {
    return parsePayFragment(new URL(url).hash);
  } catch {
    return null;
  }
}

// ---------- the owner's shop ----------

// GET /me/shop, with the shop's link rebuilt from the wrapped key: {shop, key, url, address} or null while it's off.
// `url` is the whole link, the key after its # (it buys at once, in either mode); `address` is /shop/<name> with nothing
// after it: what a public shop is found at (Ask for it there), the readable part of a private one.
export async function myShop(identity, headers, origin = globalThis.location?.origin) {
  const { shop } = await getMyShop(headers);
  if (!shop) return null;
  const key = await unwrapShopKey(identity.vaultKey, b64uDecode(shop.key_wrap));
  const open = shop.state === 'open';
  return {
    shop, key,
    url: open ? shopUrl(origin, refOf(shop), key) : null,
    address: open ? shopUrl(origin, refOf(shop), null) : null,
  };
}

// Turn the shop on: a fresh key, wrapped here, its token's hash, and the name; our server picks the id. Private.
export async function openShop(identity, { title, bio, username }, headers, origin = globalThis.location?.origin) {
  const key = newShopKey();
  const { shop } = await putMyShop({
    title, bio, username,
    key_wrap: b64uEncode(await wrapShopKey(identity.vaultKey, key)), token_hash: b64uEncode(await tokenHash(key)),
  }, headers);
  return { shop, key, url: shopUrl(origin, refOf(shop), key) };
}

// Change the name, the title or the bio of the shop as it is (`state` from myShop); a shop made before names adds its
// token's hash with its first name.
export async function saveShop(state, { title, bio, username }, headers) {
  const body = { title, bio, key_wrap: state.shop.key_wrap, ...(username ? { username } : {}) };
  if (!state.shop.has_token) body.token_hash = b64uEncode(await tokenHash(state.key));
  return (await putMyShop(body, headers)).shop;
}

// Public (anyone can read it, and it is in the market) or private again: the key stays as it is, here, in both.
export async function setMode(identity, state, mode, headers) {
  const { shop } = state;
  const body = { title: shop.title, bio: shop.bio, mode, key_wrap: shop.key_wrap };
  if (!shop.has_token) body.token_hash = b64uEncode(await tokenHash(state.key));
  return (await putMyShop(body, headers)).shop;
}

// A new key for the shop, with every listing's half of its pay link's key opened with the old key and sealed with the
// new one, all in one request: links with the old key stop working (for a link that was posted too widely).
export async function newKey(identity, state, headers) {
  const { shop } = state;
  const key = newShopKey();
  const relisted = [];
  for (const l of shop.listings) {
    const sA = await openListing(state.key, l.share_id, b64uDecode(l.link_ct));
    relisted.push({ share_id: l.share_id, link_ct: b64uEncode(await sealListing(key, l.share_id, sA)) });
  }
  return (await putMyShop({
    title: shop.title, bio: shop.bio, relisted,
    key_wrap: b64uEncode(await wrapShopKey(identity.vaultKey, key)), token_hash: b64uEncode(await tokenHash(key)),
  }, headers)).shop;
}

// List a pay link (or change its words): its sA sealed with the shop key. -> the listing as our server keeps it.
// `keyWrap` names the shop key it is sealed with (the shop's key_wrap as this page has it): our server refuses a listing
// sealed with a key the shop no longer has (409 key_changed), such as one a tab kept after the shop went private.
export async function listLink(shopKey, shareId, sA, { title, description }, headers, keyWrap) {
  const linkCt = b64uEncode(await sealListing(shopKey, shareId, sA));
  return (await putListing(shareId, { title, description, link_ct: linkCt, key_wrap: keyWrap }, headers)).listing;
}

// ---------- the visitor ----------

// The shop's page with each listing's /p/ link, where the shop key opens it; `buy` null for one that doesn't. With the key
// from the link (a private shop, or a public one shared with its key), the read token goes along. Without one, only a
// public shop answers; then no listing has `buy`, and `keyless` says so: each is asked for (lib/market.js).
export async function openShopPage(ref, shopKey, origin = globalThis.location?.origin) {
  const page = await publicShop(ref, shopKey ? await readToken(shopKey) : null);
  const key = shopKey;
  if (!key) {
    if (page.mode !== 'public') throw new TypeError('no shop key');
    return { ...page, keyless: true, items: (page.items ?? []).map((it) => ({ ...it, buy: null })) };
  }
  if (key.length !== 32) throw new TypeError('no shop key');
  const items = await Promise.all((page.items ?? []).map(async (it) => {
    let buy = null;
    try {
      buy = buyUrl(origin, it.share_id, await openListing(key, it.share_id, b64uDecode(it.link_ct)));
    } catch {
      buy = null;     // sealed with another key, or not for this link: shown, never offered
    }
    return { ...it, buy };
  }));
  return { ...page, items };
}
