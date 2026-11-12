// SPDX-License-Identifier: MIT
// lib/withdraw.js (docs/withdraw.md): the rules (the fee out of the amount, the minimum, dust that goes along, at most
// max_inputs payments, money on its way left alone), the address checks (network, checksum, payment reference, the
// drive's own sales address), and a whole withdrawal against a stand-in for our server and the indexer: built and
// signed here from genuine sales outputs (the official library), one submission however often it is asked for, the
// change reported with its id and value, the outcome reported; nothing that can spend ever leaves this browser.
import { b64uEncode, hex } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { configureApi } from '../lib/api.js';
import { identityFromSeed } from '../lib/identity.js';
import { addressFromKeys, encodeBech32m, newRandomKeys, ready, tryDecryptUtxo } from '../lib/ootle.js';
import { salesKeys } from '../lib/pay.js';
import * as wd from '../lib/withdraw.js';
import { outputTo } from './outputs.js';
import { eq, ok, rejects } from './harness.js';

export const env = 'any';

const ORIGIN = 'https://withdraw.mutis.test';
const RULES = wd.rulesOf({ min_ut: '60000', dust_ut: '30000', max_inputs: 8, pending_s: 600 });
const out = (id, value, extra = {}) => ({ utxo_id: id, value_ut: String(value), ...extra });

// Our server's withdraw routes and the indexer's reads, over fetch, recording what the client sends.
function fakeChain({ outputs, decision = 'Commit', gone = new Set() }) {
  const realFetch = globalThis.fetch;
  const byId = new Map(outputs.map((o) => [o.id, o]));
  const state = { sent: [], posts: [], reports: [] };
  globalThis.fetch = async (input, init = {}) => {
    const req = new Request(input, init);
    const url = new URL(req.url);
    const body = req.method === 'GET' ? null : await req.text();
    state.sent.push({ method: req.method, url: req.url, headers: [...req.headers], body });
    const json = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const sub = /^\/chain\/ix\/substates\/(utxo_[0-9a-f_]+)$/.exec(path);
    if (sub) {
      const o = byId.get(sub[1]);
      if (!o || gone.has(sub[1])) return json(404, { error: { code: 'not_found', message: 'x' } });
      return json(200, { substate: { Utxo: { output: { auth: { Key: '00'.repeat(32) }, output: { public_nonce: o.nonce, encrypted_data: o.enc } }, is_frozen: false } } });
    }
    if (path === '/chain/ix/epoch-manager/stats') return json(200, { current_epoch: 100 });
    if (path === '/me/withdrawals' && req.method === 'POST') {
      state.posts.push(JSON.parse(body));
      await new Promise((r) => setTimeout(r, 30));
      return json(201, { tx_id: 'ab'.repeat(32), inputs: [] });
    }
    if (/^\/chain\/ix\/transactions\/[0-9a-f]{64}\/result$/.test(path)) return json(200, { result: { Finalized: { final_decision: decision } } });
    const rep = /^\/me\/withdrawals\/([0-9a-f]{64})$/.exec(path);
    if (rep) {
      state.reports.push([rep[1], JSON.parse(body).outcome]);
      return json(200, { tx_id: rep[1], outcome: JSON.parse(body).outcome });
    }
    return json(404, { error: { code: 'not_found', message: path } });
  };
  configureApi({ origin: ORIGIN });
  return { state, restore: () => { globalThis.fetch = realFetch; } };
}

async function seller() {
  await ready();
  const identity = await identityFromSeed(randomBytes(32), {}, { lazy: true });
  const keys = await salesKeys(identity);
  return { identity, keys };
}

