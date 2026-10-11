// SPDX-License-Identifier: MIT
import { hex, unhex } from '../lib/b64.js';
import { IntegrityError, randomBytes } from '../lib/crypto.js';
import {
  AddressError, addressErrorCode, bindings, checkTxWithIndexer, checkWithIndexer, classifyAddressInput, decodeAddress,
  decodeBech32m, deriveOotleKeys, encodeBech32m, NETWORK_BYTE, newRandomKeys, parseAddress, ready, reduceScalar, sealToKeys, TARI_RESOURCE,
  tryDecryptUtxo, unwrapBlob, wasmAvailable, wrapToAddress,
} from '../lib/ootle.js';
import { ALPHABET } from '../lib/emoji.js';
import { bytesEq, eq, loadJson, loadOptionalJson, ok, rejects } from './harness.js';

export const env = 'any';

// Real Esmeralda addresses from the research run (03 §2) and the owner's L1 wallet address (03 §5).
const SERVICE = 'otl_esm_1n35xxy75a05ugssednxuu7x0sqh2k32fjcwtc62j9kt8ak992ssz5dysjzpq4mlur445r36qsepeklw9fjudljwx0jrawledarn5wfqj4wh68';
const BUYER = 'otl_esm_1ycq9y2majhpmlphlpy4perwmwg6l03yy3qy0ldrxycny855da3wppmz5glgu68clejlyczt8wt7xrrc0yu75ec25ksj8vrmks3w8jdsh40wkw';
const L1_BASE58 = 'f2A414JxJkndvrMhG1oduFycjh5LVdCC8qMSgWT3zTQHdLgPqwRARTWiCBrFGqTqonSCLvc5vu8SbxZCYh49WXYiCmg';

// BIP-350 test vectors (bitcoin/bips bip-0350.mediawiki). "an84…" (over 90 characters) is left out on
// purpose: Ootle addresses are longer than that bound.
const BIP350_VALID = ['A1LQFN3A', 'a1lqfn3a', 'an83characterlonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber11sg7hg6',
  'abcdef1l7aum6echk45nj3s0wdvt2fg8x9yrzpqzd3ryx', 'split1checkupstagehandshakeupstreamerranterredcaperredlc445v', '?1v759aa'];
// Valid checksum, but its 380 data bits don't pack into whole bytes, so it can't be an address payload.
const BIP350_VALID_NOT_BYTES = '11llllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllludsr8';
const BIP350_INVALID = ['\x201xj0phk', '\x7f1g6xzxy', '\x801vctc34', 'qyrz8wqd2c9m', '1qyrz8wqd2c9m', 'y1b0jsk6g', 'lt1igcx5c0',
  'in1muywd', 'mm1crxm3i', 'au1s5cgom', 'M1VUXWEZ', '16plkw9', '1p2gdwpf'];

