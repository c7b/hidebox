// SPDX-License-Identifier: MIT
import { hex } from '../lib/b64.js';
import { utf8 } from '../lib/bytes.js';
import { sha256 } from '../lib/crypto.js';
import { sha256Sync } from '../lib/sha256sync.js';
import { bytesEq, eq } from './harness.js';

export const env = 'any';

// FIPS 180-4 examples (NIST CSRC "SHA256.pdf", "SHA2_Additional.pdf").
const FIPS = [
  ['', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'],
  ['abc', 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'],
  ['abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq', '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1'],
];

export default [
  ['sha256Sync: FIPS 180-4 examples', () => {
    for (const [msg, digest] of FIPS) eq(hex(sha256Sync(utf8(msg))), digest, JSON.stringify(msg));
  }],
  ['sha256Sync: one million "a"', () => {
    eq(hex(sha256Sync(new Uint8Array(1000000).fill(0x61))), 'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0');
  }],
  ['sha256Sync = WebCrypto on 1,000 random inputs of length 0-200', async () => {
    for (let i = 0; i < 1000; i++) {
      const b = crypto.getRandomValues(new Uint8Array(Math.floor(Math.random() * 201)));
      bytesEq(sha256Sync(b), await sha256(b), `input ${i} (${b.length} bytes)`);
    }
  }],
  ['sha256Sync = WebCrypto at every block boundary 50-130', async () => {
    for (let n = 50; n <= 130; n++) {
      const b = crypto.getRandomValues(new Uint8Array(n));
      bytesEq(sha256Sync(b), await sha256(b), `${n} bytes`);
    }
  }],
];
