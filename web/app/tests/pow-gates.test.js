// SPDX-License-Identifier: MIT
import { randomBytes } from '../lib/crypto.js';
import { identityFromSeed } from '../lib/identity.js';
import { newRandomKeys } from '../lib/ootle.js';
import { hasJudgePass, prefetchPow, setJudgePass } from '../lib/pow.js';
import { createLink, sealItem } from '../lib/seal.js';
import { accessFor, linkStatus, openItem, peek } from '../lib/open.js';
import { ensureSession } from '../lib/session.js';
import { createDrop, getDrop, leaveInDrop } from '../lib/drop.js';
import { deliver } from '../lib/wallet.js';
import { set } from '../lib/store.js';
import { FAKE_ORIGIN, installFakeApi } from './fake-api.js';
import { eq, ok, rejects } from './harness.js';

export const env = 'any';

const PASS = 'judge-7kq2x9mdh4ab7kq2x9mdh4ab';
const in1h = () => Math.floor(Date.now() / 1000) + 3600;
const header = (r, name) => r.headers.find(([k]) => k === name.toLowerCase())?.[1] ?? null;
const bodyOf = (r) => JSON.parse(new TextDecoder().decode(r.body));
const route = (r) => `${r.method} ${new URL(r.url).pathname.replace('/api/v1', '')}`;

export default [
  ['judge pass (P-12): register, drop, upload and both courier sends skip the PoW and carry the pass; nothing else does', async () => {
    const passes = new Map([[PASS, 5]]);
    const api = installFakeApi({ judgePasses: passes });
    try {
      setJudgePass(`  ${PASS.toUpperCase()} `);
      ok(hasJudgePass());
      set('session', null);
      const me = await identityFromSeed(randomBytes(32));
      await ensureSession(me);
      const drop = await getDrop((await createDrop(me, 'tips')).drop_id);
      const item = await sealItem({ text: 'a tip' }, { anonymous: true, expiresAt: in1h(), dropId: drop.drop_id });
      const link = await createLink(item, { origin: FAKE_ORIGIN, maxViews: 3 });
      await leaveInDrop(drop, link);
      const sent = await deliver(me, { address: (await newRandomKeys()).address, kind: 3, blob: new Uint8Array(125) });
      eq(sent.mode, 'relay');
      ok(!api.state.requests.some((r) => r.url.endsWith('/pow')), 'no PoW was solved');
      eq(api.state.requests.filter((r) => header(r, 'X-Mutis-Judge') === PASS).map(route).join(' | '),
        'POST /auth/register | POST /drops | POST /uploads | POST /courier | POST /courier');
      eq(passes.get(PASS), 3, 'the two budgeted sends used two of its uses');
    } finally {
      setJudgePass(null);
      api.restore();
    }
  }],
  ['judge pass the server calls unknown or used up: dropped, and that request goes again with a PoW', async () => {
    const api = installFakeApi({ judgePasses: new Map([[PASS, 0]]) });
    try {
      setJudgePass(PASS);
      const me = await identityFromSeed(randomBytes(32));
      await createDrop(me, '');
      ok(!hasJudgePass(), 'pass dropped');
      const drops = api.state.requests.filter((r) => r.url.endsWith('/drops'));
      eq(drops.length, 2);
      eq(header(drops[0], 'X-Mutis-Judge'), PASS);
      eq(header(drops[1], 'X-Mutis-Judge'), null);
      ok(bodyOf(drops[1]).pow.nonce, 'the retry carries a PoW');
    } finally {
      setJudgePass(null);
      api.restore();
    }
  }],
  ['setJudgePass takes only a pass; prefetchPow does nothing while one is set', async () => {
    for (const bad of ['judge-short', `${PASS}x`, `${PASS}\nX-Other: 1`, 'not-a-pass-at-all-1234567890']) {
      await rejects(async () => setJudgePass(bad), TypeError, bad);
    }
    const api = installFakeApi();
    try {
      setJudgePass(PASS);
      prefetchPow('upload');
      await new Promise((r) => setTimeout(r, 50));
      eq(api.state.requests.length, 0);
    } finally {
      setJudgePass(null);
      api.restore();
    }
    ok(!hasJudgePass());
  }],
  ['password-only link after 3 wrong tries: the next try solves the PoW the server asks for, then opens', async () => {
    const api = installFakeApi();
    try {
      const item = await sealItem({ text: 'meet at the stage door' }, { anonymous: true, expiresAt: in1h() });
      const link = await createLink(item, { mode: 'password', password: 'stage-door-lantern-11', origin: FAKE_ORIGIN });
      const status = await linkStatus(link.shareId);
      for (const wrong of ['stage-door-1', 'stage-door-2', 'stage-door-3']) {
        await rejects(async () => peek(link.shareId, await accessFor(status, { password: wrong })), (e) => e.code === 'bad_access');
      }
      const access = await accessFor(status, { password: 'stage-door-lantern-11' });
      await peek(link.shareId, access);
      const opened = await openItem(link.shareId, access);
      eq(opened.meta.kind, 'text');
      const tries = api.state.requests.filter((r) => /\/(peek|open)$/.test(r.url));
      eq(tries.map((r) => Boolean(bodyOf(r).pow)).join(','), 'false,false,false,false,true,false,true', 'refused without a PoW, then sent with one');
    } finally {
      api.restore();
    }
  }],
];
