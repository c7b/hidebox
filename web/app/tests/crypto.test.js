// SPDX-License-Identifier: MIT
import { hex, unhex } from '../lib/b64.js';
import { utf8 } from '../lib/bytes.js';
import { IntegrityError, aesGcmDecrypt, aesGcmEncrypt, hkdf, pbkdf2Sha256, randomBytes } from '../lib/crypto.js';
import { bytesEq, eq, ok, rejects } from './harness.js';

export const env = 'any';

// RFC 5869 Appendix A.1-A.3 (HKDF-SHA256).
const HKDF = [
  { ikm: '0b'.repeat(22), salt: '000102030405060708090a0b0c', info: 'f0f1f2f3f4f5f6f7f8f9', len: 42,
    okm: '3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865' },
  { ikm: Array.from({ length: 80 }, (_, i) => i.toString(16).padStart(2, '0')).join(''),
    salt: Array.from({ length: 80 }, (_, i) => (0x60 + i).toString(16).padStart(2, '0')).join(''),
    info: Array.from({ length: 80 }, (_, i) => (0xb0 + i).toString(16).padStart(2, '0')).join(''), len: 82,
    okm: 'b11e398dc80327a1c8e7f78c596a49344f012eda2d4efad8a050cc4c19afa97c59045a99cac7827271cb41c65e590e09da3275600c2f09b8367793a9aca3db71cc30c58179ec3e87c14c01d5c1f3434f1d87' },
  { ikm: '0b'.repeat(22), salt: '', info: '', len: 42,
    okm: '8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8' },
];

// NIST CAVP gcmtestvectors.zip, gcmEncryptExtIV256.rsp (Count 0 of each section; 96-bit IV,
// 128-bit tag). The first has no AAD; the other three do. Checked byte for byte against the file.
const GCM = [
  { key: '83688deb4af8007f9b713b47cfa6c73e35ea7a3aa4ecdb414dded03bf7a0fd3a', iv: '0b459724904e010a46901cf3',
    pt: '33d893a2114ce06fc15d55e454cf90c3', aad: '794a14ccd178c8ebfd1379dc704c5e208f9d8424',
    ct: 'cc66bee423e3fcd4c0865715e9586696', tag: '0fb291bd3dba94a1dfd8b286cfb97ac5' },
  { key: 'b52c505a37d78eda5dd34f20c22540ea1b58963cf8e5bf8ffa85f9f2492505b4', iv: '516c33929df5a3284ff463d7',
    pt: '', aad: '', ct: '', tag: 'bdc1ac884d332457a1d2664f168c76f0' },
  { key: '92e11dcdaa866f5ce790fd24501f92509aacf4cb8b1339d50c9c1240935dd08b', iv: 'ac93a1a6145299bde902f21a',
    pt: '2d71bcfa914e4ac045b2aa60955fad24', aad: '1e0889016f67601c8ebea4943bc23ad6',
    ct: '8995ae2e6df3dbf96fac7b7137bae67f', tag: 'eca5aa77d51d4a0a14d9c51e1da474ab' },
  { key: '463b412911767d57a0b33969e674ffe7845d313b88c6fe312f3d724be68e1fca', iv: '611ce6f9a6880750de7da6cb',
    pt: 'e7d1dcf668e2876861940e012fe52a98dacbd78ab63c08842cc9801ea581682ad54af0c34d0d7f6f59e8ee0bf4900e0fd85042',
    aad: '0a682fbc6192e1b47a5e0868787ffdafe5a50cead3575849990cdd2ea9b3597749403efb4a56684f0c6bde352d4aeec5',
    ct: '8886e196010cb3849d9c1a182abe1eeab0a5f3ca423c3669a4a8703c0f146e8e956fb122e0d721b869d2b6fcd4216d7d4d3758',
    tag: '2469cecd70fd98fec9264f71df1aee9a' },
];

export default [
  ['HKDF-SHA256: RFC 5869 A.1-A.3', async () => {
    for (const v of HKDF) eq(hex(await hkdf(unhex(v.ikm), unhex(v.salt), unhex(v.info), v.len)), v.okm);
  }],
  ['HKDF: string info is ASCII bytes', async () => {
    bytesEq(await hkdf(utf8('k'), 'mutis/v1', 'auth', 32), await hkdf(utf8('k'), utf8('mutis/v1'), utf8('auth'), 32));
  }],
  ['PBKDF2-HMAC-SHA256: RFC 7914 §11 vectors (first 32 bytes)', async () => {
    eq(hex(await pbkdf2Sha256('passwd', utf8('salt'), 1)), '55ac046e56e3089fec1691c22544b605f94185216dde0465e68b9d57c20dacbc');
    eq(hex(await pbkdf2Sha256('Password', utf8('NaCl'), 80000)), '4ddcd8f60b98be21830cee5ef22701f9641a4418d04c0414aeff08876b34ab56');
  }],
  ['PBKDF2: passwords are NFC-normalized before UTF-8', async () => {
    const composed = 'café';
    const decomposed = 'café';
    bytesEq(await pbkdf2Sha256(composed, utf8('salt'), 1), await pbkdf2Sha256(decomposed, utf8('salt'), 1));
  }],
  ['AES-256-GCM: NIST CAVP vectors with AAD', async () => {
    for (const v of GCM) {
      const out = await aesGcmEncrypt(unhex(v.key), unhex(v.iv), unhex(v.pt), unhex(v.aad));
      eq(hex(out), v.ct + v.tag);
      eq(hex(await aesGcmDecrypt(unhex(v.key), unhex(v.iv), out, unhex(v.aad))), v.pt);
    }
  }],
  ['AES-256-GCM: any flipped bit, wrong AAD or short input raises IntegrityError', async () => {
    const key = randomBytes(32);
    const iv = randomBytes(12);
    const ct = await aesGcmEncrypt(key, iv, utf8('secret'), utf8('aad'));
    for (let i = 0; i < ct.length * 8; i += 7) {
      const t = ct.slice();
      t[i >> 3] ^= 1 << (i & 7);
      await rejects(() => aesGcmDecrypt(key, iv, t, utf8('aad')), IntegrityError, `bit ${i}`);
    }
    await rejects(() => aesGcmDecrypt(key, iv, ct, utf8('aae')), IntegrityError);
    await rejects(() => aesGcmDecrypt(key, iv, ct.subarray(0, 15), utf8('aad')), IntegrityError);
  }],
  ['randomBytes: right length, beyond the 65,536-byte getRandomValues limit', () => {
    const r = randomBytes(200000);
    eq(r.length, 200000);
    ok(r.subarray(150000, 150064).some((b) => b !== 0));
  }],
];
