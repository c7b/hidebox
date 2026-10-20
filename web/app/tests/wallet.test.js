// SPDX-License-Identifier: MIT
import { randomBytes } from '../lib/crypto.js';
import { identityFromSeed } from '../lib/identity.js';
import { newRandomKeys, ready } from '../lib/ootle.js';
import { idbPut } from '../lib/idb.js';
import { localGet, localSet, set } from '../lib/store.js';
import { inboxState } from '../lib/scan.js';
import { FEE_UT, WalletError, balance, deliver, ensureGrant, send } from '../lib/wallet.js';
import { setJudgePass } from '../lib/pow.js';
import { ApiError } from '../lib/api.js';
import { substateValue } from '../lib/substate.js';
import { installFakeApi } from './fake-api.js';
import { outputTo } from './outputs.js';
import { eq, loadJson, ok, rejects } from './harness.js';

export const env = 'any';

// A locker whose browser wallet holds one output of `value` µT, in this browser's inbox state, with
// a session (the submit proxy wants one).
async function funded(value) {
  await ready();
  set('session', { token: 'wallet-test' });
  const me = await identityFromSeed(randomBytes(32), { createdSeq: 0 });
  const funding = outputTo(me.wallet, value);
  await idbPut('inbox', 'current', { identityId: me.id, cursor: 0, deliveries: [], receipts: [], wallet: [{ utxoId: funding.id, value: String(value), spent: false, pending: null }] });
  return { me, funding };
}

const DIRECT = { send_mode: 'direct', features: { relay_send: true, direct_send: true } };
const SPONSORED = { send_mode: 'direct', features: { relay_send: true, direct_send: true, sponsor: true }, courier: { amount_ut: '1000' } };
const PASS = 'judge-7kq2x9mdh4ab7kq2x9mdh4ab';

