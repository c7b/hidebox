// SPDX-License-Identifier: MIT
// The library against the real API, not the in-memory fake: `node-run.mjs --api <origin>`, which
// run_all.py points at `server/bin/mutis-api --dev --pow-bits 8` after putting a judge pass in its
// database (MUTIS_JUDGE_PASS). The dev server's chain is fake, so chain flows end at "the job is done".
import { b64uDecode } from '../lib/b64.js';
import { concat } from '../lib/bytes.js';
import { randomBytes } from '../lib/crypto.js';
import { ApiError, completeUpload, config } from '../lib/api.js';
import { adoptItem, getMe } from '../lib/api-locker.js';
import { SealError, TEXT_MAX_CHARS, createLink, sealItem } from '../lib/seal.js';
import { accessFor, fetchContent, linkStatus, openItem, peek } from '../lib/open.js';
import { createIdentity } from '../lib/identity.js';
import { authHeaders, ensureSession } from '../lib/session.js';
import { closeDrop, createDrop, getDrop, leaveInDrop } from '../lib/drop.js';
import { waitJob } from '../lib/courier.js';
import { newRandomKeys } from '../lib/ootle.js';
import { deliver } from '../lib/wallet.js';
import { inboxState, scan, watch } from '../lib/scan.js';
import { hasJudgePass, setJudgePass } from '../lib/pow.js';
import { set } from '../lib/store.js';
import { coarseExpiry } from '../../shared/dates.js';
import { eq, ok, rejects } from './harness.js';

export const env = 'contract';

const now = () => Math.floor(Date.now() / 1000);
const text = (parts) => new TextDecoder().decode(concat(...parts));
const origin = async () => (await config()).origin;

// Records method, path and status of every request while fn runs.
async function recording(fn) {
  const realFetch = globalThis.fetch;
  const log = [];
  globalThis.fetch = async (input, init = {}) => {
    const res = await realFetch(input, init);
    log.push({ method: init.method ?? 'GET', path: new URL(String(input)).pathname.replace('/api/v1', ''), status: res.status, headers: init.headers ?? {} });
    return res;
  };
  try {
    return { result: await fn(), log };
  } finally {
    globalThis.fetch = realFetch;
  }
}

async function receive(link, access) {
  await peek(link.shareId, access);
  const opened = await openItem(link.shareId, access);
  return { opened, parts: await fetchContent(opened) };
}

let me;

