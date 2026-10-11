// SPDX-License-Identifier: MIT
// Links (§4.6): every link has its own 32-byte secret `s`. From it come the key that wraps the file
// key, and the access token the server stores only as a SHA-256. The secret travels after the `#`,
// which browsers never send to servers.
import { b64uDecode, b64uEncode } from './b64.js';
import { IntegrityError, aesGcmDecrypt, aesGcmEncrypt, hkdf, randomBytes, sha256 } from './crypto.js';
import { concat } from './bytes.js';

const SALT = 'mutis/v1';

export function newShareSecret() {
  return randomBytes(32);
}

export async function shareKeys(s) {
  const accessToken = await hkdf(s, SALT, 'share-access', 32);
  return {
    wrapKey: await hkdf(s, SALT, 'share-wrap', 32),
    accessToken,
    accessVerifier: await sha256(accessToken),
  };
}

// Link + password links also prove possession of the link itself, so a wrong-password counter can
// only be advanced by someone who holds the full link.
export async function linkProof(s0) {
  const proof = await hkdf(s0, SALT, 'link-proof', 32);
  return { proof, verifier: await sha256(proof) };
}

// `iv` is fixed only by the frozen test vectors; otherwise it is random.
export async function wrapFileKey(wrapKey, headerHash, fk, { iv = randomBytes(12) } = {}) {
  return concat(iv, await aesGcmEncrypt(wrapKey, iv, fk, headerHash));
}

export async function unwrapFileKey(wrapKey, headerHash, wrapped60) {
  if (wrapped60.length !== 60) throw new IntegrityError('wrapped key must be 60 bytes');
  return aesGcmDecrypt(wrapKey, wrapped60.subarray(0, 12), wrapped60.subarray(12), headerHash);
}

export function linkFragment(kind, s) {
  if ((kind !== 1 && kind !== 2) || s.length !== 32) throw new TypeError('link fragment needs kind 1|2 and 32 bytes');
  return String(kind) + b64uEncode(s);
}

export function parseFragment(hash) {
  const f = String(hash ?? '').replace(/^#/, '');
  const kind = Number(f[0]);
  const body = f.slice(1);
  try {
    if ((kind === 1 || kind === 2) && body.length === 43) return { kind, s: b64uDecode(body) };
    if ((kind === 3 || kind === 4) && body.length === 167) return { kind, blob: b64uDecode(body) };
  } catch {
    return null;
  }
  return null;
}

export function shareUrl(origin, shareId, fragment) {
  return `${origin}/s/${shareId}${fragment ? '#' + fragment : ''}`;
}