// A localStorage for the grant tests where the runtime has none (Node); either way the grant's key
// starts and ends empty.
function grantStorage() {
  const own = globalThis.localStorage;
  if (!own) {
    const m = new Map();
    globalThis.localStorage = { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
  }
  localSet('mutis.grant', null);
  return () => {
    localSet('mutis.grant', null);
    if (!own) delete globalThis.localStorage;
  };
}

// Offline regression test of the direct-mode transaction; the live run on Esmeralda is gate G1.
export default [
  ['direct send: builds a valid stealth transfer from the wallet output, submits one envelope with the locker session, spends the input', async () => {
    await ready();
    set('session', { token: 'wallet-test' });
    const me = await identityFromSeed(randomBytes(32), { createdSeq: 0 });
    const funding = outputTo(me.wallet, 2000000);
    await idbPut('inbox', 'current', { identityId: me.id, cursor: 0, deliveries: [], receipts: [], wallet: [{ utxoId: funding.id, value: '2000000', spent: false }] });
    eq(await balance(me), 2000000n);
    const api = installFakeApi({ substates: new Map([[funding.id, funding]]) });
    try {
      const to = await newRandomKeys();
      const res = await send(me, { to: to.address, amountUt: 1000, memo: { Message: 'hello' } });
      ok(/^[0-9a-f]{64}$/.test(res.tx_id));
      eq(res.fee_ut, FEE_UT.toString());
      eq(api.state.submitted.length, 1);
      ok(/^[A-Za-z0-9+/=]+$/.test(api.state.submitted[0]), 'BOR envelope, base64');
      eq(await balance(me), 0n, 'input marked spent; the change arrives with the next scan');
      const paths = api.state.requests.map((r) => `${r.method} ${new URL(r.url).pathname.replace(/[0-9a-f]{64}/g, '{hex}')}`);
      eq([...new Set(paths)].sort().join(' | '),
        'GET /api/v1/chain/ix/epoch-manager/stats | GET /api/v1/chain/ix/substates/utxo_{hex}_{hex} | GET /api/v1/chain/ix/transactions/{hex}/result | POST /api/v1/chain/ix/transactions');
      ok(!api.state.requests.some((r) => r.url.includes(to.address)), 'the recipient address never reaches our server');
    } finally {
      api.restore();
    }
  }],
  ['indexer answers: the value at state.up.substate (0.47.0, recorded) or substate (earlier); none for a proven down', async () => {
    const v = await loadJson('vectors/indexer-substates-0.47.0.json');
    const live = v.live_utxo.body;
    const utxo = live.state.up.substate.Utxo;
    eq(substateValue(live).Utxo, utxo);
    eq(substateValue({ verified: true, substate: { Utxo: utxo } }).Utxo, utxo, 'the earlier shape');
    eq(substateValue(live).Utxo.output.auth.Key, '6892417fe10f69cc21abd98b963160d872e03fe9a8882d9f531e7bb3efde7a06');
    for (const name of ['live_utxo_without_proof', 'live_utxo_at_version']) ok(substateValue(v[name].body)?.Utxo, name);
    ok('down_proof' in v.spent_utxo_at_version.body.proof);
    for (const [name, body] of [['a proven down', v.spent_utxo_at_version.body], ['the 404 for a spent output', v.spent_utxo.body],
      ['up and down at once', { state: { up: live.state.up, down: {} } }], ['a state beside a substate', { state: { down: {} }, substate: { Utxo: utxo } }],
      ['a state that is not an object', { state: 'up', substate: { Utxo: utxo } }], ['an empty state', { state: {} }],
      ['null', null], ['an array', [live]], ['a substate that is not an object', { state: { up: { substate: [utxo] } } }]]) {
      eq(substateValue(body), null, name);
    }
    ok(substateValue(v.seallog_component.body).Component, 'the SealLog component');
  }],
  ['direct send reads its input in either indexer shape; a proven down or a frozen output is gone', async () => {
    const to = (await newRandomKeys()).address;
    for (const indexer of ['older', 'down', 'frozen']) {
      const { me, funding } = await funded(2000000);
      const api = installFakeApi({ substates: new Map([[funding.id, { ...funding, indexer, frozen: indexer === 'frozen' }]]) });
      try {
        if (indexer === 'older') {
          await send(me, { to, amountUt: 1000 });
          eq(api.state.submitted.length, 1, indexer);
        } else {
          await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof WalletError && e.code === 'insufficient', indexer);
          eq(api.state.submitted.length, 0, indexer);
          ok((await inboxState(me)).wallet[0].spent, `${indexer}: marked spent`);
        }
      } finally {
        api.restore();
      }
    }
  }],
  ['direct send: refuses when the wallet can\'t cover amount + fee', async () => {
    await ready();
    const me = await identityFromSeed(randomBytes(32), { createdSeq: 0 });
    const funding = outputTo(me.wallet, 20000);
    await idbPut('inbox', 'current', { identityId: me.id, cursor: 0, deliveries: [], receipts: [], wallet: [{ utxoId: funding.id, value: '20000', spent: false }] });
    const api = installFakeApi({ substates: new Map([[funding.id, funding]]) });
    try {
      const to = (await newRandomKeys()).address;
      await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof WalletError && e.code === 'insufficient');
      eq(api.state.submitted.length, 0);
    } finally {
      api.restore();
    }
  }],
  ['direct send: a network failure spends nothing; only a 404 from the indexer means "already spent"', async () => {
    await ready();
    const me = await identityFromSeed(randomBytes(32), { createdSeq: 0 });
    const funding = outputTo(me.wallet, 2000000);
    await idbPut('inbox', 'current', { identityId: me.id, cursor: 0, deliveries: [], receipts: [], wallet: [{ utxoId: funding.id, value: '2000000', spent: false }] });
    const api = installFakeApi({ substates: new Map() });
    const fakeFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      if (String(input).includes('/chain/ix/substates/')) throw new TypeError('offline');
      return fakeFetch(input, init);
    };
    try {
      const to = (await newRandomKeys()).address;
      await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof ApiError && e.code === 'network');
      eq(await balance(me), 2000000n, 'still spendable');
      globalThis.fetch = fakeFetch;
      await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof WalletError && e.code === 'insufficient');
      eq(await balance(me), 0n, 'the indexer says it is gone (404), so it is marked spent');
    } finally {
      globalThis.fetch = fakeFetch;
      api.restore();
    }
  }],
  ['direct send rejected by the network: nothing was spent, the next send can use the same output', async () => {
    const { me, funding } = await funded(2000000);
    const api = installFakeApi({ substates: new Map([[funding.id, funding]]), txDecision: { Reject: { InvalidTransaction: 'epoch' } } });
    try {
      const to = (await newRandomKeys()).address;
      await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof WalletError && e.code === 'rejected');
      eq(await balance(me), 2000000n, 'still spendable');
      eq((await inboxState(me)).wallet[0].pending, null);
    } finally {
      api.restore();
    }
    const again = installFakeApi({ substates: new Map([[funding.id, funding]]) });
    try {
      await send(me, { to: (await newRandomKeys()).address, amountUt: 1000 });
      eq(again.state.submitted.length, 1);
    } finally {
      again.restore();
    }
  }],
  ['direct send without a final answer: inputs held back, then asked about again (gone means spent)', async () => {
    const { me, funding } = await funded(2000000);
    const to = (await newRandomKeys()).address;
    const api = installFakeApi({ substates: new Map([[funding.id, funding]]), txDecision: null });
    const stop = new AbortController();
    try {
      setTimeout(() => stop.abort(), 1500);
      await rejects(() => send(me, { to, amountUt: 1000, signal: stop.signal }), (e) => e?.name === 'AbortError');
      const held = (await inboxState(me)).wallet[0];
      ok(held.pending?.tx && !held.spent, 'pending, not spent');
      eq(await balance(me), 0n, 'not offered while the transaction may still land');
      await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof WalletError && e.code === 'insufficient');
      const state = await inboxState(me);
      state.wallet[0].pending.at -= 200000; // three minutes and more later
      await idbPut('inbox', 'current', state);
      eq(await balance(me), 2000000n, 'offered again once the hold is over');
    } finally {
      api.restore();
    }
    const landed = installFakeApi({ substates: new Map() });
    try {
      await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof WalletError && e.code === 'insufficient');
      ok(landed.state.requests.some((r) => r.url.includes('/chain/ix/substates/')), 'the indexer was asked');
      ok((await inboxState(me)).wallet[0].spent, 'the transaction landed: its input is gone, so spent');
      eq(await balance(me), 0n);
    } finally {
      landed.restore();
    }
  }],
  ['direct send refuses an epoch that isn\'t a safe integer before building anything', async () => {
    const { me, funding } = await funded(2000000);
    const api = installFakeApi({ substates: new Map([[funding.id, funding]]), epoch: '12000,"min_epoch":1' });
    try {
      const to = (await newRandomKeys()).address;
      await rejects(() => send(me, { to, amountUt: 1000 }), (e) => e instanceof WalletError && e.code === 'rejected');
      eq(api.state.submitted.length, 0);
    } finally {
      api.restore();
    }
  }],
  ['ensureGrant(): a funded wallet asks for nothing; a short one asks once a day, and pages asking at once share the request', async () => {
    const done = grantStorage();
    const { me, funding } = await funded(2000000);
    const api = installFakeApi({ substates: new Map([[funding.id, funding]]), config: SPONSORED });
    try {
      eq(await ensureGrant(me, SPONSORED), 'funded');
      eq(api.state.sponsored.length, 0);
      eq(await ensureGrant(me, SPONSORED, { need: 3000000n }), 'pending', 'short of a pack: asks');
      eq(await ensureGrant(me, { ...SPONSORED, features: { ...SPONSORED.features, sponsor: false } }), null, 'no sponsor, no grant');
      eq((await Promise.all([ensureGrant(me, SPONSORED, { need: 3000000n }), ensureGrant(me, SPONSORED, { need: 3000000n })])).join(), 'pending,pending');
      eq(api.state.sponsored.length, 1, 'one request a day');
      eq(api.state.sponsored[0], me.wallet.address);
      const kept = localGet('mutis.grant');
      localSet('mutis.grant', { ...kept, at: kept.at - 11 * 60000 });
      eq(await ensureGrant(me, SPONSORED, { need: 3000000n }), 'refused', 'asked ten minutes ago and still short: no grant today');
      eq(api.state.sponsored.length, 1);
    } finally {
      api.restore();
      done();
    }
  }],
  ['ensureGrant(): a refusal is said and kept for the day; a judge pass saved later asks once more', async () => {
    const done = grantStorage();
    const { me } = await funded(1000);
    const refusing = installFakeApi({ config: SPONSORED, sponsorStatus: 429 });
    try {
      eq(await ensureGrant(me, SPONSORED), 'refused');
      eq(await ensureGrant(me, SPONSORED), 'refused');
      eq(refusing.state.sponsored.length, 1, 'not asked again the same day');
    } finally {
      refusing.restore();
    }
    const api = installFakeApi({ config: SPONSORED, judgePasses: new Map([[PASS, 1]]) });
    try {
      setJudgePass(PASS);
      eq(await ensureGrant(me, SPONSORED), 'pending', 'the pass lifts the network limit');
      eq(api.state.judged.join(), '/api/v1/sponsor');
      eq(await ensureGrant(me, SPONSORED), 'pending');
      eq(api.state.sponsored.length, 1);
    } finally {
      setJudgePass(null);
      api.restore();
      done();
    }
  }],
  ['deliver(): direct from a funded wallet with a memo our server never sees; relay when the wallet is short', async () => {
    const { me, funding } = await funded(2000000);
    const blob = randomBytes(125);
    const to = (await newRandomKeys()).address;
    const api = installFakeApi({ substates: new Map([[funding.id, funding]]), config: DIRECT });
    try {
      const direct = await deliver(me, { address: to, kind: 3, blob });
      eq(direct.mode, 'direct');
      eq(api.state.submitted.length, 1);
      eq(api.state.courier.length, 0);
      const relayed = await deliver(me, { address: to, kind: 3, blob });
      eq(relayed.mode, 'relay', 'the only output is spent now');
      eq(api.state.courier.length, 1);
      eq(api.state.courier[0].address, to);
    } finally {
      api.restore();
    }
  }],
];