export default [
  ['config: the gate values are strings, the memo origins include ours, the text limit is this library\'s', async () => {
    const cfg = await config();
    ok(['direct', 'relay'].includes(cfg.send_mode), cfg.send_mode);
    ok(['sidecar', 'chromium', 'wallet'].includes(cfg.amount_proof), String(cfg.amount_proof));
    ok(cfg.memo_origins.includes(cfg.origin));
    eq(cfg.text_max_chars, TEXT_MAX_CHARS);
    return `send_mode=${cfg.send_mode} amount_proof=${cfg.amount_proof}`;
  }],
  ['anonymous text, Once: the item keeps its 20 h expiry (rounded up to the hour) and the link inherits it; opens once, then burned', async () => {
    const expiresAt = now() + 20 * 3600;
    const item = await sealItem({ text: 'hello mutis ✓' }, { anonymous: true, expiresAt });
    eq(item.expiresAt, expiresAt);
    ok(item.uploadExpiresAt <= now() + 7200 + 5, 'the 2 h upload session is reported separately');
    const link = await createLink(item, { origin: await origin() });
    eq(link.expiresAt, coarseExpiry(expiresAt), 'link expiry = item expiry, stored to the hour');
    const access = await accessFor(await linkStatus(link.shareId), { s: link.s });
    const { opened, parts } = await receive(link, access);
    eq(text(parts), 'hello mutis ✓');
    ok(opened.burned);
    const e = await rejects(() => openItem(link.shareId, access), (x) => x instanceof ApiError && x.code === 'gone');
    return `second open: ${e.code}/${e.details.reason}`;
  }],
  ['6 MiB file: two chunks, ticket and byte ranges, 3 views', async () => {
    const data = randomBytes(6 * 1024 * 1024 + 7);
    const item = await sealItem({ file: new Blob([data]), name: 'photo.bin', type: 'application/octet-stream', mtime: null }, { anonymous: true, expiresAt: now() + 3600 });
    eq(item.chunkCount, 2);
    const link = await createLink(item, { origin: await origin(), maxViews: 3 });
    const { opened, parts } = await receive(link, await accessFor(await linkStatus(link.shareId), { s: link.s }));
    ok(opened.ticket && !opened.inline, 'ranged download');
    eq(opened.viewsLeft, 2);
    ok(concat(...parts).every((b, i) => b === data[i]), 'same bytes');
  }],
  ['link + password: the wrong password is refused, the right one opens', async () => {
    const item = await sealItem({ text: 'pw secret' }, { anonymous: true, expiresAt: now() + 3600 });
    const link = await createLink(item, { origin: await origin(), mode: 'link_password', password: 'correct horse', maxViews: 2 });
    const status = await linkStatus(link.shareId);
    const s0 = b64uDecode(link.fragment.slice(1));
    await rejects(async () => peek(link.shareId, await accessFor(status, { s0, password: 'nope' })), (e) => e.code === 'bad_access');
    eq(text((await receive(link, await accessFor(status, { s0, password: 'correct horse' }))).parts), 'pw secret');
  }],
  ['password only: after 3 wrong tries the server says wait, then wants a PoW; the library solves it and opens', async () => {
    const item = await sealItem({ text: 'po secret' }, { anonymous: true, expiresAt: now() + 3600 });
    const link = await createLink(item, { origin: await origin(), mode: 'password', password: 'a long passphrase here' });
    eq(link.fragment, null);
    const status = await linkStatus(link.shareId);
    for (const wrong of ['guess one', 'guess two', 'guess three']) {
      await rejects(async () => peek(link.shareId, await accessFor(status, { password: wrong })), (e) => e.code === 'bad_access');
    }
    const access = await accessFor(status, { password: 'a long passphrase here' });
    const wait = await rejects(() => peek(link.shareId, access), (e) => e.code === 'pow_required' && e.retryAfter > 0);
    await new Promise((r) => setTimeout(r, (wait.retryAfter + 1) * 1000));
    const { result, log } = await recording(() => receive(link, access));
    eq(text(result.parts), 'po secret');
    ok(log.some((r) => r.path === '/pow'), 'a PoW was solved');
    return `waited ${wait.retryAfter} s`;
  }],
  ['Stop: an aborted upload ends as SealError "aborted" and the server deletes it', async () => {
    const stop = new AbortController();
    // Four chunks: the fourth starts only after one of the first three is done, which is when Stop is pressed.
    const { result, log } = await recording(() => rejects(() => sealItem({ file: new Blob([randomBytes(13 * 1024 * 1024)]), name: 'big.bin', type: '' },
      { anonymous: true, expiresAt: now() + 3600, signal: stop.signal, onPhase: (phase, f) => phase === 'uploading' && f > 0 && stop.abort() }), SealError));
    eq(result.code, 'aborted');
    const del = log.find((r) => r.method === 'DELETE');
    eq(del?.status, 204, 'DELETE /uploads/{id}');
    const uploadId = del.path.split('/').pop();
    await rejects(() => completeUpload(uploadId, {}), (e) => e.status === 404 || e.status === 410);
  }],
  ['locker: register with a PoW; a 7-day Bearer upload and its link without an expiry last 7 days', async () => {
    set('session', null);
    me = await createIdentity();
    const s = await ensureSession(me);
    ok(s.token && s.probation);
    ok((await getMe(authHeaders())).quota, '/me answers');
    const expiresAt = now() + 7 * 86400;
    const item = await sealItem({ text: 'locker text' }, { headers: authHeaders(), expiresAt });
    const link = await createLink(item, { origin: await origin(), maxViews: 5 });
    eq(link.expiresAt, coarseExpiry(expiresAt), 'stored to the hour');
    return `link lasts ${((link.expiresAt - now()) / 86400).toFixed(2)} days; createdSeq ${me.createdSeq}`;
  }],
  ['an anonymous item adopted into the locker with its manage token', async () => {
    const item = await sealItem({ text: 'adopt me' }, { anonymous: true, expiresAt: now() + 3600 });
    const res = await adoptItem(item.itemId, { expires_at: now() + 3 * 86400 }, { ...authHeaders(), 'X-Mutis-Manage': item.manageToken });
    ok(res, 'adopted');
  }],
  ['dead drop: created with a PoW and no session; a submitter leaves a sealed 3-view link; the job finishes; closed', async () => {
    const made = await createDrop(me, 'tips');
    const drop = await getDrop(made.drop_id);
    eq(drop.address, me.locker.address);
    const item = await sealItem({ text: 'a tip' }, { anonymous: true, dropId: drop.drop_id, expiresAt: now() + drop.limits.expiry_s });
    const link = await createLink(item, { origin: await origin(), maxViews: drop.limits.views });
    const job = await leaveInDrop(drop, link);
    const fin = await waitJob(job.job_id, { intervalMs: 1000, timeoutMs: 90000 });
    eq(fin.state, 'done');
    await closeDrop(me, 0);
    await rejects(() => getDrop(made.drop_id), (e) => e.code === 'drop_closed' || e.code === 'drop_not_found');
  }],
  ['deliver() in relay mode: our relay takes the sealed link for an address', async () => {
    const res = await deliver(me, { address: (await newRandomKeys()).address, kind: 3, blob: randomBytes(125) });
    eq(res.mode, 'relay');
    ok(res.job_id && res.not_before, 'queued');
  }],
  ['judge pass (P-12): a drop and a relay send go without a PoW; an unknown pass is dropped and the PoW comes back', async () => {
    const pass = process.env.MUTIS_JUDGE_PASS;
    ok(pass, 'run_all.py sets MUTIS_JUDGE_PASS');
    setJudgePass(pass);
    try {
      const { log } = await recording(async () => {
        await createDrop(me, 'judges');
        await deliver(me, { address: (await newRandomKeys()).address, kind: 3, blob: randomBytes(125) });
      });
      ok(!log.some((r) => r.path === '/pow'), 'no PoW');
      eq(log.filter((r) => r.headers['X-Mutis-Judge']).map((r) => `${r.method} ${r.path} ${r.status}`).join(' | '), 'POST /drops 201 | POST /courier 202');
      setJudgePass(`judge-${'0'.repeat(24)}`);
      const unknown = await recording(() => createDrop(me, 'after'));
      ok(!hasJudgePass(), 'dropped');
      eq(unknown.log.filter((r) => r.path === '/drops').map((r) => r.status).join(','), '403,201');
      ok(unknown.log.some((r) => r.path === '/pow'), 'then a PoW');
    } finally {
      setJudgePass(null);
    }
  }],
  ['inbox scan and /watch over the mirror: cursor saved; /watch starts at the epoch about 7 days back', async () => {
    const { head } = await scan(me);
    const state = await inboxState(me);
    eq(state.cursor, head);
    const w = await watch({ viewSk: me.locker.viewSk, viewPk: me.locker.viewPk });
    ok(Number.isSafeInteger(w.fromSeq) && w.fromSeq >= 0, 'start from /chain/seq');
    return `head=${head} watch from seq ${w.fromSeq}, ${w.checked} rows`;
  }],
];
