// SPDX-License-Identifier: MIT
// WebCrypto primitives (browsers and Node 20's global crypto): SHA-256, HKDF-SHA256, AES-256-GCM,
// PBKDF2-SHA256. Every key is a raw Uint8Array at this boundary.
import { utf8 } from './bytes.js';

export class IntegrityError extends Error {
  constructor(message = 'integrity check failed') {
    super(message);
    this.name = 'IntegrityError';
  }
}

const subtle = globalThis.crypto.subtle;

export function randomBytes(n) {
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i += 65536) globalThis.crypto.getRandomValues(out.subarray(i, Math.min(n, i + 65536)));
  return out;
}

export async function sha256(bytes) {
  return new Uint8Array(await subtle.digest('SHA-256', bytes));
}

const asBytes = (v) => (typeof v === 'string' ? utf8(v) : v);

export async function hkdf(ikm, salt, info, length) {
  const key = await subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  const bits = await subtle.deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt: asBytes(salt), info: asBytes(info) },
    key,
    length * 8,
  );
  return new Uint8Array(bits);
}

// A file's chunks share one content key; importing it once per key object saves 1 import per chunk.
const aesKeys = new WeakMap();

async function aesKey(key32) {
  if (key32.length !== 32) throw new TypeError('AES-256 needs a 32-byte key');
  let k = aesKeys.get(key32);
  if (!k) {
    k = await subtle.importKey('raw', key32, 'AES-GCM', false, ['encrypt', 'decrypt']);
    aesKeys.set(key32, k);
  }
  return k;
}

export async function aesGcmEncrypt(key32, iv12, plaintext, aad) {
  const params = { name: 'AES-GCM', iv: iv12, tagLength: 128 };
  if (aad) params.additionalData = aad;
  return new Uint8Array(await subtle.encrypt(params, await aesKey(key32), plaintext));
}

export async function aesGcmDecrypt(key32, iv12, ciphertext, aad) {
  const params = { name: 'AES-GCM', iv: iv12, tagLength: 128 };
  if (aad) params.additionalData = aad;
  const key = await aesKey(key32);
  try {
    return new Uint8Array(await subtle.decrypt(params, key, ciphertext));
  } catch {
    throw new IntegrityError();
  }
}

export async function pbkdf2Sha256(passwordString, salt16, iterations) {
  const key = await subtle.importKey('raw', utf8(passwordString.normalize('NFC')), 'PBKDF2', false, ['deriveBits']);
  const bits = await subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: salt16, iterations }, key, 256);
  return new Uint8Array(bits);
}
