// SPDX-License-Identifier: MIT
// lib/market.js (docs/market.md): an ask's id, token and key pair all come from a secret this browser keeps; the seller's
// drive seals a listing's sA to that pair, bound to the ask and the listing, and only that pair opens it; a refusal for
// keys that aren't points; and nothing the client sends holds an sA, a shop key or an ask's secret.
import { b64uDecode, b64uEncode } from '../lib/b64.js';
import { IntegrityError, randomBytes, sha256 } from '../lib/crypto.js';
import { configureApi } from '../lib/api.js';
import * as market from '../lib/market.js';
import { ready, sealToKeys } from '../lib/ootle.js';
import * as shop from '../lib/shop.js';
import { bytesEq, eq, ok, rejects } from './harness.js';

export const env = 'any';

const ORIGIN = 'https://market.mutis.test';
const id22 = () => b64uEncode(randomBytes(16));

// A stand-in for our server's market routes over fetch, recording what the client sends.
function fakeMarketApi(state) {
  const realFetch = globalThis.fetch;
  state.sent = [];
  globalThis.fetch = async (input, init = {}) => {
    const req = new Request(input, init);
    const url = new URL(req.url);
    const body = req.method === 'GET' ? null : await req.text();
    state.sent.push({ method: req.method, url: req.url, headers: [...req.headers], body });
    const json = (status, obj) => new Response(obj === null ? null : JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });
    const path = url.pathname.replace(/^\/api\/v1/, '');
    if (path === '/me/market/asks' && req.method === 'GET') return json(200, { asks: state.waiting });
    const put = /^\/me\/market\/asks\/([A-Za-z0-9_-]{22})$/.exec(path);
    if (put && req.method === 'PUT') {
      state.answers[put[1]] = JSON.parse(body);
      return new Response(null, { status: 204 });
    }
    const get = /^\/market\/asks\/([A-Za-z0-9_-]{22})$/.exec(path);
    if (get && req.method === 'GET') {
      const a = state.asks[get[1]];
      const token = req.headers.get('X-Mutis-Ask');
      const hashed = token ? b64uEncode(await sha256(b64uDecode(token))) : null;
      if (!a || hashed !== a.token_hash) return json(404, { error: { code: 'not_found', message: 'x' } });
      return json(200, { ask_id: get[1], share_id: a.share_id, state: a.answer ? 'answered' : 'waiting', expires_at: 1, ...(a.answer ? { answer: a.answer } : {}) });
    }
    if (path === '/pow' && req.method === 'POST') {
      const challenge = new Uint8Array(36);
      challenge[0] = 1;
      challenge[2] = 1;                        // one bit: solved at once
      return json(200, { challenge: b64uEncode(challenge), difficulty: 1, expires_at: Math.floor(Date.now() / 1000) + 300 });
    }
    if (path === '/market/asks' && req.method === 'POST') {
      const b = JSON.parse(body);
      state.asks[b.ask_id] = b;
      return json(201, { ask_id: b.ask_id, expires_at: 1 });
    }
    return json(404, { error: { code: 'not_found', message: 'x' } });
  };
  configureApi({ origin: ORIGIN });
  return () => { globalThis.fetch = realFetch; };
}

