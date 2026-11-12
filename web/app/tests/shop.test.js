// SPDX-License-Identifier: MIT
// lib/shop.js (docs/shop.md): the shop's link carries its key after the # (kind 6); our server keeps it only wrapped
// under the drive's key; each listing's pay-link half (sA) is sealed with it and bound to its link's id; the page a
// visitor sees builds each /p/ link from those, and nothing the client sends holds the shop key or an sA.
import { b64uDecode, b64uEncode } from '../lib/b64.js';
import { IntegrityError, randomBytes } from '../lib/crypto.js';
import { configureApi } from '../lib/api.js';
import { parsePayFragment, payFragment } from '../lib/pay.js';
import * as shop from '../lib/shop.js';
import { bytesEq, eq, ok, rejects } from './harness.js';

export const env = 'any';

const ORIGIN = 'https://shop.mutis.test';
const id22 = () => b64uEncode(randomBytes(16));

// A stand-in for our server's shop routes, over fetch, recording what the client sends.
function fakeShopApi() {
  const realFetch = globalThis.fetch;
  const state = { shop: null, listings: new Map(), sent: [], puts: [], tokenHash: null, publicKey: null };
  globalThis.fetch = async (input, init = {}) => {
    const req = new Request(input, init);
    const url = new URL(req.url);
    const body = req.method === 'GET' || req.method === 'DELETE' ? null : await req.text();
    state.sent.push({ method: req.method, url: req.url, headers: [...req.headers], body });
    const json = (status, obj) => new Response(obj === null ? null : JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const mine = () => state.shop && { ...state.shop, listings: [...state.listings.values()] };
    if (path === '/me/shop' && req.method === 'GET') return json(200, { shop: mine() });
    if (path === '/me/shop' && req.method === 'PUT') {
      const b = JSON.parse(body);
      state.puts.push(b);
      state.shop ??= { shop_id: id22(), state: 'open', key_wrap: b.key_wrap, mode: 'private' };
      if (b.relisted) for (const r of b.relisted) state.listings.get(r.share_id).link_ct = r.link_ct;
      Object.assign(state.shop, { title: b.title, bio: b.bio, username: b.username ?? state.shop.username, key_wrap: b.key_wrap,
        mode: b.mode ?? state.shop.mode, has_token: Boolean(b.token_hash ?? state.shop.has_token) });
      state.shop.path = `/shop/${state.shop.username}`;
      if (b.token_hash) state.tokenHash = b.token_hash;
      state.publicKey = state.shop.mode === 'public' ? b.shop_key ?? state.publicKey : null;
      return json(201, { shop: mine() });
    }
    const listed = /^\/me\/shop\/listings\/([A-Za-z0-9_-]{22})$/.exec(path);
    if (listed && req.method === 'PUT') {
      const b = JSON.parse(body);
      const row = { share_id: listed[1], title: b.title, description: b.description, kind: 'file', size_stored: 4096, price_ut: '250000', link_ct: b.link_ct };
      state.listings.set(listed[1], row);
      return json(201, { listing: { ...row, selling: true, paused: false } });
    }
    const pub = /^\/shop\/([A-Za-z0-9_-]{1,64})$/.exec(path);
    if (pub && req.method === 'GET') {
      const missing = () => json(404, { error: { code: 'not_found', message: 'x' } });
      if (!state.shop || pub[1] !== state.shop.username) return missing();
      const page = { title: state.shop.title, bio: state.shop.bio, mode: state.shop.mode, username: state.shop.username, items: [...state.listings.values()] };
      if (state.shop.mode === 'public') return json(200, { ...page, shop_key: state.publicKey });
      // As our server checks it: SHA-256 of the token the request shows equals the hash the drive registered.
      const token = req.headers.get('X-Mutis-Shop');
      if (!token) return missing();
      const hashed = b64uEncode(new Uint8Array(await crypto.subtle.digest('SHA-256', b64uDecode(token))));
      return hashed === state.tokenHash ? json(200, page) : missing();
    }
    return json(404, { error: { code: 'not_found', message: 'x' } });
  };
  configureApi({ origin: ORIGIN });
  return { state, restore: () => { globalThis.fetch = realFetch; } };
}

export default [
  ['shop fragment: kind 6 and 43 characters; pay links and other kinds are not shop links', () => {
    const key = randomBytes(32);
    const f = shop.shopFragment(key);
    eq(f.length, 44);
    eq(f[0], '6');
    bytesEq(shop.parseShopFragment('#' + f), key);
    bytesEq(shop.parseShopFragment(f), key);
    eq(shop.parseShopFragment('#' + payFragment(key)), null);
    eq(shop.parseShopFragment('#1' + f.slice(1)), null);
    eq(shop.parseShopFragment('#6' + f.slice(2)), null);
    eq(shop.parseShopFragment(''), null);
    eq(shop.parseShopFragment(null), null);
    let threw = false;
    try {
      shop.shopFragment(randomBytes(16));
    } catch (e) {
      threw = e instanceof TypeError;
    }
    ok(threw, 'a 16-byte key is refused');
  }],
  ['shop key: wrapped under the drive key in 60 bytes, opened only by that drive', async () => {
    const vault = randomBytes(32);
    const key = randomBytes(32);
    const wrapped = await shop.wrapShopKey(vault, key);
    eq(wrapped.length, 60);
    bytesEq(await shop.unwrapShopKey(vault, wrapped), key);
    await rejects(() => shop.unwrapShopKey(randomBytes(32), wrapped), IntegrityError, 'another drive');
    wrapped[30] ^= 1;
    await rejects(() => shop.unwrapShopKey(vault, wrapped), IntegrityError, 'a changed byte');
    const again = await shop.wrapShopKey(vault, key);
    ok(b64uEncode(again) !== b64uEncode(await shop.wrapShopKey(vault, key)), 'a fresh iv each time');
  }],
  ['listing: the pay link half sealed with the shop key, bound to its link id', async () => {
    const key = randomBytes(32);
    const sA = randomBytes(32);
    const shareId = id22();
    const sealed = await shop.sealListing(key, shareId, sA);
    eq(sealed.length, 60);
    bytesEq(await shop.openListing(key, shareId, sealed), sA);
    await rejects(() => shop.openListing(key, id22(), sealed), IntegrityError, 'moved to another link');
    await rejects(() => shop.openListing(randomBytes(32), shareId, sealed), IntegrityError, 'another shop key');
  }],
  ['links: the shop link names its id and key; Buy and open is the pay link itself', () => {
    const key = randomBytes(32);
    const sid = id22();
    const url = shop.shopUrl(ORIGIN, sid, key);
    eq(url, `${ORIGIN}/shop/${sid}#6${b64uEncode(key)}`);
    const sA = randomBytes(32);
    const share = id22();
    const buy = shop.buyUrl(ORIGIN, share, sA);
    eq(buy, `${ORIGIN}/p/${share}#5${b64uEncode(sA)}`);
    bytesEq(parsePayFragment(new URL(buy).hash), sA);
    bytesEq(shop.sAOf(buy), sA);
    eq(shop.sAOf(`${ORIGIN}/s/${share}#1${b64uEncode(sA)}`), null);
    eq(shop.sAOf('not a url'), null);
    eq(shop.shopUrl(ORIGIN, 'mila-prints', key), `${ORIGIN}/shop/mila-prints#6${b64uEncode(key)}`);
    eq(shop.shopUrl(ORIGIN, 'mila-prints', null), `${ORIGIN}/shop/mila-prints`, 'a public address has nothing after it');
    for (const bad of ['ab', `${sid}/x`, '', 'Mila', 'mila prints', '-mila', 'mila-', 'a--b', '<script>', '../x', 'm\u0430la', 'x'.repeat(31)]) {
      let threw = false;
      try {
        shop.shopUrl(ORIGIN, bad, key);
      } catch {
        threw = true;
      }
      ok(threw, `shopUrl refuses ${bad}`);
    }
  }],
  ['owner and visitor: the server gets the key wrapped and each sA sealed, never either in the clear; the page builds the /p/ links', async () => {
    const api = fakeShopApi();
    try {
      const identity = { vaultKey: randomBytes(32) };
      const opened = await shop.openShop(identity, { title: 'Prints', bio: 'Zines and prints.', username: 'mila' }, { Authorization: 'Bearer x' }, ORIGIN);
      eq(new URL(opened.url).pathname, '/shop/mila');
      const keyB64 = b64uEncode(opened.key);
      ok(opened.url.endsWith(`#6${keyB64}`), 'the shop link carries its key after the #');
      const sA = randomBytes(32);
      const share = id22();
      const listing = await shop.listLink(opened.key, share, sA, { title: 'Zine 3', description: 'Twelve pages.' }, { Authorization: 'Bearer x' }, opened.shop.key_wrap);
      eq(JSON.parse(api.state.sent.at(-1).body).key_wrap, opened.shop.key_wrap, 'the listing names the key it is sealed with');
      eq(listing.title, 'Zine 3');
      // A second listing sealed with some other key: shown, never offered.
      const stray = id22();
      api.state.listings.set(stray, { share_id: stray, title: 'Odd', description: '', kind: 'file', size_stored: 1, price_ut: '1', link_ct: b64uEncode(await shop.sealListing(randomBytes(32), stray, sA)) });
      const again = await shop.myShop(identity, { Authorization: 'Bearer x' }, ORIGIN);
      eq(again.url, opened.url);
      const sid = opened.shop.username;
      await rejects(() => shop.openShopPage(sid, null, ORIGIN), 'not_found', 'a private shop shows nothing without its key');
      const page = await shop.openShopPage(sid, shop.parseShopFragment(new URL(opened.url).hash), ORIGIN);
      eq(page.title, 'Prints');
      const good = page.items.find((x) => x.share_id === share);
      eq(good.buy, `${ORIGIN}/p/${share}#5${b64uEncode(sA)}`);
      eq(page.items.find((x) => x.share_id === stray).buy, null);
      await rejects(() => shop.openShopPage(sid, randomBytes(32), ORIGIN), 'not_found', 'another key shows nothing either');
      const sent = JSON.stringify(api.state.sent);
      for (const secret of [keyB64, b64uEncode(sA), b64uEncode(identity.vaultKey)]) ok(!sent.includes(secret), 'no secret left the client');
      ok(!sent.includes('#6') && !sent.includes('#5'), 'no fragment in any request');
      const put = JSON.parse(api.state.sent.find((r) => r.method === 'PUT' && r.url.endsWith('/me/shop')).body);
      eq(b64uDecode(put.key_wrap).length, 60);
      eq(put.token_hash, b64uEncode(await shop.tokenHash(opened.key)));
      eq(put.shop_key, undefined, 'a private shop\'s key stays here');
      bytesEq(await shop.unwrapShopKey(identity.vaultKey, b64uDecode(put.key_wrap)), opened.key);
      const visitor = api.state.sent.filter((r) => r.url.includes('/api/v1/shop/'));
      ok(visitor.length >= 2 && visitor.every((r) => !r.headers.some(([k]) => k.toLowerCase() === 'authorization')), 'the visitor sends no session');
    } finally {
      api.restore();
    }
  }],
  ['the read token: HKDF(shop key, "mutis/v2", "shop-read"), the same bytes our server derives', async () => {
    const key = Uint8Array.from({ length: 32 }, (_, i) => i);
    // server: shop.read_token(bytes(range(32))) and its SHA-256 (server/tests/test_shop_names.py makes the same)
    eq(b64uEncode(await shop.readToken(key)), b64uEncode(Uint8Array.from('0339c9a2a29560feb735e8ecfeb7dc137e09b8e7777c4c6340876195af416fba'.match(/../g), (x) => parseInt(x, 16))));
    eq(b64uEncode(await shop.tokenHash(key)), b64uEncode(Uint8Array.from('dff1b3b1d63b66fbb7a5e547470a500d1a1191a864318dd1a0265e9b2da6ce5d'.match(/../g), (x) => parseInt(x, 16))));
  }],
  ['the address: what a name may be, said early, as our server will', () => {
    for (const good of ['mila', 'mila-prints', 'Mila-Prints', 'a1b2', 'x'.repeat(30)]) eq(shop.nameProblem(good), null, good);
    const cases = [['ab', 'short'], ['', 'short'], ['x'.repeat(31), 'long'], ['mila prints', 'chars'], ['m\u0430la', 'chars'], ['caf\u00e9', 'chars'],
      ['<script>', 'chars'], ['../x', 'chars'], ['a_b', 'chars'], ['\u202emila', 'chars'], ['mi\u200bla', 'chars'], ['-mila', 'hyphens'], ['mila-', 'hyphens'], ['a--b', 'hyphens']];
    for (const [bad, why] of cases) eq(shop.nameProblem(bad), why, bad);
  }],
  ['public, then private again: the key never leaves this browser; without it a public page offers no Buy, only asks', async () => {
    const api = fakeShopApi();
    try {
      const identity = { vaultKey: randomBytes(32) };
      const hdr = { Authorization: 'Bearer x' };
      const opened = await shop.openShop(identity, { title: 'Prints', bio: '', username: 'mila' }, hdr, ORIGIN);
      const sA = randomBytes(32);
      const share = id22();
      await shop.listLink(opened.key, share, sA, { title: 'Zine', description: '' }, hdr, opened.shop.key_wrap);
      let state = await shop.myShop(identity, hdr, ORIGIN);
      await shop.setMode(identity, state, 'public', hdr);
      const pub = api.state.puts.at(-1);
      eq(pub.mode, 'public');
      eq(pub.shop_key, undefined, 'public: the shop key stays here');
      eq(pub.key_wrap, opened.shop.key_wrap, 'the same key');
      state = await shop.myShop(identity, hdr, ORIGIN);
      eq(state.url, opened.url, 'the whole link still buys at once');
      eq(state.address, `${ORIGIN}/shop/mila`, 'the address is where the market finds it');
      const seen = await shop.openShopPage('mila', null, ORIGIN);
      ok(seen.keyless, 'without the key, the page says so');
      eq(seen.items[0].buy, null, 'and offers no pay link');
      const withKey = await shop.openShopPage('mila', opened.key, ORIGIN);
      eq(withKey.items[0].buy, `${ORIGIN}/p/${share}#5${b64uEncode(sA)}`, 'with it, Buy and open');
      await shop.setMode(identity, state, 'private', hdr);
      const back = api.state.puts.at(-1);
      eq((back.mode + (back.relisted ? 'relisted' : '')), 'private', 'private again keeps the key: nothing to seal again');
      eq(back.key_wrap, opened.shop.key_wrap);
      await rejects(() => shop.openShopPage('mila', null, ORIGIN), 'not_found', 'private: nothing without the key');
      const fresh = await shop.newKey(identity, await shop.myShop(identity, hdr, ORIGIN), hdr);
      const turned = api.state.puts.at(-1);
      const key2 = await shop.unwrapShopKey(identity.vaultKey, b64uDecode(turned.key_wrap));
      ok(b64uEncode(key2) !== b64uEncode(opened.key), 'a new key, when asked for');
      bytesEq(await shop.openListing(key2, share, b64uDecode(turned.relisted[0].link_ct)), sA);
      eq(fresh.key_wrap, turned.key_wrap);
      const sent = JSON.stringify(api.state.sent);
      for (const secret of [b64uEncode(opened.key), b64uEncode(key2), b64uEncode(sA)]) ok(!sent.includes(secret), 'no key or sA left the browser');
    } finally {
      api.restore();
    }
  }],
];
