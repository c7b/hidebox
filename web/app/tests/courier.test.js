// SPDX-License-Identifier: MIT
import { b64uEncode, hex, unhex } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { utf8 } from '../lib/bytes.js';
import { decodeInner, encodeInner, memoFor, memoPlainText, parseMemo, unconfirmed } from '../lib/courier.js';
import { bytesEq, eq, loadJson, ok, rejects } from './harness.js';

export const env = 'any';

const ORIGINS = ['https://mutis.sh', 'https://srv2052606.hstgr.cloud'];

export default [
  ['inner payload: share_id(16) ‖ s(32) ‖ flags(1) ‖ ref(16), matching the vector', async () => {
    const w = await loadJson('vectors/wrap-v2.json');
    const d = decodeInner(unhex(w.inner.bytes));
    eq(d.shareId, w.inner.share_id_b64u);
    eq(hex(d.s), w.inner.s);
    eq(d.flags, 1);
    ok(d.isDeadDrop);
    eq(hex(d.ref16), w.inner.ref);
    bytesEq(encodeInner(d), unhex(w.inner.bytes));
    const send = decodeInner(encodeInner({ shareId16: randomBytes(16), s: randomBytes(32) }));
    eq(send.flags, 0);
    eq(hex(send.ref16), '00'.repeat(16), 'a send names nobody');
    await rejects(async () => encodeInner({ shareId16: randomBytes(15), s: randomBytes(32) }), TypeError);
  }],
  ['memo: {origin}/t#{kind}{167 chars}; 187 bytes on mutis.sh, 201 on the current host, under 253', async () => {
    const w = await loadJson('vectors/wrap-v2.json');
    for (const kind of [3, 4]) {
      for (const origin of ORIGINS) eq(memoFor(origin, kind, unhex(w[`kind${kind}`].blob)), w[`kind${kind}`].memos[origin]);
    }
    eq(utf8(w.kind3.memos['https://mutis.sh']).length, 187);
    ok(utf8(w.kind3.memos['https://srv2052606.hstgr.cloud']).length <= 253);
    await rejects(async () => memoFor('https://mutis.sh', 1, randomBytes(125)), TypeError);
    await rejects(async () => memoFor('https://mutis.sh', 3, randomBytes(124)), TypeError);
  }],
  ['parseMemo: only exact /t links on allowed origins are deliveries', async () => {
    const blob = randomBytes(125);
    const good = memoFor('https://mutis.sh', 3, blob);
    const p = parseMemo({ Message: good }, ORIGINS);
    eq(p.kind, 3);
    eq(p.origin, 'https://mutis.sh');
    bytesEq(p.blob, blob);
    eq(parseMemo({ Message: memoFor('https://srv2052606.hstgr.cloud', 4, blob) }, ORIGINS).kind, 4);
    const tail = b64uEncode(blob);
    const plainHttp = `https://mutis.sh/t#3${tail}`.replace('https:', 'http:'); // a literal http URL fails the build lint
    for (const bad of [
      `https://evil.example/t#3${tail}`, plainHttp, `https://mutis.sh.evil.example/t#3${tail}`,
      `https://mutisXsh/t#3${tail}`, `https://mutis.sh/t#5${tail}`, `https://mutis.sh/t#3${tail}A`, `https://mutis.sh/t#3${tail.slice(1)}`,
      `https://mutis.sh/s/x#3${tail}`, ` https://mutis.sh/t#3${tail}`, `https://mutis.sh/t#3${tail}\n`,
    ]) eq(parseMemo({ Message: bad }, ORIGINS), null, bad.slice(0, 40));
    eq(parseMemo({ Bytes: 'ab' }, ORIGINS), null);
    eq(parseMemo(null, ORIGINS), null);
    eq(parseMemo({ Message: good }, []), null, 'no allowed origins');
    const staging = memoFor('https://staging.mutis.test:8443', 3, blob);
    eq(parseMemo({ Message: staging }, ['https://staging.mutis.test:8443']).origin, 'https://staging.mutis.test:8443', 'an origin with a port');
    eq(parseMemo({ Message: staging }, ['https://staging.mutis.test']), null, 'the port is part of the origin');
    eq(parseMemo({ Message: good }, ['https://mutis.sh:99999999']), null, 'a malformed allowed origin is ignored');
  }],
  ['unconfirmed: a job whose payment may still go out (walletd took it, or nobody heard back) is not a failure', () => {
    ok(unconfirmed({ state: 'timeout', error: null }), 'our wait ran out');
    for (const error of ['walletd_timeout', 'timeout', 'interrupted']) ok(unconfirmed({ state: 'failed', error }), error);
    for (const error of ['walletd_unreachable', 'walletd_error', 'rejected', 'budget_exhausted', 'invalid_payload', 'sidecar_error', 'internal']) {
      ok(!unconfirmed({ state: 'failed', error }), error);
    }
    ok(!unconfirmed({ state: 'done', error: null }));
  }],
  ['memoPlainText: messages and pay-refs as text; nothing else', () => {
    eq(memoPlainText({ Message: 'thanks for the tip' }), 'thanks for the tip');
    eq(memoPlainText({ PayRefAndBytes: '06696e765f5432' + hex(utf8('hello')) }), 'inv_T2 hello');
    eq(memoPlainText({ PayRefAndBytes: '0a696e765f454d42454431' }), 'inv_EMBED1');
    eq(memoPlainText({ U256: '00' }), null);
    eq(memoPlainText(null), null);
  }],
];
