// SPDX-License-Identifier: MIT
import { b64uDecode, b64uEncode, hex, unhex } from '../lib/b64.js';
import { concat } from '../lib/bytes.js';
import { IntegrityError, randomBytes, sha256 } from '../lib/crypto.js';
import {
  CHUNK_SIZE, chunkRange, ctHash, decryptBlob, decryptChunk, decryptMeta, deriveItemKeys, encryptFile, encryptMeta,
  makeHeader, padme, parseHeader,
} from '../lib/format.js';
import { unwrapFileKey, shareKeys } from '../lib/share.js';
import { bytesEq, deepEq, eq, loadJson, ok, rejects } from './harness.js';

export const env = 'any';

const MiB = 1024 * 1024;

// Seal `plain` the way the client does and keep everything a reader would get from the server.
async function seal(plain) {
  const fk = randomBytes(32);
  const parts = [];
  let first;
  for await (const c of encryptFile(plain, { fk })) {
    if (!first) first = c;
    else parts.push(c);
  }
  const { contentKey, metaKey } = await deriveItemKeys(fk, first.salt);
  const metaCt = await encryptMeta(metaKey, first.headerHash, { kind: 'file', name: 'x.bin', type: 'application/octet-stream', size: plain.length });
  return { ...first, blob: concat(...parts.map((p) => p.ciphertext)), contentKey, metaKey, metaCt, hashes: parts.map((p) => p.sha256) };
}

async function open(s, { blob = s.blob, headerHash = s.headerHash, chunkCount = s.chunkCount, sizeStored = s.sizeStored, plainLength } = {}) {
  const meta = await decryptMeta(s.metaKey, headerHash, s.metaCt);
  return decryptBlob({
    contentKey: s.contentKey, headerHash, chunkCount, sizeStored, plainLength: plainLength ?? meta.size,
    readChunk: async (i, start, end) => blob.subarray(start, end),
  });
}

const plaintextOf = (n) => Uint8Array.from({ length: n }, (_, i) => (i * 31 + (i >> 9)) & 255);

