// SPDX-License-Identifier: MIT
// Writes the frozen vectors (§3.4.8) from fixed inputs with the real library under Node 20:
//   node web/app/tests/vectors/generate.mjs
// format-v1.json  file format, HKDF rows, Padmé, verifiers, identity, PoW (the server recomputes these)
// wrap-v2.json    address wraps with fixed r, memos, real Esmeralda outputs, crafted forgeries
// ../../sidecar/selftest.json  the sidecar's G4 self-test cases (a subset of wrap-v2.json)
// A change to any byte of format-v1.json is a format break and needs a version bump.
import { readFileSync, writeFileSync } from 'node:fs';
import { b64uEncode, hex, unhex } from '../../lib/b64.js';
import { concat, utf8 } from '../../lib/bytes.js';
import { hkdf, pbkdf2Sha256, sha256 } from '../../lib/crypto.js';
import * as format from '../../lib/format.js';
import * as share from '../../lib/share.js';
import * as password from '../../lib/password.js';
import * as ootle from '../../lib/ootle.js';
import { identityFromSeed, keyFileName, keyFileText, recoveryCode } from '../../lib/identity.js';
import { encodeInner, memoFor } from '../../lib/courier.js';
import { searchNonce, leadingZeroBits } from '../../lib/pow.js';
import { sha256Sync } from '../../lib/sha256sync.js';

const here = new URL('./', import.meta.url);
await ootle.initWithBytes(readFileSync(new URL('../../vendor/ootle-wasm-0.45.0/ootle_wasm_bg.wasm', here)));

const seq = (start, n) => Uint8Array.from({ length: n }, (_, i) => (start + i) & 255);
const SEED = seq(0x00, 32);
const S = seq(0x20, 32);
const S0 = seq(0x40, 32);
const FK = seq(0x60, 32);
const SALT = seq(0x80, 16);
const KDF = { alg: 'PBKDF2-SHA256', iter: password.PBKDF2_ITER, salt: b64uEncode(seq(0x90, 16)) };
const PASSWORD = 'correct horse battery staple';
const ORIGINS = ['https://mutis.sh', 'https://srv2052606.hstgr.cloud'];

// --- format-v1 -----------------------------------------------------------------------------------

const hkdfRows = [];
async function row(name, ikmName, ikm, saltName, salt, info, length) {
  const out = await hkdf(ikm, salt, info, length);
  hkdfRows.push({ name, ikm: ikmName, salt: saltName, info, length, out: hex(out) });
  return out;
}

const P = await pbkdf2Sha256(PASSWORD, seq(0x90, 16), KDF.iter);
await row('contentKey', 'fk', FK, 'header_salt', SALT, 'mutis/v1/content', 32);
await row('metaKey', 'fk', FK, 'header_salt', SALT, 'mutis/v1/meta', 32);
await row('wrapKey', 's', S, 'mutis/v1', 'mutis/v1', 'share-wrap', 32);
const accessToken = await row('accessToken', 's', S, 'mutis/v1', 'mutis/v1', 'share-access', 32);
const proof = await row('linkProof', 's0', S0, 'mutis/v1', 'mutis/v1', 'link-proof', 32);
await row('s (link+password)', 's0 ‖ P', concat(S0, P), 'mutis/v1', 'mutis/v1', 'link+password', 32);
await row('s (password only)', 'P', P, 'mutis/v1', 'mutis/v1', 'password-only', 32);
await row('identityId', 'seed', SEED, 'mutis/v1', 'mutis/v1', 'identity-id', 16);
const authKey = await row('authKey', 'seed', SEED, 'mutis/v1', 'mutis/v1', 'auth', 32);
await row('vaultKey', 'seed', SEED, 'mutis/v1', 'mutis/v1', 'vault', 32);
const scalars = [];
for (const info of ['ootle-owner', 'ootle-view', 'wallet-owner', 'wallet-view']) {
  const wide = await row(info, 'seed', SEED, 'mutis/v1', 'mutis/v1', info, 64);
  scalars.push({ info, hkdf64: hex(wide), reduced: hex(ootle.reduceScalar(wide)) });
}
for (const i of [0, 1, 15]) {
  await row(`dropTag(${i})`, 'seed', SEED, 'mutis/v1', 'mutis/v1', `drop-tag/${i}`, 16);
  await row(`dropManage(${i})`, 'seed', SEED, 'mutis/v1', 'mutis/v1', `drop-manage/${i}`, 32);
}

