// SPDX-License-Identifier: MIT
import { b64uDecode, b64uEncode } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { identityFromSeed } from '../lib/identity.js';
import { authHeaders, ensureSession } from '../lib/session.js';
import { closeDrop, createDrop, getDrop, leaveInDrop, renameDrop } from '../lib/drop.js';
import { decodeInner, parseMemo } from '../lib/courier.js';
import { unwrapBlob } from '../lib/ootle.js';
import { set } from '../lib/store.js';
import { FAKE_ORIGIN, installFakeApi } from './fake-api.js';
import { eq, ok, rejects } from './harness.js';

export const env = 'any';

export default [
  ['session: an unknown locker registers with a PoW and gets a bearer token; its secrets stay home', async () => {
    const api = installFakeApi({ powDifficulty: 8 });
    try {
      set('session', null);
      const me = await identityFromSeed(randomBytes(32));
      const s = await ensureSession(me);
      ok(s.token && s.probation);
      ok(authHeaders().Authorization.startsWith('Bearer '));
      const reg = api.state.requests.find((r) => r.url.endsWith('/auth/register'));
      const body = JSON.parse(new TextDecoder().decode(reg.body));
      ok(body.pow.challenge && body.pow.nonce, 'solved PoW attached');
      ok(!JSON.stringify(api.state.requests.map((r) => new TextDecoder().decode(r.body))).includes(b64uEncode(me.seed)), 'no seed');
      eq(await ensureSession(me), s, 'cached for the page');
    } finally {
      api.restore();
    }
  }],
  ['dead drop: create (PoW, no session), leave a sealed link, owner opens it, close with the manage token', async () => {
    const api = installFakeApi({ powDifficulty: 8 });
    try {
      const owner = await identityFromSeed(randomBytes(32));
      const made = await createDrop(owner, 'Tips for the newsroom');
      ok(made.url.endsWith(made.drop_id));
      eq(owner.dropIndex, 1);
      const posted = api.state.requests.find((r) => r.url.endsWith('/drops'));
      ok(!posted.headers.some(([k]) => k === 'authorization'), 'no session on drop creation');
      const drop = await getDrop(made.drop_id);
      eq(drop.address, owner.locker.address);
      const link = { shareId: b64uEncode(randomBytes(16)), s: randomBytes(32) };
      const job = await leaveInDrop(drop, link);
      ok(job.job_id);
      const sent = api.state.courier.at(-1);
      eq(sent.to, 'drop');
      eq(sent.address, owner.locker.address);
      const parsed = parseMemo({ Message: sent.memo }, [FAKE_ORIGIN]);
      const inner = decodeInner(await unwrapBlob(owner, parsed.blob, 3));
      eq(inner.shareId, link.shareId);
      ok(inner.isDeadDrop);
      eq(b64uEncode(inner.ref16), drop.tag);
      await renameDrop(owner, 0, 'Council');
      eq(owner.drops[0].label, 'Council');
      eq((await getDrop(made.drop_id)).label, 'Council');
      await closeDrop(owner, 0);
      eq(owner.drops[0].state, 'closed');
      await rejects(() => getDrop(made.drop_id), (e) => e.code === 'drop_closed');
      ok(b64uDecode(drop.tag).length === 16);
    } finally {
      api.restore();
    }
  }],
];
