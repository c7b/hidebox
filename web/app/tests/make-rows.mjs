// SPDX-License-Identifier: MIT
// Prints `count` mirror rows ({id, nonce, enc}) of genuine stealth outputs to a random address, made
// offline with the official library, for the sidecar scan benchmark:  node make-rows.mjs 3000
import { readFileSync } from 'node:fs';
import { hex } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { NETWORK_BYTE, TARI_RESOURCE, bindings, initWithBytes, newRandomKeys } from '../lib/ootle.js';

await initWithBytes(readFileSync(new URL('../vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm', import.meta.url)));
const count = Number(process.argv[2] ?? 2000);
const w = bindings();
const keys = await newRandomKeys();
const rows = [];
for (let i = 0; i < count; i++) {
  const memo = i % 3 === 0 ? JSON.stringify({ Message: `https://mutis.sh/t#3${'A'.repeat(167)}` }) : null;
  const wit = JSON.parse(w.createStealthOutputWitness(NETWORK_BYTE, keys.ownerPk, keys.viewPk, BigInt(1000 + i), TARI_RESOURCE, null, memo, null, 0n));
  // The commitment only feeds the AEAD key here: a scanner that isn't the recipient fails at the AEAD.
  rows.push({ id: `utxo_${'01'.repeat(32)}_${hex(randomBytes(32))}`, nonce: wit.witness.sender_public_nonce, enc: wit.witness.encrypted_data });
}
process.stdout.write(JSON.stringify(rows));
