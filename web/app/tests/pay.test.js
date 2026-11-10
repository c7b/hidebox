// SPDX-License-Identifier: MIT
// Pay to open's client library (lib/pay.js; 16-drive-architecture §1.3, §1.9).
import { b64uDecode, b64uEncode, hex, unhex } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { shareKeys } from '../lib/share.js';
import { auditOutput, checkSales, claimRef, keepClaim, openTeaser, parsePayFragment, payFragment, payFromDrive, paySecret, savedClaim, salesState, sealTeaser, sizeBucket } from '../lib/pay.js';
import { configureApi } from '../lib/api.js';
import { idbPut } from '../lib/idb.js';
import { oneTimeKey, ready, tryDecryptUtxo } from '../lib/ootle.js';
import { eq, loadJson, ok, rejects } from './harness.js';

export const env = 'any';

// A stand-in for our API: `routes` maps "METHOD /path" (without /api/v1) to (body) => [status, json]. Every
// request is kept, so a test can say what was never sent.
const STUB = 'https://pay-stub.mutis.test';
function stubApi(routes) {
  const realFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    if (url.origin !== STUB) return realFetch(input, init);
    const key = `${init.method ?? 'GET'} ${url.pathname.replace(/^\/api\/v1/, '')}`;
    const body = init.body ? JSON.parse(init.body) : null;
    requests.push({ key, body });
    const [status, answer] = (routes[key] ?? (() => [404, { error: { code: 'not_found' } }]))(body);
    return new Response(JSON.stringify(answer), { status, headers: { 'Content-Type': 'application/json' } });
  };
  configureApi({ origin: STUB });
  return { requests, restore: () => { globalThis.fetch = realFetch; } };
}

