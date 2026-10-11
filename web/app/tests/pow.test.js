// SPDX-License-Identifier: MIT
import { b64uDecode } from '../lib/b64.js';
import { concat } from '../lib/bytes.js';
import { randomBytes } from '../lib/crypto.js';
import { sha256Sync } from '../lib/sha256sync.js';
import { difficultyOf, leadingZeroBits, searchNonce } from '../lib/pow.js';
import { hex } from '../lib/b64.js';
import { eq, loadJson, loadOptionalJson, ok, rejects } from './harness.js';

export const env = 'any';

export default [
  ['PoW vectors: the search finds the recorded nonces; verdicts match', async () => {
    const v = await loadJson('vectors/format-v1.json');
    for (const c of v.pow) {
      const challenge = b64uDecode(c.challenge);
      eq(difficultyOf(challenge), c.difficulty);
      const lz = leadingZeroBits(sha256Sync(concat(challenge, b64uDecode(c.nonce))));
      eq(lz, c.leading_zero_bits);
      eq(lz >= c.difficulty, c.valid);
      if (c.valid) eq(searchNonce(challenge, c.difficulty, 0, 1 << 24).join(','), b64uDecode(c.nonce).join(','));
    }
  }],
  ['PoW: the server builder\'s pow.json cases agree (challenge layout, digest, zero bits), when present', async () => {
    const v = await loadOptionalJson('../../../server/tests/vectors/pow.json');
    if (!v) return;
    for (const c of v.cases) {
      const challenge = b64uDecode(c.challenge);
      eq(difficultyOf(challenge), c.difficulty);
      const digest = sha256Sync(concat(challenge, b64uDecode(c.nonce)));
      eq(hex(digest), c.digest);
      eq(leadingZeroBits(digest), c.leading_zero_bits);
      ok(c.leading_zero_bits >= c.difficulty, 'solves');
    }
    // Its "invalid" cases hinge on the server's HMAC, which only the server can check.
  }],
  ['PoW: every nonce found for random challenges meets its difficulty (checked with sha256Sync)', () => {
    for (let i = 0; i < 20; i++) {
      const challenge = concat(Uint8Array.of(1, 1, 10, 0), randomBytes(32));
      const start = Math.floor(Math.random() * 2 ** 40);
      const nonce = searchNonce(challenge, 10, start, 1 << 20);
      ok(nonce, 'found');
      ok(leadingZeroBits(sha256Sync(concat(challenge, nonce))) >= 10, `case ${i}`);
    }
  }],
  ['PoW: counter carries from the low to the high word', () => {
    const challenge = concat(Uint8Array.of(1, 1, 0, 0), randomBytes(32));
    eq(searchNonce(challenge, 0, 2 ** 32 - 1, 1).join(','), '0,0,0,0,255,255,255,255');
    eq(searchNonce(challenge, 0, 2 ** 32, 1).join(','), '0,0,0,1,0,0,0,0');
  }],
  ['PoW: leading-zero counting and challenge checks', async () => {
    eq(leadingZeroBits(Uint8Array.of(0, 0, 0x10)), 19);
    eq(leadingZeroBits(Uint8Array.of(0x80)), 0);
    eq(leadingZeroBits(new Uint8Array(4)), 32);
    await rejects(async () => difficultyOf(new Uint8Array(35)), TypeError);
    await rejects(async () => searchNonce(new Uint8Array(36), 33, 0, 1), RangeError);
  }],
];
