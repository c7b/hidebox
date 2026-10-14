// SPDX-License-Identifier: MIT
// Pay to open's client library (lib/pay.js; 16-drive-architecture §1.3, §1.9), lane app2.
import { b64uDecode, b64uEncode, hex, unhex } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { shareKeys } from '../lib/share.js';
import { claimRef, keepClaim, openTeaser, parsePayFragment, payFragment, paySecret, savedClaim, sealTeaser, sizeBucket } from '../lib/pay.js';
import { oneTimeKey, ready, tryDecryptUtxo } from '../lib/ootle.js';
import { eq, loadJson, ok, rejects } from './harness.js';

export const env = 'any';

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
      eq((await oneTimeKey(unhex(own.owner_sk), row.nonce)) === row.auth_key, ours);
    }
    eq(await oneTimeKey(unhex(own.owner_sk), 'ff'.repeat(32)), null);
    ok(b64uDecode(b64uEncode(unhex(own.owner_sk))).length === 32);
  }],
];