// A localStorage where the runtime has none (Node), for what a claim keeps in this browser.
function claimStorage() {
  const own = globalThis.localStorage;
  if (!own) {
    const m = new Map();
    globalThis.localStorage = { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
  }
  return () => { if (!own) delete globalThis.localStorage; };
}

// The answers an indexer gives for one output (through our proxy): there with its key, proven spent, or unknown.
const there = (row, key) => [200, { version: 0, state: { up: { substate: { Utxo: { output: { auth: { Key: key }, output: { public_nonce: row.nonce, encrypted_data: row.enc } }, is_frozen: false } } } }, verified: true }];
const DOWN = [200, { version: 0, state: { down: {} }, verified: true, proof: { down_proof: '' } }];
const UNKNOWN = [404, { error: { code: 'not_found', message: 'Substate not found' } }];

export default [
  ['split key: s = HKDF(sA ‖ sB), then the link keys, match pay-v1.json', async () => {
    const v = await loadJson('vectors/pay-v1.json');
    const s = await paySecret(unhex(v.sA), unhex(v.sB));
    eq(hex(s), v.s);
    const k = await shareKeys(s);
    eq(hex(k.accessToken), v.access_token);
    eq(hex(k.accessVerifier), v.access_verifier);
    eq(hex(k.wrapKey), v.wrap_key);
  }],
  ['fragment kind 5 carries sA alone (44 characters) and nothing else parses', () => {
    const sA = randomBytes(32);
    const f = payFragment(sA);
    eq(f.length, 44);
    eq(f[0], '5');
    eq(hex(parsePayFragment('#' + f)), hex(sA));
    for (const bad of ['', '#1' + f.slice(1), '#5' + f.slice(2), '#5' + f.slice(1) + 'A', '#5!' + f.slice(2)]) eq(parsePayFragment(bad), null, bad);
  }],
  ['teaser: sealed, padded to 256-byte steps, opens only with its sA', async () => {
    const sA = randomBytes(32);
    const sealed = await sealTeaser(sA, { kind: 'folder', name: 'Trip photos', count: 8, size_bucket: 5e7 });
    eq(sealed.length, 12 + 256 + 16);
    const t = await openTeaser(sA, sealed);
    eq(t.v, 1);
    eq(t.name, 'Trip photos');
    eq(t.count, 8);
    const long = await sealTeaser(sA, { kind: 'file', name: 'x'.repeat(300), count: 1, size_bucket: 1e6 });
    eq(long.length, 12 + 512 + 16);
    await rejects(() => openTeaser(randomBytes(32), sealed));
  }],
  ['size bucket: never the size, the smallest bucket at or above it', () => {
    const MIB = 1048576;
    eq(sizeBucket(1), MIB);
    eq(sizeBucket(MIB), MIB);
    eq(sizeBucket(MIB + 1), 5 * MIB);
    eq(sizeBucket(47.7e6), 50 * MIB);
    eq(sizeBucket(1e12), 10240 * MIB);
  }],
  ['claim reference: a Message that is a claim id, or a PayRefAndBytes pay-ref; nothing else', () => {
    const id = 'clm_' + 'abcdefghijklmnopqrst';
    eq(claimRef({ Message: id }), id);
    const ref = Array.from(new TextEncoder().encode(id));
    eq(claimRef({ PayRefAndBytes: hex(Uint8Array.from([ref.length, ...ref, 1, 2])) }), id);
    eq(claimRef({ DestinationTagAndBytes: hex(Uint8Array.from([ref.length, ...ref])) }), id, 'the Ootle 0.48+ name');
    for (const bad of [null, {}, { Message: id + ' ' }, { Message: 'inv_abcdefghijklmnopqrst' }, { PayRefAndBytes: 'zz' }, { PayRefAndBytes: '40' + hex(Uint8Array.from(ref)) }]) {
      eq(claimRef(bad), null, JSON.stringify(bad));
    }
  }],
  ['claims kept in this browser: saved, merged, forgotten', () => {
    const sid = b64uEncode(randomBytes(16));
    keepClaim(sid, { claimId: 'clm_x', t: 'T' });
    keepClaim(sid, { how: 'test' });
    const c = savedClaim(sid);
    ok(c === null || (c.claimId === 'clm_x' && c.how === 'test'), 'merged (or no storage here)');
    keepClaim(sid, null);
    eq(savedClaim(sid), null);
  }],
  ['R1 owner check: the one-time key our owner key derives matches only the output that is ours', async () => {
    const v = await loadJson('vectors/pay-v1.json');
    await ready();
    const own = v.ownership;
    for (const [row, ours] of [[own.genuine, true], [own.not_ours, false]]) {
      ok(await tryDecryptUtxo(unhex(own.view_sk), row), 'the view key opens both (amount and memo)');
      eq((await oneTimeKey(unhex(own.owner_sk), unhex(own.view_sk), row.nonce)) === row.auth_key, ours);
    }
    eq(await oneTimeKey(unhex(own.owner_sk), unhex(own.view_sk), 'ff'.repeat(32)), null);
    ok(b64uDecode(b64uEncode(unhex(own.owner_sk))).length === 32);
  }],
  ['a 404 is no verdict: auditOutput answers null and no confirm is sent', async () => {
    const v = await loadJson('vectors/pay-v1.json');
    await ready();
    const own = v.ownership;
    const keys = { ownerSk: unhex(own.owner_sk), viewSk: unhex(own.view_sk) };
    const row = own.genuine;
    const output = { utxoId: row.id, nonce: row.nonce };
    const sub = `GET /chain/ix/substates/${row.id}`;
    // the verdict, answer by answer: only evidence makes a 'bad'
    for (const [answer, verdict, why] of [
      [UNKNOWN, null, 'an indexer that doesn\'t know the output yet'],
      [[503, { error: { code: 'chain_unavailable' } }], null, 'no indexer answering'],
      [[200, { version: 0, state: { up: { substate: 'not-cbor' } } }], null, 'a value nothing can read'],
      [there(row, row.auth_key), 'ok', 'there, with the key our owner key derives'],
      [there(row, own.not_ours.auth_key), 'bad', 'there, with another key'],
      [DOWN, 'bad', 'proven spent before this drive confirmed it'],
    ]) {
      const api = stubApi({ [sub]: () => answer });
      try {
        eq(await auditOutput(keys, output), verdict, why);
      } finally {
        api.restore();
      }
    }
    // the whole pass: our server waits on this output; while the indexer answers 404 nothing is confirmed or voided
    const identity = { id: b64uEncode(randomBytes(16)), createdSeq: 0, sales: { ...keys, address: 'otl_esm_1seller' } };
    const claim = 'clm_' + 'abcdefghijklmnopqrst';
    let answer = UNKNOWN;
    const api = stubApi({
      'GET /chain/utxos': () => [200, { items: [], head: 0 }],
      'GET /me/sales': () => [200, { seller: { address: identity.sales.address, state: 'ok' }, to_check: [{ claim_id: claim, utxo_ids: [row.id] }], paid: [] }],
      [sub]: () => answer,
      [`POST /me/sales/claims/${claim}/confirm`]: () => [200, { claim_id: claim, status: 'paid', owner_check: 'ok' }],
    });
    try {
      const confirms = () => api.requests.filter((r) => r.key.endsWith('/confirm'));
      let state = await checkSales(identity, {}, {});
      eq(state.outputs.find((o) => o.utxoId === row.id).check, null, 'no verdict kept');
      eq(confirms().length, 0, 'nothing confirmed, nothing voided');
      answer = there(row, row.auth_key);   // the indexer caught up
      state = await checkSales(identity, {}, {});
      eq(state.outputs.find((o) => o.utxoId === row.id).check, 'ok');
      eq(JSON.stringify(confirms().map((r) => r.body)), JSON.stringify([{ utxo_id: row.id, spendable: true }]), 'confirmed once it is seen');
    } finally {
      api.restore();
    }
  }],
  ['a "payer kept control" kept from before the evidence rule is asked about again; one made under it stands', async () => {
    const v = await loadJson('vectors/pay-v1.json');
    await ready();
    const own = v.ownership;
    const row = own.genuine;
    const identity = { id: b64uEncode(randomBytes(16)), createdSeq: 0, sales: { ownerSk: unhex(own.owner_sk), viewSk: unhex(own.view_sk), address: 'otl_esm_1seller' } };
    const kept = (extra) => ({ registered: identity.sales.address, cursor: 0, outputs: [{ utxoId: row.id, seq: 1, epoch: 1, nonce: row.nonce, value: '1000', claimId: null, check: 'bad', confirmed: 'sent', at: 1, ...extra }] });
    const api = stubApi({
      'GET /chain/utxos': () => [200, { items: [], head: 0 }],
      'GET /me/sales': () => [200, { seller: { address: identity.sales.address, state: 'ok' }, to_check: [], paid: [] }],
      [`GET /chain/ix/substates/${row.id}`]: () => there(row, row.auth_key),
    });
    try {
      await idbPut('inbox', `sales:${identity.id}`, kept({}));
      eq((await checkSales(identity, {}, {})).outputs[0].check, 'ok', 'an old verdict (it may have been a 404) is checked again');
      eq((await salesState(identity)).outputs[0].check, 'ok', 'and kept');
      await idbPut('inbox', `sales:${identity.id}`, kept({ v: 2 }));
      eq((await checkSales(identity, {}, {})).outputs[0].check, 'bad', 'a verdict made on evidence isn\'t asked about again');
      eq(api.requests.filter((r) => r.key.endsWith('/confirm')).length, 0, 'our server waits on neither: nothing is sent');
    } finally {
      api.restore();
    }
  }],
  ['Pay from my drive signs the price the page shows or nothing: a claim that asks more, a negative count or a changed price is refused', async () => {
    const shareId = b64uEncode(randomBytes(16));
    const claimId = 'clm_' + 'abcdefghijklmnopqrst';
    const made = (amountUt) => ({ t: 'T', claimId, address: 'otl_esm_1whoever', amountUt });
    const run = async ({ price = '1000000', amount = '1000000', received = '0', state = 'selling', shown = '1000000' }) => {
      const api = stubApi({
        [`GET /p/${shareId}`]: () => [200, { state, price_ut: price }],
        [`GET /p/${shareId}/claims/${claimId}`]: () => [200, { status: 'pending', amount_ut: amount, received_ut: received }],
      });
      try {
        const res = await payFromDrive({ id: 'x' }, shareId, made(amount), { priceUt: shown });
        return { res, api };
      } catch (e) {
        return { code: e?.code, api };
      } finally {
        api.restore();
      }
    };
    const none = (r) => !r.api.requests.some((x) => x.key.startsWith('POST'));
    for (const [what, opts] of [
      ['a claim for 250 times the price', { amount: '250000000' }],
      ['a claim for less than the price', { amount: '999999' }],
      ['a negative amount already counted (it would add to what is sent)', { received: '-5000000' }],
      ['a price that changed since the page showed it', { price: '2000000', amount: '2000000' }],
      ['an amount that isn\'t a number', { amount: '1e9' }],
      ['a price of nothing', { price: '0', amount: '0', shown: '0' }],
    ]) {
      const r = await run(opts);
      eq(r.code, 'conflict', what);
      ok(none(r), `${what}: nothing was sent`);
    }
    eq((await run({ state: 'paused' })).code, 'not_for_sale');
    const paid = await run({ received: '1000000' });
    eq(paid.res, null, 'already paid in full: nothing more is owed');
    ok(none(paid));
  }],
  ['Pay from my drive after a submit whose answer was lost: the claim remembers, and isn\'t paid again while the first may land', async () => {
    await ready();
    const restore = claimStorage();
    const shareId = b64uEncode(randomBytes(16));
    const claimId = 'clm_' + 'abcdefghijklmnopqrst';
    const claim = { t: 'T', claimId, address: 'otl_esm_1whoever', amountUt: '1000000' };
    const api = stubApi({
      [`GET /p/${shareId}`]: () => [200, { state: 'selling', price_ut: '1000000' }],
      [`GET /p/${shareId}/claims/${claimId}`]: () => [200, { status: 'pending', amount_ut: '1000000', received_ut: '0' }],
    });
    try {
      keepClaim(shareId, { ...claim, unsure: Date.now() - 1000 });
      const e = await rejects(() => payFromDrive({ id: 'x' }, shareId, claim, { priceUt: '1000000' }), 'maybe_sent');
      eq(e.name, 'WalletError');
      ok(!api.requests.some((x) => x.key.startsWith('POST')), 'no second payment');
      eq(savedClaim(shareId).how ?? null, null, 'and the claim isn\'t marked as paying');
    } finally {
      keepClaim(shareId, null);
      api.restore();
      restore();
    }
  }],
];