export default [
  ['ask parts: id, token and key pair from the secret, the same id and token our server derives', async () => {
    await ready();
    const secret = Uint8Array.from({ length: 32 }, (_, i) => i);
    const parts = await market.askParts(secret);
    // server: codec.hkdf(bytes(range(32)), b"mutis/v2", b"market-ask-id", 16) and b"market-ask", 32
    eq(parts.askId, 'EGMlANxGYEHDay5e6TL60g');
    eq(Array.from(parts.token, (b) => b.toString(16).padStart(2, '0')).join(''), '3970f4a3cb452ef0f8c09f07234b54cb6ab78d2449e71b978fb0c86591554792');
    eq(parts.keys.ownerPk.length, 32);
    eq(parts.keys.viewPk.length, 32);
    ok(b64uEncode(parts.keys.ownerPk) !== b64uEncode(parts.keys.viewPk), 'two keys');
    const again = await market.askParts(secret);
    bytesEq(again.keys.ownerPk, parts.keys.ownerPk);
    const other = await market.askParts(randomBytes(32));
    ok(other.askId !== parts.askId, 'another secret, another ask');
    await rejects(() => market.askParts(randomBytes(16)), TypeError, 'a 16-byte secret');
  }],
  ['an answer opens only with its ask\'s keys, for its ask and its listing', async () => {
    const parts = await market.askParts(randomBytes(32));
    const shareId = id22();
    const sA = randomBytes(32);
    const sealed = await sealToKeys({ ownerPk: parts.keys.ownerPk, viewPk: parts.keys.viewPk }, await market.answerInner(parts.askId, shareId, sA), 3);
    eq(sealed.length, 125);
    bytesEq(await market.openAnswer(parts, shareId, sealed), sA);
    await rejects(() => market.openAnswer(parts, id22(), sealed), TypeError, 'for another listing');
    const other = await market.askParts(randomBytes(32));
    await rejects(() => market.openAnswer(other, shareId, sealed), IntegrityError, 'another ask\'s keys');
    const moved = { ...other, keys: parts.keys };                          // the right keys, another ask's id
    await rejects(() => market.openAnswer(moved, shareId, sealed), TypeError, 'bound to its ask');
    const changed = sealed.slice();
    changed[90] ^= 1;
    await rejects(() => market.openAnswer(parts, shareId, changed), IntegrityError, 'a changed byte');
  }],
  ['fragment kind 8: the ask\'s secret, 43 characters', () => {
    const s = randomBytes(32);
    const f = market.askFragment(s);
    eq((f[0] + f.length), '844');
    bytesEq(market.parseAskFragment('#' + f), s);
    eq(market.parseAskFragment('#6' + f.slice(1)), null);
    eq(market.parseAskFragment('#8' + f.slice(2)), null);
    eq(market.parseAskFragment(''), null);
  }],
  ['the seller\'s drive answers, refuses keys that aren\'t points, skips what it can\'t open; the shopper opens and buys', async () => {
    const shopKey = randomBytes(32);
    const sA = randomBytes(32);
    const shareId = id22();
    const state = { waiting: [], answers: {}, asks: {} };
    const restore = fakeMarketApi(state);
    try {
      globalThis.localStorage?.clear?.();
      const entry = await market.ask({ share_id: shareId, title: 'Zine', price_ut: '250000000', shop: { path: '/shop/mila' } });
      eq(entry.shareId, shareId);
      eq(market.savedAskFor(shareId)?.askId ?? entry.askId, entry.askId);
      eq((await market.askState(entry, ORIGIN)).state, 'waiting');
      const asked = state.asks[entry.askId];
      const stray = id22();
      state.waiting = [
        { ask_id: entry.askId, share_id: shareId, owner_pk: asked.owner_pk, view_pk: asked.view_pk },
        { ask_id: id22(), share_id: shareId, owner_pk: b64uEncode(randomBytes(32)), view_pk: b64uEncode(randomBytes(32)) },
        { ask_id: id22(), share_id: stray, owner_pk: asked.owner_pk, view_pk: asked.view_pk },
      ];
      const mine = {
        key: shopKey,
        shop: { mode: 'public', state: 'open', listings: [{ share_id: shareId, link_ct: b64uEncode(await shop.sealListing(shopKey, shareId, sA)) },
          { share_id: stray, link_ct: b64uEncode(await shop.sealListing(randomBytes(32), stray, sA)) }] },
      };
      eq(await market.answerAsks(mine, { Authorization: 'Bearer x' }), 1);
      eq(b64uDecode(state.answers[entry.askId].answer).length, 125);
      eq(state.answers[state.waiting[1].ask_id].refused, true, 'random bytes are no key pair');
      eq(state.answers[state.waiting[2].ask_id], undefined, 'a listing this page can\'t open waits');
      state.asks[entry.askId].answer = state.answers[entry.askId].answer;
      const got = await market.askState(entry, ORIGIN);
      eq(got.state, 'answered');
      eq(got.buy, `${ORIGIN}/p/${shareId}#5${b64uEncode(sA)}`);
      state.asks[entry.askId].answer = b64uEncode(randomBytes(125));
      eq((await market.askState(entry, ORIGIN)).state, 'bad', 'an answer that doesn\'t open is never followed');
      delete state.asks[entry.askId];
      eq((await market.askState(entry, ORIGIN)).state, 'ended');
      eq(await market.answerAsks({ ...mine, shop: { ...mine.shop, mode: 'private' } }, {}), 0, 'a private shop answers nothing');
      const sent = JSON.stringify(state.sent);
      for (const secret of [b64uEncode(sA), b64uEncode(shopKey), entry.s]) ok(!sent.includes(secret), 'no secret left the client');
      ok(!sent.includes('#8') && !sent.includes('#5'), 'no fragment in any request');
    } finally {
      restore();
    }
  }],
];
