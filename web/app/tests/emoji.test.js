// SPDX-License-Identifier: MIT
import { hex, unhex } from '../lib/b64.js';
import { utf8 } from '../lib/bytes.js';
import { sha256 } from '../lib/crypto.js';
import { ALPHABET, safetyCode } from '../lib/emoji.js';
import { deepEq, eq, loadJson, ok } from './harness.js';

export const env = 'any';

export default [
  ['alphabet: 256 unique single code points, identical to tari v6.1.0 emoji.rs', async () => {
    eq(ALPHABET.length, 256);
    eq(new Set(ALPHABET).size, 256);
    ok(ALPHABET.every((e) => Array.from(e).length === 1), 'one code point each (no variation selectors)');
    eq(hex(await sha256(utf8(ALPHABET.join('')))), '993865fde3ad66a36b51811eca899c55f7d8ebd4070352f5d34d4a38627f2c1f');
  }],
  ['alphabet spot checks (spec §4.8.3 and 02 Appendix A)', () => {
    const at = { 0: '🐢', 64: '🎃', 116: '🙈', 167: '👻', 179: '💎', 182: '🔒', 183: '🧩', 199: '📜', 211: '🔑', 222: '🔮' };
    for (const [i, e] of Object.entries(at)) eq(ALPHABET[i], e, `index ${i}`);
  }],
  ['safety code: 12 emoji (96 bits) and 6 hex groups, from the vector locker', async () => {
    const w = await loadJson('vectors/wrap-v2.json');
    const code = await safetyCode(unhex(w.locker.owner_pk), unhex(w.locker.view_pk));
    deepEq(code, w.safety_code);
    eq(code.emoji.length, 12);
    ok(/^([0-9a-f]{4} ){5}[0-9a-f]{4}$/.test(code.hex), code.hex);
  }],
];
