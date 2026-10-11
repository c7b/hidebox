// SPDX-License-Identifier: MIT
import { NETWORK_BYTE, TARI_RESOURCE, bindings } from '../lib/ootle.js';

// Test helper: a mirror row for a fresh stealth output to `keys`, built offline with the official library.
export function outputTo(keys, value, memo = null) {
  const w = bindings();
  const wit = w.createStealthOutputWitness(NETWORK_BYTE, keys.ownerPk, keys.viewPk, BigInt(value), TARI_RESOURCE, null, memo ? JSON.stringify({ Message: memo }) : null, null, 0n);
  const st = w.generateStealthOutputsStatement(`[${wit}]`, 0n, new Uint8Array(32));
  const out = JSON.parse(st.statement_json).outputs[0].output;
  st.free();
  return { id: `utxo_${'01'.repeat(32)}_${out.commitment}`, nonce: out.sender_public_nonce, enc: out.encrypted_data };
}