export default [
  ['Padmé: spec §4.4.2 examples and edge sizes', async () => {
    const v = await loadJson('vectors/format-v1.json');
    for (const [n, lp] of v.padme) eq(padme(n), lp, `padme(${n})`);
    eq(padme(1000000), 1015808);
    eq(padme(5000000), 5111808);
    eq(padme(4097), 4352);
    for (let n = 1025; n < 3 * MiB; n += 997) ok(padme(n) >= n && padme(n) <= n * 1.12, `overhead at ${n}`);
  }],
  ['header: frozen bytes, parse round trip, every malformed field is an IntegrityError', async () => {
    const v = await loadJson('vectors/format-v1.json');
    const h = makeHeader({ chunkCount: v.header.chunk_count, salt: unhex(v.header.salt) });
    eq(hex(h), v.header.bytes);
    eq(hex(await sha256(h)), v.header.sha256);
    const p = parseHeader(h);
    eq(p.chunkCount, 3);
    eq(p.chunkLog2, 22);
    bytesEq(p.salt, unhex(v.header.salt));
    for (const [at, value] of [[0, 0x4e], [4, 2], [5, 21], [6, 1], [7, 1], [8, 0], [11, 0], [12, 1], [15, 1]]) {
      const bad = h.slice();
      if (at === 8) bad.set([0, 0, 0, 0], 8);
      else bad[at] = value;
      await rejects(() => parseHeader(bad), IntegrityError, `byte ${at}`);
    }
    await rejects(() => parseHeader(h.subarray(0, 31)), IntegrityError);
  }],
  ['format v1 frozen vector: ciphertext, chunk hashes, ct_hash, metadata and wrapped key', async () => {
    const f = (await loadJson('vectors/format-v1.json')).file;
    const plain = Uint8Array.from({ length: 5000 }, (_, i) => i % 251);
    const chunks = [];
    let first;
    for await (const c of encryptFile(plain, { fk: unhex(f.fk), salt: unhex(f.salt) })) {
      if (!first) first = c;
      else chunks.push(c);
    }
    eq(hex(first.header), f.header);
    eq(first.sizeStored, f.size_stored);
    eq(b64uEncode(concat(...chunks.map((c) => c.ciphertext))), f.ciphertext_b64u);
    deepEq(chunks.map((c) => b64uEncode(c.sha256)), f.chunk_sha256_b64u);
    eq(b64uEncode(await ctHash(chunks.map((c) => c.sha256))), f.ct_hash_b64u);
    const { metaKey } = await deriveItemKeys(unhex(f.fk), unhex(f.salt));
    eq(b64uEncode(await encryptMeta(metaKey, first.headerHash, f.meta, { iv: unhex(f.meta_iv) })), f.meta_ct_b64u);
    deepEq(await decryptMeta(metaKey, first.headerHash, b64uDecode(f.meta_ct_b64u)), f.meta);
    const { wrapKey } = await shareKeys(unhex(f.link_secret));
    eq(hex(await unwrapFileKey(wrapKey, first.headerHash, b64uDecode(f.wrapped_key_b64u))), f.fk);
  }],
  ['metadata: padded to 256-byte blocks; name and type truncated on a code point boundary', async () => {
    const key = randomBytes(32);
    const hh = randomBytes(32);
    const long = '🔒'.repeat(100);
    const ct = await encryptMeta(key, hh, { kind: 'file', name: long, type: 'a/' + 'b'.repeat(300), size: 7 });
    eq((ct.length - 28) % 256, 0, 'block padding');
    const m = await decryptMeta(key, hh, ct);
    ok(new TextEncoder().encode(m.name).length <= 255 && m.name === '🔒'.repeat(63), 'name cut at 252 bytes, whole emoji');
    eq(new TextEncoder().encode(m.type).length, 127);
    const text = await decryptMeta(key, hh, await encryptMeta(key, hh, { kind: 'text', name: 'ignored', size: 3 }));
    eq(text.name, '');
    eq(text.type, 'text/plain;charset=utf-8');
    const worst = await encryptMeta(key, hh, { kind: 'file', name: '"\\\u0001'.repeat(100), type: '"'.repeat(200), size: 1 });
    eq((await decryptMeta(key, hh, worst)).name, '"\\'.repeat(100), 'control characters dropped, quotes and backslashes kept');
    await rejects(() => decryptMeta(key, hh, ct.subarray(0, ct.length - 1)), IntegrityError, 'bad length');
    await rejects(() => decryptMeta(key, randomBytes(32), ct), IntegrityError, 'other header');
  }],
  ['A-02 round trips: 0, 1, 1023, 1024, 1025, 4 MiB-1, 4 MiB, 4 MiB+1, 10 MiB, 25 MiB', async () => {
    for (const n of [0, 1, 1023, 1024, 1025, 4 * MiB - 1, 4 * MiB, 4 * MiB + 1, 10 * MiB, 25 * MiB]) {
      const plain = plaintextOf(n);
      const s = await seal(plain);
      eq(s.blob.length, s.sizeStored, `stored size ${n}`);
      const parts = await open(s);
      const got = concat(...parts);
      eq(got.length, n, `length ${n}`);
      ok(hex(await sha256(got)) === hex(await sha256(plain)), `content ${n}`);
    }
  }],
  ['A-02 tampering: flipped bit in any chunk, swapped chunks, dropped last chunk, edited header, edited meta, wrong final flag', async () => {
    const s = await seal(plaintextOf(10 * MiB));
    eq(s.chunkCount, 3);
    for (let i = 0; i < 3; i++) {
      const { start } = chunkRange(i, 3, s.sizeStored);
      const bad = s.blob.slice();
      bad[start + 100] ^= 1;
      await rejects(() => open(s, { blob: bad }), IntegrityError, `bit in chunk ${i}`);
    }
    const r0 = chunkRange(0, 3, s.sizeStored);
    const r1 = chunkRange(1, 3, s.sizeStored);
    const swapped = concat(s.blob.subarray(r1.start, r1.end), s.blob.subarray(r0.start, r0.end), s.blob.subarray(r1.end));
    await rejects(() => open(s, { blob: swapped }), IntegrityError, 'swapped chunks');
    const r2 = chunkRange(2, 3, s.sizeStored);
    const dropped = s.blob.subarray(0, r2.start);
    await rejects(() => open(s, { blob: dropped, sizeStored: dropped.length }), IntegrityError, 'last chunk dropped, size adjusted');
    await rejects(() => open(s, { blob: dropped, chunkCount: 2, sizeStored: dropped.length }), IntegrityError, 'last chunk dropped, count adjusted');
    await rejects(() => open(s, { blob: dropped }), IntegrityError, 'last chunk missing');
    const header = s.header.slice();
    header[20] ^= 1;
    const editedHash = await sha256(header);
    await rejects(() => open(s, { headerHash: editedHash }), IntegrityError, 'edited header');
    const meta = s.metaCt.slice();
    meta[40] ^= 1;
    await rejects(() => decryptMeta(s.metaKey, s.headerHash, meta), IntegrityError, 'edited meta');
    await rejects(() => decryptChunk(s.contentKey, s.headerHash, 2, false, s.blob.subarray(r2.start)), IntegrityError, 'final chunk as non-final');
    await rejects(() => decryptChunk(s.contentKey, s.headerHash, 0, true, s.blob.subarray(r0.start, r0.end)), IntegrityError, 'first chunk as final');
    await rejects(() => open(s, { plainLength: 10 * MiB + 1 }), IntegrityError, 'length lie');
  }],
  ['A-02: a failure releases no plaintext (decryptBlob resolves only when every chunk verified)', async () => {
    const s = await seal(plaintextOf(9 * MiB));
    const bad = s.blob.slice();
    bad[bad.length - 5] ^= 0x80;
    let released = null;
    await rejects(async () => { released = await open(s, { blob: bad }); }, IntegrityError);
    eq(released, null);
  }],
  ['chunk ranges: chunk i starts at i * (CS + 16) and the last one ends at size_stored', () => {
    eq(chunkRange(0, 3, 3 * (CHUNK_SIZE + 16)).end, CHUNK_SIZE + 16);
    eq(chunkRange(2, 3, 2 * (CHUNK_SIZE + 16) + 1040).start, 2 * (CHUNK_SIZE + 16));
    eq(chunkRange(2, 3, 2 * (CHUNK_SIZE + 16) + 1040).end, 2 * (CHUNK_SIZE + 16) + 1040);
  }],
];