export default [
  ['WebAssembly is available here and the official module loads (hash-pinned)', async () => {
    ok(wasmAvailable());
    await ready();
  }],
  ['bech32m: BIP-350 valid and invalid vectors', () => {
    for (const s of BIP350_VALID) ok(decodeBech32m(s) !== null, s);
    for (const s of BIP350_INVALID) eq(decodeBech32m(s), null, JSON.stringify(s));
    eq(decodeBech32m(BIP350_VALID_NOT_BYTES), null);
  }],
  ['addresses: real Esmeralda addresses decode, re-encode, and agree with the official parser', async () => {
    for (const a of [SERVICE, BUYER]) {
      const d = decodeBech32m(a);
      eq(d.hrp, 'otl_esm_');
      eq(d.payload.length, 64);
      eq(encodeBech32m(d.hrp, d.payload), a);
      const p = await parseAddress(a);
      eq(p.network, NETWORK_BYTE);
      bytesEq(p.ownerPk, d.payload.subarray(0, 32));
    }
    const owner = hex(decodeAddress(SERVICE).ownerPk);
    ok(owner.startsWith('9c686313') && owner.endsWith('a55420'), 'the service account key walletd reported');
  }],
  ['address classification (§4.9.4) before any network call', () => {
    const { payload } = decodeBech32m(SERVICE);
    const invoice = encodeBech32m('otl_esm_', new Uint8Array([...payload, ...new TextEncoder().encode('inv_abcdefghijklmnopqrst')]));
    const cases = [
      [SERVICE, 'ootle_testnet'], [SERVICE.toUpperCase(), 'ootle_testnet'], [`  ${BUYER}\n`, 'ootle_testnet'], [invoice, 'ootle_testnet'],
      [encodeBech32m('otl_', payload), 'ootle_other'], [encodeBech32m('otl_loc_', payload), 'ootle_other'],
      [SERVICE.slice(0, -1) + (SERVICE.endsWith('8') ? '9' : '8'), 'invalid'], [encodeBech32m('otl_esm_', payload.subarray(0, 40)), 'invalid'],
      [L1_BASE58, 'l1_base58'], [ALPHABET.slice(40, 73).join(''), 'l1_emoji'], [ALPHABET.slice(0, 33).join(' '), 'l1_emoji'],
      [ALPHABET.slice(0, 19).join(''), 'invalid'], ['🎃'.repeat(19) + '🦄', 'invalid'], ['', 'invalid'], ['hello', 'invalid'],
      ['0x' + 'ab'.repeat(20), 'invalid'],
    ];
    for (const [input, cls] of cases) eq(classifyAddressInput(input), cls, input.slice(0, 40));
    eq(addressErrorCode('ootle_testnet'), null);
    eq(addressErrorCode('ootle_other'), 'mainnet_address');
    eq(addressErrorCode('l1_emoji'), 'l1_address');
    eq(addressErrorCode('l1_base58'), 'l1_address');
    eq(addressErrorCode('invalid'), 'bad_address');
  }],
  ['addresses: the server builder\'s addr.json (classify, valid, invalid), when present', async () => {
    const v = await loadOptionalJson('../../../server/tests/vectors/addr.json');
    if (!v) return;
    for (const c of v.classify) eq(classifyAddressInput(c.input), c.class, String(c.input).slice(0, 40));
    for (const a of v.valid) {
      const d = decodeAddress(a.address);
      eq(hex(d.ownerPk), a.owner_pk);
      eq(hex(d.viewPk), a.view_pk);
      eq(d.payRef ? hex(d.payRef) : '', a.pay_ref);
    }
    for (const bad of v.invalid) ok(classifyAddressInput(bad.input) !== 'ootle_testnet', bad.why);
  }],
  ['parseAddress throws AddressError with the API code', async () => {
    await rejects(() => parseAddress(L1_BASE58), (e) => e instanceof AddressError && e.code === 'l1_address');
    await rejects(() => parseAddress(encodeBech32m('otl_', decodeBech32m(SERVICE).payload)), (e) => e.code === 'mainnet_address');
    await rejects(() => parseAddress('nope'), (e) => e.code === 'bad_address');
  }],
  ['G2a: seed-derived keys (HKDF 64 bytes mod ℓ) are accepted and match the vectors', async () => {
    const v = await loadJson('vectors/format-v1.json');
    const w = await loadJson('vectors/wrap-v2.json');
    for (const s of v.scalars_mod_l) eq(hex(reduceScalar(unhex(s.hkdf64))), s.reduced, s.info);
    const k = await deriveOotleKeys(unhex(v.inputs.seed), 'ootle');
    eq(hex(k.ownerPk), w.locker.owner_pk);
    eq(hex(k.viewPk), w.locker.view_pk);
    bytesEq(bindings().publicKeyFromSecretKey(k.viewSk), k.viewPk, 'view pk = view sk · G');
    await rejects(() => deriveOotleKeys(unhex(v.inputs.seed), 'other'), TypeError);
  }],
  ['G2b: owner-key Diffie-Hellman is symmetric (20 random pairs)', async () => {
    await ready();
    const w = bindings();
    for (let i = 0; i < 20; i++) {
      const r = w.generateKeypair();
      const o = await newRandomKeys();
      bytesEq(w.encryptedDataDhKdfAead(r.secret_key, o.ownerPk), w.encryptedDataDhKdfAead(o.ownerSk, r.public_key), `pair ${i}`);
      r.free();
    }
  }],
  ['G2: a stealth output to a seed-derived address decrypts, and its one-time key is ours to spend', async () => {
    const k = await deriveOotleKeys(randomBytes(32), 'wallet');
    const w = bindings();
    const wit = JSON.parse(w.createStealthOutputWitness(NETWORK_BYTE, k.ownerPk, k.viewPk, 4242n, TARI_RESOURCE, null, JSON.stringify({ Message: 'hi' }), null, 0n));
    const st = w.generateStealthOutputsStatement(JSON.stringify([wit]), 0n, new Uint8Array(32));
    const out = JSON.parse(st.statement_json).outputs[0];
    st.free();
    const d = await tryDecryptUtxo(k.viewSk, { id: `utxo_${'01'.repeat(32)}_${out.output.commitment}`, nonce: out.output.sender_public_nonce, enc: out.output.encrypted_data });
    eq(d.value, 4242n);
    eq(d.memo.Message, 'hi');
    eq(hex(w.publicKeyFromSecretKey(w.stealthDhSecret(NETWORK_BYTE, k.ownerSk, unhex(out.output.sender_public_nonce)))), out.auth.Key);
  }],
  ['wrap v2: kind 3 and kind 4 blobs with fixed r are byte-identical to the vectors and open', async () => {
    const w = await loadJson('vectors/wrap-v2.json');
    const locker = { ownerSk: unhex(w.locker.owner_sk), viewSk: unhex(w.locker.view_sk), ownerPk: unhex(w.locker.owner_pk), viewPk: unhex(w.locker.view_pk) };
    const inner = unhex(w.inner.bytes);
    for (const kind of [3, 4]) {
      const blob = await sealToKeys(locker, inner, kind, { r: unhex(w.r), iv: unhex(w.iv) });
      eq(hex(blob), w[`kind${kind}`].blob, `kind ${kind}`);
      eq(blob.length, 125);
      bytesEq(await unwrapBlob(locker, blob, kind), inner);
    }
  }],
  ['A-14: a kind-3 blob never opens with the view key alone', async () => {
    const w = await loadJson('vectors/wrap-v2.json');
    const viewOnly = { viewSk: unhex(w.locker.view_sk), viewPk: unhex(w.locker.view_pk) };
    const blob3 = unhex(w.kind3.blob);
    await rejects(() => unwrapBlob(viewOnly, blob3, 3), IntegrityError, 'no owner key');
    await rejects(() => unwrapBlob(viewOnly, blob3, 4), IntegrityError, 'kind-4 derivation on a kind-3 blob');
    await rejects(() => unwrapBlob({ ...viewOnly, ownerSk: unhex(w.locker.view_sk), ownerPk: unhex(w.locker.owner_pk) }, blob3, 3), IntegrityError, 'view key in the owner slot');
    bytesEq(await unwrapBlob(viewOnly, unhex(w.kind4.blob), 4), unhex(w.inner.bytes), 'kind 4 does open with the view key');
  }],
  ['wraps: random r round trip through an address; tampered or misdirected blobs fail', async () => {
    const me = await newRandomKeys();
    const other = await newRandomKeys();
    const inner = randomBytes(65);
    const blob = await wrapToAddress(me.address, inner, 3);
    bytesEq(await unwrapBlob(me, blob, 3), inner);
    await rejects(() => unwrapBlob(other, blob, 3), IntegrityError, 'another locker');
    for (const at of [0, 40, 100]) {
      const t = blob.slice();
      t[at] ^= 1;
      await rejects(() => unwrapBlob(me, t, 3), IntegrityError, `byte ${at}`);
    }
    await rejects(() => unwrapBlob(me, blob.subarray(1), 3), IntegrityError, 'short');
    await rejects(() => sealToKeys(me, randomBytes(64), 3), TypeError);
  }],
  ['real Esmeralda outputs decrypt to their recorded values and memos', async () => {
    const w = await loadJson('vectors/wrap-v2.json');
    eq(w.real_outputs.length, 5);
    for (const r of w.real_outputs) {
      const d = await tryDecryptUtxo(unhex(r.view_sk), r);
      eq(d?.value.toString(), r.value_ut, r.id.slice(-8));
      eq(JSON.stringify(d.memo), JSON.stringify(r.memo));
    }
    const stranger = await newRandomKeys();
    eq(await tryDecryptUtxo(stranger.viewSk, w.real_outputs[0]), null, 'a stranger opens nothing');
  }],
  ['G4: crafted outputs whose payload doesn\'t open their commitment are rejected', async () => {
    const w = await loadJson('vectors/wrap-v2.json');
    for (const c of w.crafted) eq(await tryDecryptUtxo(unhex(c.view_sk), c), null, c.name);
    eq(await tryDecryptUtxo(randomBytes(32), { id: 'utxo_bad', nonce: '00', enc: '00' }), null, 'malformed row');
  }],
  ['checkWithIndexer: only substates and committed receipts, straight at the public indexers, nothing else', async () => {
    const tx = 'ab'.repeat(32);
    for (const bad of [`transactions/${tx}/result`, `transaction-receipts/${tx}/x`, 'epoch-manager/stats', `substates/vault_${tx}`, `../transaction-receipts/${tx}`]) {
      await rejects(() => checkWithIndexer(bad), TypeError, bad);
    }
    const realFetch = globalThis.fetch;
    const asked = [];
    globalThis.fetch = async (url, init) => {
      asked.push({ url: String(url), credentials: init.credentials, referrerPolicy: init.referrerPolicy });
      if (asked.length === 1) throw new TypeError('indexer-b is down');
      return new Response('{"receipt":{"outcome":"Commit"}}', { status: 200 });
    };
    try {
      const r = await checkTxWithIndexer(tx);
      eq(r.origin, 'https://ootle-indexer-a.tari.com', 'falls back to the other indexer');
      eq(r.body.receipt.outcome, 'Commit');
      eq(asked.map((a) => a.url).join(' '), `https://ootle-indexer-b.tari.com/transaction-receipts/${tx} https://ootle-indexer-a.tari.com/transaction-receipts/${tx}`);
      ok(asked.every((a) => a.credentials === 'omit' && a.referrerPolicy === 'no-referrer'));
    } finally {
      globalThis.fetch = realFetch;
    }
  }],
];
