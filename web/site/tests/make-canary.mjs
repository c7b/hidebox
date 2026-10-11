// SPDX-License-Identifier: MIT
// Test fixture: two canaries sealed with the app's real format code (web/app/lib), the newer one
// still secret and the older one with its key published, as GET /api/v1/canary returns them.
// Run once with Node 20: node web/site/tests/make-canary.mjs  (writes tests/fixtures/canary*)
import { writeFileSync } from 'node:fs';
import { b64uEncode } from '../../app/lib/b64.js';
import { randomBytes, sha256 } from '../../app/lib/crypto.js';
import { concat, utf8 } from '../../app/lib/bytes.js';
import { deriveItemKeys, encryptFile, encryptMeta } from '../../app/lib/format.js';

const dir = new URL('./fixtures/', import.meta.url);
const SEALED_AT = 1760000400;

async function seal(n, sealedAt) {
  const head = `mutis canary #${n}. Sealed ${new Date(sealedAt * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z')}. `
    + 'If you can read this without the key, we failed. Drop a file. Mutis.\n';
  const alphabet = 'abcdefghijklmnopqrstuvwxyz234567';
  const text = head + Array.from(randomBytes(4000 - head.length), (b) => alphabet[b & 31]).join('');
  const plain = utf8(text);
  const fk = randomBytes(32);
  const chunks = [];
  let first;
  for await (const part of encryptFile(plain, { fk })) {
    if (!first) first = part;
    else chunks.push(part);
  }
  const { metaKey } = await deriveItemKeys(fk, first.salt);
  const metaCt = await encryptMeta(metaKey, first.headerHash, { kind: 'text', size: plain.length });
  const raw = concat(...chunks.map((c) => c.ciphertext));
  return {
    n, sealed_at: sealedAt, size_stored: raw.length, header: b64uEncode(first.header), meta_ct: b64uEncode(metaCt),
    ct_hash: b64uEncode(await sha256(concat(...chunks.map((c) => c.sha256)))), fk: b64uEncode(fk), raw,
  };
}

const current = await seal(812, SEALED_AT);
const old = await seal(788, SEALED_AT - 24 * 3600);
writeFileSync(new URL('canary-812.bin', dir), current.raw);
writeFileSync(new URL('canary-788.bin', dir), old.raw);
const canary = {
  n: current.n, sealed_at: current.sealed_at, size_stored: current.size_stored, header: current.header,
  meta_ct: current.meta_ct, ct_hash: current.ct_hash, raw: '/api/v1/canary/raw',
  delivery_tx: '45f03981238907134d321e8f6ada288c18d3a5e8745d8f4f8fd28bee856c3d1a',
  revealed: [{ n: old.n, sealed_at: old.sealed_at, raw: `/api/v1/canary/raw?n=${old.n}`, fk: old.fk,
    header: old.header, meta_ct: old.meta_ct, size_stored: old.size_stored }],
};
writeFileSync(new URL('canary.json', dir), JSON.stringify(canary, null, 1) + '\n');
console.log(`canary #${current.n}: ${current.size_stored} bytes; #${old.n} revealed`);
