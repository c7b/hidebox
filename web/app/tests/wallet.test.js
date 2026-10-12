// SPDX-License-Identifier: MIT
import { randomBytes } from '../lib/crypto.js';
import { identityFromSeed } from '../lib/identity.js';
import { newRandomKeys, ready } from '../lib/ootle.js';
import { idbPut, set } from '../lib/store.js';
import { inboxState } from '../lib/scan.js';
import { FEE_UT, WalletError, balance, deliver, send } from '../lib/wallet.js';
import { ApiError } from '../lib/api.js';
import { installFakeApi } from './fake-api.js';
import { outputTo } from './outputs.js';
import { eq, ok, rejects } from './harness.js';

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
