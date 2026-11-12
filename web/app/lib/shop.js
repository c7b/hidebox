// SPDX-License-Identifier: MIT
// A drive's shop (docs/shop.md): a public page that lists some of the drive's pay links, with the words its owner
// chose to publish. Buying is the pay link's own page (/p/<id>#5…, lib/pay.js), unchanged.
//
// The shop's link is /shop/<id>#6<shop key>. The id is our server's, random. The shop key is drawn here and never
// leaves the browser in the clear: our server keeps it wrapped under a key from the drive's vault key (`key_wrap`),
// so the owner's drive on any device can show the shop's link again. Each listing carries its pay link's own half
// of its key (sA, the part after a /p/ link's #) sealed with the shop key and bound to the link's id (`link_ct`): a
// visitor with the shop's whole link opens it and builds the /p/ link; our server, which holds the other half (sB)
// of every pay link, can't put the two together from what it stores.
import { b64uDecode, b64uEncode } from './b64.js';
import { concat, utf8 } from './bytes.js';
import { aesGcmDecrypt, aesGcmEncrypt, hkdf, randomBytes } from './crypto.js';
import { enc, request } from './api.js';
import { parsePayFragment, payFragment } from './pay.js';

const V2 = 'mutis/v2';
const KIND = '6';                       // fragment kind 6: a shop's key (1, 2 links; 3, 4 Tari sends; 5 a pay link)
const KEY_AAD = utf8('mutis-shop-key-v1');
const LISTING_AAD = 'mutis-shop-listing-v1:';
const SHOP_ID = /^[A-Za-z0-9_-]{22}$/;

// ---------- the API (docs/api.md "Shop"); the owner's routes take the drive's session ----------

export const getMyShop = (headers) => request('GET', '/me/shop', { headers });
export const putMyShop = (body, headers) => request('PUT', '/me/shop', { json: body, headers });
export const deleteMyShop = (headers) => request('DELETE', '/me/shop', { headers, expect: 'none' });
export const putListing = (shareId, body, headers) => request('PUT', `/me/shop/listings/${enc(shareId)}`, { json: body, headers });
export const deleteListing = (shareId, headers) => request('DELETE', `/me/shop/listings/${enc(shareId)}`, { headers, expect: 'none' });
// The public page's data: no session, the same for everyone.
export const publicShop = (shopId) => request('GET', `/shop/${enc(shopId)}`);

// ---------- keys ----------

export const newShopKey = () => randomBytes(32);
const wrapKey = (vaultKey) => hkdf(vaultKey, V2, 'shop-key-wrap', 32);
const listingKey = (shopKey) => hkdf(shopKey, V2, 'shop-listing', 32);
const listingAad = (shareId) => utf8(LISTING_AAD + shareId);

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

export function shopUrl(origin, shopId, shopKey) {
  if (!SHOP_ID.test(shopId)) throw new TypeError('bad shop id');
  return `${origin}/shop/${shopId}#${shopFragment(shopKey)}`;
}

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

// GET /me/shop, with the shop's link rebuilt from the wrapped key: {shop, key, url} or null while it's off.
export async function myShop(identity, headers, origin = globalThis.location?.origin) {
  const { shop } = await getMyShop(headers);
  if (!shop) return null;
  const key = await unwrapShopKey(identity.vaultKey, b64uDecode(shop.key_wrap));
  return { shop, key, url: shop.state === 'open' ? shopUrl(origin, shop.shop_id, key) : null };
}

// Turn the shop on: a fresh key, wrapped here; our server picks the id.
export async function openShop(identity, { title, bio }, headers, origin = globalThis.location?.origin) {
  const key = newShopKey();
  const { shop } = await putMyShop({ title, bio, key_wrap: b64uEncode(await wrapShopKey(identity.vaultKey, key)) }, headers);
  return { shop, key, url: shopUrl(origin, shop.shop_id, key) };
}

// List a pay link (or change its words): its sA sealed with the shop key. -> the listing as our server keeps it.
export async function listLink(shopKey, shareId, sA, { title, description }, headers) {
  const linkCt = b64uEncode(await sealListing(shopKey, shareId, sA));
  return (await putListing(shareId, { title, description, link_ct: linkCt }, headers)).listing;
}

// ---------- the visitor ----------

// The public page with each listing's /p/ link, where the shop key opens it; `buy` null for one that doesn't.
export async function openShopPage(shopId, shopKey, origin = globalThis.location?.origin) {
  const page = await publicShop(shopId);
  const items = await Promise.all((page.items ?? []).map(async (it) => {
    let buy = null;
    try {
      buy = buyUrl(origin, it.share_id, await openListing(shopKey, it.share_id, b64uDecode(it.link_ct)));
    } catch {
      buy = null;     // sealed with another key, or not for this link: shown, never offered
    }
    return { ...it, buy };
  }));
  return { ...page, items };
}