const padmeCases = [0, 1, 1000, 1023, 1024, 1025, 4097, 1000000, 5000000, 4194304, 4194305, 26214400, 1073741824];
const header = format.makeHeader({ chunkCount: 3, salt: SALT });

const plain = Uint8Array.from({ length: 5000 }, (_, i) => i % 251);
const chunks = [];
let first;
for await (const c of format.encryptFile(plain, { fk: FK, salt: SALT })) {
  if (!first) first = c;
  else chunks.push(c);
}
const ciphertext = concat(...chunks.map((c) => c.ciphertext));
const { metaKey } = await format.deriveItemKeys(FK, SALT);
const meta = { v: 1, kind: 'file', name: 'café-menu.pdf', type: 'application/pdf', size: plain.length, mtime: 1760000000000, stripped: false };
const metaIv = seq(0xa0, 12);
const wrapIv = seq(0xb0, 12);
const metaCt = await format.encryptMeta(metaKey, first.headerHash, meta, { iv: metaIv });
const { wrapKey } = await share.shareKeys(S);
const wrapped = await share.wrapFileKey(wrapKey, first.headerHash, FK, { iv: wrapIv });

const powCases = [];
for (const d of [8, 12, 16]) {
  const challenge = concat(Uint8Array.of(1, 1, d, 0), Uint8Array.of(0x68, 0xe9, 0x3c, 0x5c), seq(0xc0, 12), seq(0xd0, 16));
  const nonce = searchNonce(challenge, d, 0, 1 << 24);
  const lz = leadingZeroBits(sha256Sync(concat(challenge, nonce)));
  powCases.push({ challenge: b64uEncode(challenge), nonce: b64uEncode(nonce), difficulty: d, leading_zero_bits: lz, valid: true });
  const bad = seq(0, 8);
  const badLz = leadingZeroBits(sha256Sync(concat(challenge, bad)));
  if (badLz < d) powCases.push({ challenge: b64uEncode(challenge), nonce: b64uEncode(bad), difficulty: d, leading_zero_bits: badLz, valid: false });
}

const id = await identityFromSeed(SEED, { created: '2026-10-14' });

const formatV1 = {
  _about: 'mutis file format v1 and derivation vectors (spec §4). Generated by generate.mjs; frozen. Hex unless a field says b64u.',
  inputs: {
    seed: hex(SEED), s: hex(S), s0: hex(S0), fk: hex(FK), header_salt: hex(SALT), password: PASSWORD, kdf: KDF,
    P: hex(P),
  },
  hkdf: hkdfRows,
  scalars_mod_l: scalars,
  padme: padmeCases.map((L) => [L, format.padme(L)]),
  header: { chunk_count: 3, salt: hex(SALT), bytes: hex(header), sha256: hex(await sha256(header)) },
  verifiers: {
    access_token_b64u: b64uEncode(accessToken),
    access_verifier_b64u: b64uEncode(await sha256(accessToken)),
    link_proof_b64u: b64uEncode(proof),
    link_verifier_b64u: b64uEncode(await sha256(proof)),
  },
  fragments: [
    { kind: 1, secret: hex(S), fragment: share.linkFragment(1, S) },
    { kind: 2, secret: hex(S0), fragment: share.linkFragment(2, S0) },
  ],
  file: {
    plaintext: '5000 bytes, byte i = i mod 251',
    fk: hex(FK), salt: hex(SALT), header: hex(first.header), header_sha256: hex(first.headerHash),
    chunk_count: first.chunkCount, size_stored: first.sizeStored,
    ciphertext_b64u: b64uEncode(ciphertext),
    chunk_sha256_b64u: chunks.map((c) => b64uEncode(c.sha256)),
    ct_hash_b64u: b64uEncode(await format.ctHash(chunks.map((c) => c.sha256))),
    meta, meta_iv: hex(metaIv), meta_ct_b64u: b64uEncode(metaCt),
    link_secret: hex(S), wrap_iv: hex(wrapIv), wrapped_key_b64u: b64uEncode(wrapped),
  },
  identity: {
    seed: hex(SEED), created: '2026-10-14',
    identity_id_b64u: id.id,
    auth_verifier_b64u: b64uEncode(await sha256(authKey)),
    recovery_code: recoveryCode(SEED),
    locker_address: id.locker.address,
    wallet_address: id.wallet.address,
    safety_code: id.safetyCode,
    key_file_name: keyFileName(id),
    key_file_text: keyFileText(id),
  },
  pow: powCases,
};

// --- wrap-v2 -------------------------------------------------------------------------------------

