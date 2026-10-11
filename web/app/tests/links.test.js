// SPDX-License-Identifier: MIT
import { b64uDecode, b64uEncode, hex, unhex } from '../lib/b64.js';
import { IntegrityError, randomBytes } from '../lib/crypto.js';
import { linkFragment, linkProof, parseFragment, shareKeys, shareUrl, unwrapFileKey, wrapFileKey } from '../lib/share.js';
import { checkPassword, linkPasswordSecret, newKdfParams, passwordOnlySecret } from '../lib/password.js';
import { bytesEq, eq, loadJson, ok, rejects } from './harness.js';

export const env = 'any';

const row = (v, name) => v.hkdf.find((r) => r.name === name).out;

export default [
  ['link keys: wrap key, access token and verifiers match the frozen vectors', async () => {
    const v = await loadJson('vectors/format-v1.json');
    const k = await shareKeys(unhex(v.inputs.s));
    eq(hex(k.wrapKey), row(v, 'wrapKey'));
    eq(b64uEncode(k.accessToken), v.verifiers.access_token_b64u);
    eq(b64uEncode(k.accessVerifier), v.verifiers.access_verifier_b64u);
    const p = await linkProof(unhex(v.inputs.s0));
    eq(b64uEncode(p.proof), v.verifiers.link_proof_b64u);
    eq(b64uEncode(p.verifier), v.verifiers.link_verifier_b64u);
  }],
  ['passwords: link + password and password-only secrets match the vectors', async () => {
    const v = await loadJson('vectors/format-v1.json');
    eq(hex(await linkPasswordSecret(unhex(v.inputs.s0), v.inputs.password, v.inputs.kdf)), row(v, 's (link+password)'));
    eq(hex(await passwordOnlySecret(v.inputs.password, v.inputs.kdf)), row(v, 's (password only)'));
  }],
  ['passwords: refuse weak or unknown KDF parameters from a server', async () => {
    const good = newKdfParams();
    eq(good.iter, 600000);
    eq(b64uDecode(good.salt).length, 16);
    for (const bad of [{ ...good, iter: 599999 }, { ...good, iter: 5000001 }, { ...good, alg: 'PBKDF2-SHA1' }, { ...good, salt: 'AAAA' }, null]) {
      await rejects(() => passwordOnlySecret('long enough pw', bad), TypeError, JSON.stringify(bad));
    }
  }],
  ['passwords: minimum lengths are rules, common and patterned passwords are flagged', () => {
    eq(checkPassword('abc', 'link_password').problem, 'too_short');
    eq(checkPassword('abcd', 'link_password').ok, true);
    eq(checkPassword('short pw', 'password').problem, 'too_short');
    eq(checkPassword('P@ssw0rd2024!', 'password').problem, 'common');
    eq(checkPassword('qwertyuiop', 'password').problem, 'common');
    eq(checkPassword('zzzzzzzzzzzz', 'password').problem, 'pattern');
    eq(checkPassword('0987654321', 'password').problem, 'common');
    eq(checkPassword('lkjhgfdsaqwe', 'password').problem, null);
    eq(checkPassword('correct horse battery staple', 'password').strength, 'strong');
    eq(checkPassword('Tr4ce-ink-lamp', 'password').strength, 'strong');
    eq(checkPassword('quietlamp42', 'password').strength, 'fair');
  }],
  ['file key wrap: 60 bytes, opens only with the same link and header', async () => {
    const fk = randomBytes(32);
    const hh = randomBytes(32);
    const { wrapKey } = await shareKeys(randomBytes(32));
    const w = await wrapFileKey(wrapKey, hh, fk);
    eq(w.length, 60);
    bytesEq(await unwrapFileKey(wrapKey, hh, w), fk);
    await rejects(() => unwrapFileKey(wrapKey, randomBytes(32), w), IntegrityError);
    const otherKey = (await shareKeys(randomBytes(32))).wrapKey;
    await rejects(() => unwrapFileKey(otherKey, hh, w), IntegrityError);
    await rejects(() => unwrapFileKey(wrapKey, hh, w.subarray(1)), IntegrityError);
  }],
  ['fragments: §4.6 table (1/2 = 44 chars, 3/4 = 168 chars), everything else is null', async () => {
    const v = await loadJson('vectors/format-v1.json');
    for (const f of v.fragments) {
      eq(linkFragment(f.kind, unhex(f.secret)), f.fragment);
      const p = parseFragment('#' + f.fragment);
      eq(p.kind, f.kind);
      eq(hex(p.s), f.secret);
    }
    const blob = randomBytes(125);
    const p3 = parseFragment('3' + b64uEncode(blob));
    eq(p3.kind, 3);
    bytesEq(p3.blob, blob);
    eq(parseFragment('4' + b64uEncode(blob)).kind, 4);
    for (const bad of ['', '#', '1', '5' + 'A'.repeat(43), '1' + 'A'.repeat(42), '1' + 'A'.repeat(44), '3' + 'A'.repeat(166), '1' + '+'.repeat(43), 'k=abc']) {
      eq(parseFragment(bad), null, JSON.stringify(bad));
    }
  }],
  ['share URL: {origin}/s/{id}#{fragment}; password-only links have no fragment', () => {
    eq(shareUrl('https://mutis.sh', 'A'.repeat(22), '1abc'), `https://mutis.sh/s/${'A'.repeat(22)}#1abc`);
    eq(shareUrl('https://mutis.sh', 'A'.repeat(22), null), `https://mutis.sh/s/${'A'.repeat(22)}`);
    ok(!shareUrl('https://x', 'id', null).includes('#'));
  }],
];
