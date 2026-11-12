// SPDX-License-Identifier: MIT
// lib/ristretto.js (RFC 9496) and the watch-only ownership check built on it (lib/ootle.js watchOneTimeKey), which
// lets our payment checker release a sale without the seller's drive (docs/mvp-november.md §2). Checked against the
// RFC's own vectors, against the official library (n·G + m·G = (n + m)·G for random n, m), and on genuine stealth
// outputs the official library builds: one paid to the seller's keys passes, one that opens with the seller's view key
// but carries another owner's key fails, as does the frozen ownership known-answer test of the sidecar.
import { hex, unhex } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { NETWORK_BYTE, TARI_RESOURCE, bindings, newRandomKeys, oneTimeKey, ready, tryDecryptUtxo, watchOneTimeKey } from '../lib/ootle.js';
import { L, add, decode, encode, scalarSub } from '../lib/ristretto.js';
import { eq, ok } from './harness.js';

export const env = 'any';

// RFC 9496 Appendix A.1: the encodings of 0·B to 15·B.
const MULTIPLES = [
  '0000000000000000000000000000000000000000000000000000000000000000',
  'e2f2ae0a6abc4e71a884a961c500515f58e30b6aa582dd8db6a65945e08d2d76',
  '6a493210f7499cd17fecb510ae0cea23a110e8d5b901f8acadd3095c73a3b919',
  '94741f5d5d52755ece4f23f044ee27d5d1ea1e2bd196b462166b16152a9d0259',
  'da80862773358b466ffadfe0b3293ab3d9fd53c5ea6c955358f568322daf6a57',
  'e882b131016b52c1d3337080187cf768423efccbb517bb495ab812c4160ff44e',
  'f64746d3c92b13050ed8d80236a7f0007c3b3f962f5ba793d19a601ebb1df403',
  '44f53520926ec81fbd5a387845beb7df85a96a24ece18738bdcfa6a7822a176d',
  '903293d8f2287ebe10e2374dc1a53e0bc887e592699f02d077d5263cdd55601c',
  '02622ace8f7303a31cafc63f8fc48fdc16e1c8c8d234b2f0d6685282a9076031',
  '20706fd788b2720a1ed2a5dad4952b01f413bcf0e7564de8cdc816689e2db95f',
  'bce83f8ba5dd2fa572864c24ba1810f9522bc6004afe95877ac73241cafdab42',
  'e4549ee16b9aa03099ca208c67adafcafa4c3f3e4e5303de6026e3ca8ff84460',
  'aa52e000df2e16f55fb1032fc33bc42742dad6bd5a8fc0be0167436c5948501f',
  '46376b80f409b29dc2b5f6f0c52591990896e5716f41477cd30085ab7f10301e',
  'e0c418f7c8d9c4cdd7395b93ea124f3ad99021bb681dfc3302a9d99a2e53e64e',
];

// Encodings decode() must refuse: non-canonical (s ≥ p), negative (s odd), and not a valid point.
const BAD = [
  'edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',   // p itself
  'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',   // above p
  '0100000000000000000000000000000000000000000000000000000000000000',   // negative
  '0300000000000000000000000000000000000000000000000000000000000000',
  'f3ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',   // negative and above p
  '26948d35ca62e643e26a83177332e6b6afeb9d08e4268b650f1f5bbd8d81d371',   // not a square (RFC 9496 A.2)
  '4eac077a713c57b4f4397629a4145982c661f48044dd3f96427d40b147d9742f',
  'de6a7b00deadc788eb6b6c8d26b8e8de8dc5d9f1c3e0f9a3e8f2d1b3c4a5d6c7',
];

// web/app/sidecar/selftest.json `ownership` (Esmeralda, ootle-wasm 0.49.2, throwaway keys): both outputs open with the
// view key; only `genuine` carries the one-time key the owner key derives.
const OWNERSHIP = {
  owner_sk: 'a96c0c0e99a59a77c76efd2505488b4facdd6d40ba0c84239f55ebc0de00c206',
  view_sk: 'de7a17aa69c67cba6913615c06fb0f8878deb2e1b027dfa94535791db4939804',
  genuine: { nonce: 'be8941bc7e07aa8238c60e52e5a0a52b545a00f68cee7b1bee04d94d00bd800a', auth_key: 'e0f36a1ef3021253c7803f2df44ef591343b0470c5a82c020214a8ac8f221e1a' },
  not_ours: { nonce: '840a5eba811c2c9e17ebb605cfd39de3b1dc53a202c558abd4e431c6fadcd453', auth_key: 'a67740d9f632cbba5bba498becdd5dfa342289c31c06aec77593d01112c42d29' },
};

