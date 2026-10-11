// SPDX-License-Identifier: MIT
import { b64uDecode, b64uEncode, hex, unhex } from '../lib/b64.js';
import { utf8 } from '../lib/bytes.js';
import { bytesEq, eq, ok, rejects } from './harness.js';

export const env = 'any';

// RFC 4648 §10 vectors in the URL-safe alphabet without padding.
const RFC4648 = [['', ''], ['f', 'Zg'], ['fo', 'Zm8'], ['foo', 'Zm9v'], ['foob', 'Zm9vYg'], ['fooba', 'Zm9vYmE'], ['foobar', 'Zm9vYmFy']];

export default [
  ['base64url: RFC 4648 vectors round trip', () => {
    for (const [plain, enc] of RFC4648) {
      eq(b64uEncode(utf8(plain)), enc, plain);
      bytesEq(b64uDecode(enc), utf8(plain), enc);
    }
  }],
  ['base64url: uses - and _ for 62 and 63', () => {
    eq(b64uEncode(Uint8Array.of(0xfb, 0xff)), '-_8');
    bytesEq(b64uDecode('-_8'), Uint8Array.of(0xfb, 0xff));
  }],
  ['base64url: random round trips of every length 0-100', () => {
    for (let n = 0; n <= 100; n++) {
      const b = crypto.getRandomValues(new Uint8Array(n));
      bytesEq(b64uDecode(b64uEncode(b)), b, `length ${n}`);
    }
  }],
  ['base64url: strict decoding (padding, foreign chars, bad length, non-zero tail bits)', async () => {
    for (const bad of ['Zg==', 'Zm9v+', 'Zm9v/', 'Z', 'Zh', 'Zm9w ', 'Zm9vé']) {
      await rejects(() => b64uDecode(bad), TypeError, bad);
    }
  }],
  ['hex round trip, lowercase out, rejects odd length and non-hex', async () => {
    eq(hex(Uint8Array.of(0, 15, 16, 255)), '000f10ff');
    bytesEq(unhex('000F10ff'), Uint8Array.of(0, 15, 16, 255));
    await rejects(() => unhex('abc'), TypeError);
    await rejects(() => unhex('zz'), TypeError);
    ok(unhex('').length === 0);
  }],
];