export default [
  ['amounts: tTARI with up to 6 decimals, nothing else', () => {
    eq(wd.parseAmount('0.25'), 250000n);
    eq(wd.parseAmount('2'), 2000000n);
    eq(wd.parseAmount(' 1,5 '), 1500000n);
    eq(wd.parseAmount('0.000001'), 1n);
    for (const bad of ['', '-1', '1e3', '0.0000001', 'abc', '1.2.3', null]) eq(wd.parseAmount(bad), null, String(bad));
  }],
  ['the plan: the fee out of the amount, a minimum, dust that goes along, the biggest payments first, at most max_inputs', () => {
    const list = [out('a', 100000), out('b', 250000), out('c', 40000)];
    let p = wd.plan(list, 200000n, RULES);
    eq(p.inputs.map((o) => o.utxo_id).join(), 'b');
    eq([p.withdrawUt, p.feeUt, p.arriveUt, p.changeUt, p.dustUt].join(), '200000,30000,170000,50000,0');
    p = wd.plan(list, 230000n, RULES);                        // 20,000 would stay: less than the fee to move it
    eq([p.withdrawUt, p.arriveUt, p.changeUt, p.dustUt].join(), '250000,220000,0,20000');
    p = wd.plan(list, 'all', RULES);
    eq([p.inputs.length, p.withdrawUt, p.arriveUt, p.changeUt].join(), '3,390000,360000,0');
    eq(wd.plan(list, 59999n, RULES).error, 'below_min');
    eq(wd.plan(list, 400000n, RULES).error, 'over');
    const many = Array.from({ length: 10 }, (_, i) => out(`m${i}`, 100000));
    p = wd.plan(many, 'all', RULES);
    eq([p.inputs.length, p.withdrawUt, p.capped].join(), '8,800000,true');
    const over = wd.plan(many, 900000n, RULES);
    eq([over.error, over.best, over.max].join(), 'too_many,800000,8');
  }],
  ['money on its way is left alone until the window passes', () => {
    const now = 1_800_000_000;
    const list = [out('a', 100000, { pending_tx: 'cd'.repeat(32), pending_at: now - 10 }), out('b', 250000),
      out('c', 40000, { pending_tx: 'ef'.repeat(32), pending_at: now - 601 })];
    const a = wd.available(list, RULES, now);
    eq(a.free.map((o) => o.utxo_id).join(), 'b,c');
    eq(a.onTheirWay.map((o) => o.utxo_id).join(), 'a');
    eq(a.total, 290000n);
  }],
  ['the address: this network, its checksum, no payment reference, not the drive\'s own sales address', async () => {
    const { identity, keys } = await seller();
    const them = await newRandomKeys();
    const good = await addressFromKeys(them.ownerPk, them.viewPk);
    ok((await wd.checkAddress(identity, good)).ownerPk.length === 32, 'a testnet address');
    const parts = wd.addressParts(good);
    eq(parts.prefix + parts.head + parts.middle + parts.tail, good);
    eq([parts.prefix, parts.head.length, parts.tail.length].join(), 'otl_esm_1,6,6');
    // addressParts sets apart six characters after otl_1 too: the mainnet's prefix has one word, not two
    const main = wd.addressParts(encodeBech32m('otl_', new Uint8Array([...them.ownerPk, ...them.viewPk])));
    eq([main.prefix, main.head.length, main.tail.length].join(), 'otl_1,6,6');
    ok(!main.head.includes('_') && main.prefix + main.head + main.middle + main.tail === encodeBech32m('otl_', new Uint8Array([...them.ownerPk, ...them.viewPk])));
    eq(JSON.stringify(wd.addressParts('otl_1' + 'q'.repeat(10))), JSON.stringify({ prefix: 'otl_1', head: 'q'.repeat(10), middle: '', tail: '' }), 'a short one is shown whole');
    const mainnet = encodeBech32m('otl_', new Uint8Array([...them.ownerPk, ...them.viewPk]));
    await rejects(() => wd.checkAddress(identity, mainnet), 'mainnet_address', 'another network');
    await rejects(() => wd.checkAddress(identity, good.slice(0, -1) + (good.at(-1) === 'q' ? 'p' : 'q')), 'bad_address', 'a broken checksum');
    await rejects(() => wd.checkAddress(identity, '🐢'.repeat(33)), 'l1_address', 'a base-layer address');
    const withRef = await addressFromKeys(them.ownerPk, them.viewPk, randomBytes(8));
    await rejects(() => wd.checkAddress(identity, withRef), 'pay_ref', 'a payment reference');
    await rejects(() => wd.checkAddress(identity, keys.address), 'own_sales', 'the drive\'s own sales address');
  }],
  ['a withdrawal: built and signed here from genuine sales outputs, sent once, its change and outcome reported; no key leaves', async () => {
    const { identity, keys } = await seller();
    const outs = [outputTo(keys, 250000), outputTo(keys, 100000)];
    const list = outs.map((o, i) => out(o.id, [250000, 100000][i]));
    const them = await newRandomKeys();
    const to = await addressFromKeys(them.ownerPk, them.viewPk);
    const chain = fakeChain({ outputs: outs });
    try {
      const p = wd.plan(list, 300000n, RULES);
      const steps = [];
      const first = wd.withdraw(identity, { to, plan: p, rules: RULES, headers: { Authorization: 'Bearer x' }, onStep: (s) => steps.push(s) });
      await rejects(() => wd.withdraw(identity, { to, plan: p, rules: RULES, headers: {} }), 'busy', 'a second press while one runs');
      const done = await first;
      eq(steps.join(), 'build,sent,chain');
      eq(chain.state.posts.length, 1);
      const post = chain.state.posts[0];
      eq([done.arriveUt, done.feeUt, done.changeUt].join(), '270000,30000,50000');
      eq(post.change.value_ut, '50000');
      ok(/^utxo_(01){32}_[0-9a-f]{64}$/.test(post.change.utxo_id) && !outs.some((o) => o.id === post.change.utxo_id), 'the change is a new output');
      ok(typeof post.transaction === 'string' && post.transaction.length > 1000, 'a sealed envelope');
      eq(chain.state.reports.map((r) => r.join(':')).join(), `${'ab'.repeat(32)}:commit`);
      const sent = JSON.stringify(chain.state.sent);
      for (const secret of [hex(keys.ownerSk), hex(keys.viewSk), hex(identity.seed), b64uEncode(keys.ownerSk), b64uEncode(identity.seed)]) {
        ok(!sent.includes(secret), 'nothing that can spend left this browser');
      }
      ok(!sent.includes(to), 'the destination address never went to our server');
      ok(!JSON.stringify(chain.state.posts).includes(hex(them.ownerPk)), 'nor its keys in the clear');
      // The sales view key opens neither input again as anyone else's: they were this drive's, found by its key.
      ok(await tryDecryptUtxo(keys.viewSk, outs[0]), 'the inputs were the sales address\'s');
    } finally {
      chain.restore();
    }
  }],
  ['a payment spent elsewhere sends nothing; a rejected withdrawal is reported so its money is free again', async () => {
    const { identity, keys } = await seller();
    const outs = [outputTo(keys, 250000)];
    const list = [out(outs[0].id, 250000)];
    const them = await newRandomKeys();
    const to = await addressFromKeys(them.ownerPk, them.viewPk);
    let chain = fakeChain({ outputs: outs, gone: new Set([outs[0].id]) });
    try {
      await rejects(() => wd.withdraw(identity, { to, plan: wd.plan(list, 'all', RULES), rules: RULES, headers: {} }), 'input_gone', 'spent elsewhere');
      eq(chain.state.posts.length, 0);
    } finally {
      chain.restore();
    }
    chain = fakeChain({ outputs: outs, decision: { Reject: 'x' } });
    try {
      await rejects(() => wd.withdraw(identity, { to, plan: wd.plan(list, 'all', RULES), rules: RULES, headers: {} }), 'rejected', 'the network refused it');
      eq(chain.state.reports.map((r) => r[1]).join(), 'reject');
    } finally {
      chain.restore();
    }
  }],
  ['a withdrawal that never said how it ended is settled on evidence: an input shown unspent never went, one proven spent did, a 404 says neither', async () => {
    const { keys } = await seller();
    const o = outputTo(keys, 250000);
    const tx = 'cd'.repeat(32);
    const stale = [out(o.id, 250000, { source: 'sale', pending_tx: tx, pending_at: 1 })];
    const realFetch = globalThis.fetch;
    const reports = [];
    let answer;
    globalThis.fetch = async (input, init = {}) => {
      const url = new URL(String(input));
      if (url.origin !== ORIGIN) return realFetch(input, init);
      const json = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });
      const path = url.pathname.replace(/^\/api\/v1/, '');
      if (path.endsWith('/result')) return json(404, { error: { code: 'not_found' } });   // the indexers forgot the transaction
      if (path.startsWith('/chain/ix/substates/')) return json(...answer);
      if (path === `/me/withdrawals/${tx}`) {
        reports.push(JSON.parse(init.body).outcome);
        return json(200, {});
      }
      return json(404, { error: { code: 'not_found' } });
    };
    configureApi({ origin: ORIGIN });
    const up = { Utxo: { output: { auth: { Key: '00'.repeat(32) }, output: { public_nonce: o.nonce, encrypted_data: o.enc } }, is_frozen: false } };
    try {
      for (const [what, ans, said, settled] of [
        ['a 404 (an indexer that hasn\'t caught up answers the same)', [404, { error: { code: 'not_found' } }], [], 0],
        ['no indexer answering', [503, { error: { code: 'chain_unavailable' } }], [], 0],
        ['the input shown unspent', [200, { version: 0, state: { up: { substate: up } }, verified: true }], ['reject'], 1],
        ['the input proven spent', [200, { version: 0, state: { down: {} }, verified: true, proof: { down_proof: '' } }], ['commit'], 1],
      ]) {
        answer = ans;
        reports.length = 0;
        eq(await wd.settleStale(stale, RULES, {}, 1000000), settled, what);
        eq(reports.join(), said.join(), what);
      }
      eq(await wd.settleStale([out(o.id, 250000, { source: 'sale', pending_tx: tx, pending_at: 999999 })], RULES, {}, 1000000), 0, 'one still inside its window is left alone');
    } finally {
      globalThis.fetch = realFetch;
    }
  }],
];