const scalar = (n) => {
  const out = new Uint8Array(32);
  let x = n % L;
  for (let i = 0; i < 32; i++) {
    out[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return out;
};
const randomScalar = () => {
  let n = 0n;
  for (const b of randomBytes(64)) n = (n << 8n) | BigInt(b);
  return n % L;
};

// A stealth output the official library builds for {ownerPk, viewPk}: its nonce (hex) and the one-time key it carries.
function outputFor(ownerPk, viewPk, amount = 1000n) {
  const w = bindings();
  const out = JSON.parse(w.createStealthOutputWitness(NETWORK_BYTE, ownerPk, viewPk, amount, TARI_RESOURCE, null, null, null, 0n));
  return { nonce: out.witness.sender_public_nonce, key: out.auth.Key };
}

export default [
  ['RFC 9496 vectors: 0·B to 15·B decode, encode back, and B added n times gives n·B', async () => {
    for (const v of MULTIPLES.slice(1)) eq(hex(encode(decode(unhex(v)))), v);
    eq(decode(unhex(MULTIPLES[0])) !== null, true, 'the identity decodes');
    let acc = unhex(MULTIPLES[1]);
    for (let n = 2; n < MULTIPLES.length; n++) {
      acc = add(acc, unhex(MULTIPLES[1]));
      eq(hex(acc), MULTIPLES[n], `${n}·B`);
    }
    eq(hex(add(unhex(MULTIPLES[0]), unhex(MULTIPLES[7]))), MULTIPLES[7], 'adding the identity');
  }],
  ['refused encodings: non-canonical, negative, not a point, the wrong length', async () => {
    for (const v of BAD) eq(decode(unhex(v)), null, v);
    eq(decode(new Uint8Array(31)), null, 'short');
    eq(decode(new Uint8Array(33)), null, 'long');
    let threw = false;
    try {
      add(unhex(BAD[0]), unhex(MULTIPLES[1]));
    } catch (e) {
      threw = e instanceof RangeError;
    }
    ok(threw, 'add() refuses a bad point');
  }],
  ['against the official library: n·G + m·G = (n + m)·G for random n and m, and the scalar difference', async () => {
    await ready();
    const w = bindings();
    eq(hex(w.publicKeyFromSecretKey(scalar(1n))), MULTIPLES[1], 'the library\'s G is the RFC\'s B');
    for (let i = 0; i < 24; i++) {
      const n = randomScalar();
      const m = randomScalar();
      const sum = hex(add(w.publicKeyFromSecretKey(scalar(n)), w.publicKeyFromSecretKey(scalar(m))));
      eq(sum, hex(w.publicKeyFromSecretKey(scalar(n + m))), `case ${i}`);
      eq(hex(scalarSub(scalar(n + m), scalar(m))), hex(scalar(n)), `difference ${i}`);
    }
  }],
  ['watch-only: an output paid to the keys passes with the view key and the account\'s public key alone', async () => {
    const k = await newRandomKeys();
    for (let i = 0; i < 4; i++) {
      const o = outputFor(k.ownerPk, k.viewPk);
      eq(await watchOneTimeKey(k.ownerPk, k.viewSk, o.nonce), o.key, `output ${i}`);
      eq(await oneTimeKey(k.ownerSk, k.viewSk, o.nonce), o.key, 'the owner-key check agrees');
    }
  }],
  ['watch-only: an output that opens with the view key but carries another owner\'s key fails', async () => {
    const seller = await newRandomKeys();
    const payer = await newRandomKeys();
    const w = bindings();
    const fake = JSON.parse(w.createStealthOutputWitness(NETWORK_BYTE, payer.ownerPk, seller.viewPk, 7000n, TARI_RESOURCE, null, null, null, 0n));
    const st = w.generateStealthOutputsStatement(JSON.stringify([fake]), 0n, new Uint8Array(32));
    const [f] = JSON.parse(st.statement_json).outputs;
    st.free();
    const opened = await tryDecryptUtxo(seller.viewSk, { id: `utxo_${'01'.repeat(32)}_${f.output.commitment}`, nonce: f.output.sender_public_nonce, enc: f.output.encrypted_data });
    eq(opened?.value, 7000n, 'the seller\'s view key opens it');
    const watched = await watchOneTimeKey(seller.ownerPk, seller.viewSk, f.output.sender_public_nonce);
    ok(watched !== null && watched !== f.auth.Key, 'but its one-time key is not the seller\'s');
    eq(await watchOneTimeKey(payer.ownerPk, seller.viewSk, f.output.sender_public_nonce), f.auth.Key, 'it is the payer\'s');
  }],
  ['watch-only: the sidecar\'s frozen ownership KAT, from the owner key\'s public half only', async () => {
    const own = OWNERSHIP;
    const ownerPk = bindings().publicKeyFromSecretKey(unhex(own.owner_sk));
    eq(await watchOneTimeKey(ownerPk, unhex(own.view_sk), own.genuine.nonce), own.genuine.auth_key, 'genuine');
    ok(await watchOneTimeKey(ownerPk, unhex(own.view_sk), own.not_ours.nonce) !== own.not_ours.auth_key, 'not ours');
  }],
  ['watch-only: a nonce or an account key that is not a point gives null, never a key', async () => {
    const k = await newRandomKeys();
    eq(await watchOneTimeKey(k.ownerPk, k.viewSk, BAD[0]), null, 'bad nonce');
    eq(await watchOneTimeKey(unhex(BAD[2]), k.viewSk, outputFor(k.ownerPk, k.viewPk).nonce), null, 'bad account key');
  }],
];