const R_SCALAR = ootle.reduceScalar(seq(0xe0, 64));
const inner = encodeInner({ shareId16: seq(0x10, 16), s: S, flags: 1, ref16: id.dropTag(0) });
const blob3 = await ootle.sealToKeys(id.locker, inner, 3, { r: R_SCALAR, iv: seq(0xf0, 12) });
const blob4 = await ootle.sealToKeys(id.locker, inner, 4, { r: R_SCALAR, iv: seq(0xf0, 12) });

const outputs = JSON.parse(readFileSync(new URL('esmeralda-outputs.json', here), 'utf8'));
const gate = await identityFromSeed(await sha256(utf8('mutis gate test seed v1')));
const research = { viewSk: unhex('c749d79d955beedbe3fd6b2c0f824c1d78291d9fa1cefdadcb85311af3fcdc0c') };
const keyring = [['research browser identity (03 §9 T8)', research], ['gate locker', gate.locker], ['gate wallet', gate.wallet]];
const real = [];
for (const [txId, tx] of Object.entries(outputs)) {
  for (const o of tx.outputs) {
    for (const [owner, keys] of keyring) {
      const d = await ootle.tryDecryptUtxo(keys.viewSk, o);
      if (d) real.push({ tx_id: txId, owner, view_sk: hex(keys.viewSk), ...o, value_ut: d.value.toString(), memo: d.memo });
    }
  }
}
const find = (owner, value) => real.find((r) => r.owner === owner && r.value_ut === value);
const wallet2m = find('gate wallet', '2000000');
const change = find('gate wallet', '1969000');
const lockerOutputs = real.filter((r) => r.owner === 'gate locker');
const crafted = [
  { name: 'value claim: commitment of 2,000,000 with the payload of 1,969,000 (same view key)',
    view_sk: wallet2m.view_sk, id: wallet2m.id, nonce: change.nonce, enc: change.enc },
  { name: 'swap: one locker output\'s commitment with another\'s payload',
    view_sk: lockerOutputs[0].view_sk, id: lockerOutputs[0].id, nonce: lockerOutputs[1].nonce, enc: lockerOutputs[1].enc },
  { name: 'commitment one bit off',
    view_sk: change.view_sk, id: change.id.slice(0, -1) + (change.id.endsWith('0') ? '1' : '0'), nonce: change.nonce, enc: change.enc },
];

const wrapV2 = {
  _about: 'mutis address wraps v2 (spec §4.9-4.10) and real Esmeralda outputs. Generated by generate.mjs. Hex unless b64u.',
  locker_seed: hex(SEED),
  locker: { owner_sk: hex(id.locker.ownerSk), view_sk: hex(id.locker.viewSk), owner_pk: hex(id.locker.ownerPk), view_pk: hex(id.locker.viewPk), address: id.locker.address },
  safety_code: id.safetyCode,
  inner: { share_id_b64u: b64uEncode(seq(0x10, 16)), s: hex(S), flags: 1, ref: hex(id.dropTag(0)), bytes: hex(inner) },
  r: hex(R_SCALAR),
  iv: hex(seq(0xf0, 12)),
  kind3: { blob: hex(blob3), memos: Object.fromEntries(ORIGINS.map((o) => [o, memoFor(o, 3, blob3)])) },
  kind4: { blob: hex(blob4), memos: Object.fromEntries(ORIGINS.map((o) => [o, memoFor(o, 4, blob4)])) },
  memo_bytes: Object.fromEntries(ORIGINS.map((o) => [o, utf8(memoFor(o, 3, blob3)).length])),
  real_outputs: real,
  crafted,
};

const selftest = {
  _about: 'Sidecar G4 self-test: real outputs that must open and forgeries that must be rejected (subset of tests/vectors/wrap-v2.json).',
  known_good: [find('research browser identity (03 §9 T8)', '1000'), wallet2m, lockerOutputs[0]]
    .map(({ id: i, nonce, enc, view_sk: v, value_ut: value }) => ({ id: i, nonce, enc, view_sk: v, value_ut: value })),
  crafted,
};

const write = (rel, obj) => writeFileSync(new URL(rel, here), JSON.stringify(obj, null, 1) + '\n');
write('format-v1.json', formatV1);
write('wrap-v2.json', wrapV2);
write('../../sidecar/selftest.json', selftest);
console.log(`format-v1: ${hkdfRows.length} HKDF rows, ${powCases.length} PoW cases; wrap-v2: ${real.length} real outputs, ${crafted.length} crafted`);
