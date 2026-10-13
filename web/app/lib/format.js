// SPDX-License-Identifier: MIT
// File format v1 (§4.4–4.5): a 32-byte clear header, Padmé-padded plaintext cut into 4 MiB chunks,
// each sealed with AES-256-GCM under a STREAM-style nonce (chunk index + final flag) with the header
// hash as AAD, and the metadata (name, type, real size) encrypted separately.
import { concat, readU16be, readU32be, truncateUtf8, u16be, u32be, utf8, fromUtf8 } from './bytes.js';
import { IntegrityError, aesGcmDecrypt, aesGcmEncrypt, hkdf, randomBytes, sha256 } from './crypto.js';

export const CHUNK_SIZE = 4194304;
const CHUNK_LOG2 = 22;
const TAG = 16;
const MAGIC = utf8('MTS1');
const META_BLOCK = 256;
const META_MAX = 2048;

// Padmé (Nikitin et al., PETS 2019): leaks O(log log L) bits of the length, overhead ≤ 12%.
export function padme(length) {
  if (length <= 1024) return 1024;
  const e = length.toString(2).length - 1;
  const s = e.toString(2).length;
  const step = 2 ** (e - s);
  return Math.ceil(length / step) * step;
}

export function chunkCountFor(paddedLength) {
  return Math.max(1, Math.ceil(paddedLength / CHUNK_SIZE));
}

export function sizeStoredFor(plainLength) {
  const lp = padme(plainLength);
  return lp + TAG * chunkCountFor(lp);
}

// Byte range [start, end) of ciphertext chunk `index` inside the stored blob.
export function chunkRange(index, chunkCount, sizeStored) {
  const start = index * (CHUNK_SIZE + TAG);
  const end = index === chunkCount - 1 ? sizeStored : start + CHUNK_SIZE + TAG;
  return { start, end };
}

export function makeHeader({ chunkCount, salt }) {
  if (salt.length !== 16 || !Number.isInteger(chunkCount) || chunkCount < 1) throw new TypeError('bad header fields');
  return concat(MAGIC, Uint8Array.of(1, CHUNK_LOG2, 0, 0), u32be(chunkCount), u32be(0), salt);
}

export function parseHeader(bytes32) {
  const b = bytes32;
  const ok = b.length === 32 && MAGIC.every((m, i) => b[i] === m) && b[4] === 1 && b[5] === CHUNK_LOG2
    && b[6] === 0 && b[7] === 0 && readU32be(b, 12) === 0 && readU32be(b, 8) >= 1;
  if (!ok) throw new IntegrityError('bad header');
  return { version: 1, chunkLog2: CHUNK_LOG2, chunkCount: readU32be(b, 8), salt: b.slice(16, 32) };
}

export async function deriveItemKeys(fk, salt) {
  return {
    contentKey: await hkdf(fk, salt, 'mutis/v1/content', 32),
    metaKey: await hkdf(fk, salt, 'mutis/v1/meta', 32),
  };
}

function chunkIv(index, isFinal) {
  const iv = new Uint8Array(12);
  iv.set(u32be(index), 7);
  iv[11] = isFinal ? 1 : 0;
  return iv;
}

const META_AAD = utf8('meta');

// Control characters are dropped so JSON escaping can't push the record past its 2,048-byte cap.
const clean = (v, max) => truncateUtf8(String(v ?? '').replace(/\p{Cc}/gu, ''), max);

function normalizeMeta(m) {
  if (m.kind !== 'file' && m.kind !== 'text' && m.kind !== 'folder') throw new TypeError('meta.kind must be file, text or folder');
  if (!Number.isSafeInteger(m.size) || m.size < 0) throw new TypeError('meta.size must be a byte count');
  return {
    v: 1,
    kind: m.kind,
    name: m.kind === 'text' ? '' : clean(m.name, 255),
    type: m.kind === 'text' ? 'text/plain;charset=utf-8' : clean(m.type, 127),
    size: m.size,
    mtime: Number.isSafeInteger(m.mtime) ? m.mtime : null,
    stripped: Boolean(m.stripped),
  };
}

// `iv` is fixed only by the frozen test vectors; otherwise it is random.
export async function encryptMeta(metaKey, headerHash, metaObject, { iv = randomBytes(12) } = {}) {
  const json = utf8(JSON.stringify(normalizeMeta(metaObject)));
  const blocks = Math.max(1, Math.ceil((json.length + 2) / META_BLOCK));
  if (blocks * META_BLOCK > META_MAX) throw new TypeError('metadata too large');
  const plain = new Uint8Array(blocks * META_BLOCK);
  plain.set(u16be(json.length));
  plain.set(json, 2);
  return concat(iv, await aesGcmEncrypt(metaKey, iv, plain, concat(headerHash, META_AAD)));
}

