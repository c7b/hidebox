// SPDX-License-Identifier: MIT
import { b64uEncode, hex, unhex } from '../lib/b64.js';
import { sha256 } from '../lib/crypto.js';
import {
  KeyError, identityFromSeed, keyFileName, keyFileText, lockedKeyFileText, parseRecoveryCode, recoveryCode, restoreFromText,
} from '../lib/identity.js';
import { bytesEq, deepEq, eq, loadJson, ok, rejects } from './harness.js';

export const env = 'any';

const row = (v, name) => v.hkdf.find((r) => r.name === name).out;

export default [
  ['identity from the fixed seed: id, auth verifier, keys, addresses and safety code match the vectors', async () => {
    const v = await loadJson('vectors/format-v1.json');
    const w = await loadJson('vectors/wrap-v2.json');
    const id = await identityFromSeed(unhex(v.identity.seed), { created: v.identity.created });
    eq(id.id, v.identity.identity_id_b64u);
    eq(id.id.length, 22);
    eq(b64uEncode(await sha256(id.authKey)), v.identity.auth_verifier_b64u);
    eq(hex(id.vaultKey), row(v, 'vaultKey'));
    eq(id.locker.address, v.identity.locker_address);
    eq(id.wallet.address, v.identity.wallet_address);
    eq(hex(id.locker.ownerPk), w.locker.owner_pk);
    eq(hex(id.locker.ownerSk), v.scalars_mod_l.find((s) => s.info === 'ootle-owner').reduced);
    eq(hex(id.wallet.viewSk), v.scalars_mod_l.find((s) => s.info === 'wallet-view').reduced);
    deepEq(id.safetyCode, v.identity.safety_code);
    eq(hex(id.dropTag(0)), row(v, 'dropTag(0)'));
    eq(hex(id.dropManage(15)), row(v, 'dropManage(15)'));
    await rejects(async () => id.dropTag(16), RangeError);
  }],
  ['recovery code: Crockford base32 of seed + 2-byte checksum, MUTIS- + 11 groups of 5', async () => {
    const v = await loadJson('vectors/format-v1.json');
    const code = recoveryCode(unhex(v.identity.seed));
    eq(code, v.identity.recovery_code);
    ok(/^MUTIS(-[0-9A-HJKMNP-TV-Z]{5}){11}$/.test(code), 'shape');
    bytesEq(parseRecoveryCode(code), unhex(v.identity.seed));
  }],
  ['recovery code decoding: case, spaces and dashes ignored; O->0, I/L->1; U rejected; typos caught', async () => {
    const seed = crypto.getRandomValues(new Uint8Array(32));
    const code = recoveryCode(seed);
    const groups = code.slice(6);
    bytesEq(parseRecoveryCode(groups.toLowerCase().replace(/-/g, ' ')), seed, 'lowercase with spaces');
    bytesEq(parseRecoveryCode(groups.replace(/-/g, '')), seed, 'no separators');
    bytesEq(parseRecoveryCode(code.replace(/0/g, 'O').replace(/1/g, 'l')), seed, 'O and l');
    bytesEq(parseRecoveryCode(`please keep\n${code}\nthanks`), seed, 'inside other text');
    const pos = 6 + 7;
    const typo = code.slice(0, pos) + (code[pos] === 'A' ? 'B' : 'A') + code.slice(pos + 1);
    await rejects(async () => parseRecoveryCode(typo), (e) => e instanceof KeyError && e.code === 'checksum', 'typo');
    await rejects(async () => parseRecoveryCode(code.slice(0, pos) + 'U' + code.slice(pos + 1)), (e) => e.code === 'no_key', 'U');
    await rejects(async () => parseRecoveryCode('mutis locker key. nothing here'), (e) => e.code === 'no_key');
  }],
  ['key file: exact text and name from the vector (12 emoji in 3 groups); restoring it gives the same locker', async () => {
    const v = await loadJson('vectors/format-v1.json');
    const id = await identityFromSeed(unhex(v.identity.seed), { created: v.identity.created });
    eq(keyFileText(id), v.identity.key_file_text);
    eq(keyFileName(id), v.identity.key_file_name);
    const back = await restoreFromText(keyFileText(id));
    eq(back.id, id.id);
    eq(back.created, '2026-10-14');
    eq(back.createdSeq, null);
    eq(typeof back.storageAvailable, 'boolean');
    ok([true, false, null].includes(back.persisted), 'asked the browser to keep its storage (null: not supported)');
  }],
  ['locked key file (P-15): passphrase required, wrong passphrase refused, right one restores', async () => {
    const seed = crypto.getRandomValues(new Uint8Array(32));
    const id = await identityFromSeed(seed, { created: '2026-10-31' });
    const text = await lockedKeyFileText(id, 'lamp curtain velvet exit');
    ok(!text.includes(recoveryCode(seed)) && !text.includes('Key: MUTIS'), 'no plain code in the file');
    ok(text.includes(id.locker.address), 'address shown');
    await rejects(() => restoreFromText(text), (e) => e.code === 'locked');
    await rejects(() => restoreFromText(text, 'lamp curtain velvet exist'), (e) => e.code === 'wrong_passphrase');
    eq((await restoreFromText(text, 'lamp curtain velvet exit')).id, id.id);
  }],
];
