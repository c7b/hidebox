// SPDX-License-Identifier: MIT
// Dedicated Worker for proof of work, so hashing never blocks the page. Reports progress per batch.
import { searchNonce } from './pow.js';

const BATCH = 1 << 14;

self.onmessage = ({ data: { challenge, difficulty, start } }) => {
  for (let tries = 0; ; tries += BATCH) {
    const nonce = searchNonce(challenge, difficulty, start + tries, BATCH);
    if (nonce) {
      self.postMessage({ tries: tries + BATCH, nonce });
      return;
    }
    self.postMessage({ tries: tries + BATCH });
  }
};