export async function decryptMeta(metaKey, headerHash, metaCt) {
  const k = (metaCt.length - 12 - TAG) / META_BLOCK;
  if (!Number.isInteger(k) || k < 1 || k > META_MAX / META_BLOCK) throw new IntegrityError('bad metadata length');
  const plain = await aesGcmDecrypt(metaKey, metaCt.subarray(0, 12), metaCt.subarray(12), concat(headerHash, META_AAD));
  const len = readU16be(plain, 0);
  if (len + 2 > plain.length) throw new IntegrityError('bad metadata');
  try {
    const meta = JSON.parse(fromUtf8(plain.subarray(2, 2 + len)));
    if (meta.v !== 1) throw new TypeError('unknown metadata version');
    return normalizeMeta(meta);
  } catch {
    throw new IntegrityError('bad metadata');
  }
}

async function readRange(source, start, end) {
  if (source instanceof Uint8Array) return source.subarray(start, end);
  return new Uint8Array(await source.slice(start, end).arrayBuffer());
}

// Yields {header, headerHash, chunkCount, sizeStored, salt} first, then {index, ciphertext, sha256}
// per chunk. `salt` and `fromIndex` let an interrupted upload re-create the exact same chunks.
export async function* encryptFile(blobOrBytes, { fk, onProgress, salt = randomBytes(16), fromIndex = 0 }) {
  const length = blobOrBytes instanceof Uint8Array ? blobOrBytes.length : blobOrBytes.size;
  const padded = padme(length);
  const chunkCount = chunkCountFor(padded);
  const header = makeHeader({ chunkCount, salt });
  const headerHash = await sha256(header);
  const { contentKey } = await deriveItemKeys(fk, salt);
  yield { header, headerHash, chunkCount, sizeStored: padded + TAG * chunkCount, salt };
  for (let i = fromIndex; i < chunkCount; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, padded);
    const chunk = new Uint8Array(end - start);
    if (start < length) chunk.set(await readRange(blobOrBytes, start, Math.min(end, length)));
    const ciphertext = await aesGcmEncrypt(contentKey, chunkIv(i, i === chunkCount - 1), chunk, headerHash);
    yield { index: i, ciphertext, sha256: await sha256(ciphertext) };
    onProgress?.(end / padded);
  }
}

export async function decryptChunk(contentKey, headerHash, index, isFinal, ciphertext) {
  return aesGcmDecrypt(contentKey, chunkIv(index, isFinal), ciphertext, headerHash);
}

export async function ctHash(chunkHashes) {
  return sha256(concat(...chunkHashes));
}

// Decrypts a whole stored blob and returns the plaintext as parts, trimmed to `plainLength` (from
// the decrypted metadata). Nothing is returned unless every chunk verified, and the layout must be
// exactly the one the metadata implies, so truncation, extension and reordering all fail.
// `readChunk(index, start, end)` resolves to that chunk's ciphertext; two run in parallel.
export async function decryptBlob({ contentKey, headerHash, chunkCount, sizeStored, plainLength, readChunk, onProgress }) {
  if (chunkCountFor(padme(plainLength)) !== chunkCount || sizeStoredFor(plainLength) !== sizeStored) {
    throw new IntegrityError('size does not match the sealed metadata');
  }
  const parts = new Array(chunkCount);
  let next = 0;
  let done = 0;
  let failed = false;
  async function worker() {
    while (!failed && next < chunkCount) {
      const i = next++;
      try {
        const { start, end } = chunkRange(i, chunkCount, sizeStored);
        const ct = await readChunk(i, start, end);
        if (ct.length !== end - start) throw new IntegrityError('chunk has the wrong length');
        parts[i] = await decryptChunk(contentKey, headerHash, i, i === chunkCount - 1, ct);
      } catch (e) {
        failed = true;
        throw e;
      }
      onProgress?.(++done / chunkCount);
    }
  }
  await Promise.all([worker(), worker()]);
  let remaining = plainLength;
  return parts.map((p) => {
    const take = Math.min(p.length, remaining);
    remaining -= take;
    return p.subarray(0, take);
  }).filter((p) => p.length > 0);
}
