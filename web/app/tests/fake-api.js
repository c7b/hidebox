// SPDX-License-Identifier: MIT
// An in-memory stand-in for the §6 API, installed over fetch for one origin, so the protocol modules
// can be tested end to end without the server. It follows the contract's checks that matter to the
// client (hashed access tokens, link proofs, atomic views, byte ranges, upload-session vs item expiry,
// PoW or judge pass on gated routes) and records every request so tests can prove no secret ever
// leaves the client. contract.test.js runs the same flows against the real server (run_all.py).
import { b64uDecode, b64uEncode, hex } from '../lib/b64.js';
import { concat, equal } from '../lib/bytes.js';
import { randomBytes, sha256 } from '../lib/crypto.js';
import { chunkRange } from '../lib/format.js';
import { configureApi } from '../lib/api.js';

export const FAKE_ORIGIN = 'https://fake.mutis.test';
const id22 = () => b64uEncode(randomBytes(16));
const now = () => Math.floor(Date.now() / 1000);
const UPLOAD_TTL_S = 7200;
const ANON_DEFAULT_EXPIRY_S = 86400;
const PASSWORD_POW_AFTER = 3;

function json(status, body) {
  return new Response(body === null ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
const fail = (status, code, details = {}) => json(status, { error: { code, message: code, details } });

// `substates` maps utxo ids to {nonce, enc} for the indexer pass-through (chain/ix) used by wallet.js.
// `judgePasses` maps pass codes to uses left. `txDecision`: what transactions/{id}/result answers
// ('Commit', a {Reject: …} object, or null for "not final yet").
export function installFakeApi({ mirror = [], config = {}, powDifficulty = 2, substates = new Map(), judgePasses = new Map(), txDecision = 'Commit', epoch = 12000, sponsorStatus = 202 } = {}) {
  const realFetch = globalThis.fetch;
  const state = { uploads: new Map(), items: new Map(), shares: new Map(), tickets: new Map(), drops: new Map(), jobs: new Map(), requests: [], courier: [], submitted: [], judged: [], sponsored: [] };

  // PoW-gated routes accept a judge pass instead (P-12); budgeted sends spend one of its uses.
  function powGate(req, body, { spend = false, purpose = null } = {}) {
    const pass = req.headers.get('X-Mutis-Judge');
    if (pass !== null) {
      const left = judgePasses.get(pass) ?? 0;
      if (left <= 0) return fail(403, 'forbidden', { judge: 'invalid' });
      if (spend) judgePasses.set(pass, left - 1);
      state.judged.push(new URL(req.url).pathname);
      return null;
    }
    if (!purpose) return null;
    return body.pow?.challenge && body.pow?.nonce ? null : fail(428, 'pow_required', { purpose, difficulty: powDifficulty });
  }

  async function access(share, req) {
    const token = req.headers.get('X-Mutis-Access');
    if (share.mode === 'link_password') {
      const proof = req.headers.get('X-Mutis-Link');
      if (!proof || !equal(await sha256(b64uDecode(proof)), share.link_hash)) return fail(403, 'bad_link');
    }
    if (share.mode === 'password' && share.fails >= PASSWORD_POW_AFTER) {
      const body = await req.clone().json().catch(() => ({}));
      if (!body.pow?.challenge) return fail(428, 'pow_required', { purpose: 'password', difficulty: powDifficulty });
    }
    if (!token || !equal(await sha256(b64uDecode(token)), share.access_hash)) {
      share.fails++;
      return fail(403, 'bad_access');
    }
    return null;
  }

  function opened(item) {
    const inline = item.sizeStored <= 262144;
    const ticket = inline ? null : b64uEncode(randomBytes(32));
    if (ticket) state.tickets.set(ticket, item);
    return { ticket, ticket_expires_at: ticket ? now() + 1800 : null, inline_ct: inline ? b64uEncode(item.blob) : null };
  }

  const routes = [
    ['GET', /^\/config$/, () => json(200, {
      origin: FAKE_ORIGIN, memo_origins: [FAKE_ORIGIN], send_mode: 'relay', text_max_chars: 10000,
      features: { relay_send: true, direct_send: false, sponsor: false, demo_pay: true }, courier: { amount_ut: '1000' },
      ootle: { mirror_start_seq: 1 }, ...config,
    })],
    ['POST', /^\/pow$/, () => {
      const challenge = concat(Uint8Array.of(1, 1, powDifficulty, 0), new Uint8Array(4).fill(0x7f), randomBytes(28));
      return json(200, { challenge: b64uEncode(challenge), difficulty: powDifficulty, expires_at: now() + 300 });
    }],
    ['POST', /^\/uploads$/, async (req) => {
      const b = await req.json();
      const anonymous = !req.headers.has('Authorization') && !req.headers.has('X-Mutis-Canary');
      const denied = anonymous && powGate(req, b, { purpose: 'upload' });
      if (denied) return denied;
      const expiresAt = b.retention === 'kept' ? null : b.expires_at ?? now() + ANON_DEFAULT_EXPIRY_S;
      const upload = { header: b64uDecode(b.header), metaCt: b64uDecode(b.meta_ct), chunkCount: b.chunk_count, sizeStored: b.size_stored, chunks: new Map(), hashes: [], dropId: b.drop_id, retention: b.retention, ownerWrap: b.owner_wrap };
      const itemId = id22();
      const uploadId = id22();
      state.uploads.set(uploadId, { ...upload, itemId });
      const manage = randomBytes(32);
      state.items.set(itemId, { ...upload, manageHash: await sha256(manage), ready: false, expiresAt });
      // Like the server: `expires_at` here is when this upload session ends, not the item's expiry.
      return json(201, { upload_id: uploadId, item_id: itemId, manage_token: b64uEncode(manage), expires_at: now() + UPLOAD_TTL_S });
    }],
    ['PUT', /^\/uploads\/([\w-]+)\/chunks\/(\d+)$/, async (req, [, uploadId, index]) => {
      const up = state.uploads.get(uploadId);
      if (!up) return fail(404, 'not_found');
      const body = new Uint8Array(await req.arrayBuffer());
      const { start, end } = chunkRange(Number(index), up.chunkCount, up.sizeStored);
      if (body.length !== end - start) return fail(400, 'bad_length');
      const h = await sha256(body);
      if (b64uEncode(h) !== req.headers.get('X-Mutis-Chunk-SHA256')) return fail(422, 'hash_mismatch');
      up.chunks.set(Number(index), body);
      up.hashes[Number(index)] = h;
      return json(204, null);
    }],
    ['POST', /^\/uploads\/([\w-]+)\/complete$/, async (req, [, uploadId]) => {
      const up = state.uploads.get(uploadId);
      const missing = [...Array(up.chunkCount).keys()].filter((i) => !up.chunks.has(i));
      if (missing.length) return fail(409, 'missing_chunks', { missing });
      const item = state.items.get(up.itemId);
      item.blob = concat(...[...Array(up.chunkCount).keys()].map((i) => up.chunks.get(i)));
      item.ready = true;
      return json(200, { item_id: up.itemId, ct_hash: b64uEncode(await sha256(concat(...up.hashes))), size_stored: up.sizeStored });
    }],
    ['DELETE', /^\/uploads\/([\w-]+)$/, (req, [, uploadId]) => {
      const up = state.uploads.get(uploadId);
      if (!up) return fail(404, 'not_found');
      state.uploads.delete(uploadId);
      state.items.delete(up.itemId);
      return json(204, null);
    }],
    ['POST', /^\/items\/([\w-]+)\/shares$/, async (req, [, itemId]) => {
      const item = state.items.get(itemId);
      if (!item?.ready) return fail(409, 'item_not_ready');
      const b = await req.json();
      // Like the server: no expiry means the item's own; a link can't outlive its item.
      const expiresAt = b.expires_at ?? item.expiresAt;
      if (expiresAt !== null && (expiresAt <= now() || (item.expiresAt !== null && expiresAt > item.expiresAt))) {
        return fail(422, 'invalid', { field: 'expires_at' });
      }
      const shareId = id22();
      state.shares.set(shareId, {
        itemId, mode: b.mode, kdf: b.kdf, wrapped: b64uDecode(b.wrapped_key), access_hash: b64uDecode(b.access_verifier),
        link_hash: b.link_verifier ? b64uDecode(b.link_verifier) : null, max_views: b.max_views, views_used: 0, state: 'active', fails: 0,
      });
      return json(201, { share_id: shareId, path: `/s/${shareId}`, state: 'active', max_views: b.max_views, expires_at: expiresAt });
    }],
    ['GET', /^\/s\/([\w-]+)$/, (req, [, shareId]) => {
      const s = state.shares.get(shareId);
      if (!s) return fail(404, 'not_found');
      if (s.state !== 'active') return fail(410, 'gone', { reason: s.state === 'exhausted' ? 'burned' : s.state });
      return json(200, { state: 'active', mode: s.mode, needs_password: s.mode !== 'link', kdf: s.kdf });
    }],
    ['POST', /^\/s\/([\w-]+)\/peek$/, async (req, [, shareId]) => {
      const s = state.shares.get(shareId);
      if (!s) return fail(404, 'not_found');
      const denied = await access(s, req);
      if (denied) return denied;
      return json(200, { share: { id: shareId, views_left: s.max_views - s.views_used }, not_known: ['file_name', 'file_type', 'file_content', 'link_key', 'password', 'ip_address_on_disk'] });
    }],
    ['POST', /^\/s\/([\w-]+)\/open$/, async (req, [, shareId]) => {
      const s = state.shares.get(shareId);
      if (!s) return fail(404, 'not_found');
      if (s.state !== 'active') return fail(410, 'gone', { reason: 'burned' });
      const denied = await access(s, req);
      if (denied) return denied;
      const item = state.items.get(s.itemId);
      s.views_used += 1;
      const burned = s.views_used >= s.max_views;
      const wrapped = s.wrapped;
      if (burned) Object.assign(s, { state: 'exhausted', wrapped: null, access_hash: null });
      return json(200, {
        wrapped_key: b64uEncode(wrapped), header: b64uEncode(item.header), meta_ct: b64uEncode(item.metaCt), chunk_size: 4194304,
        chunk_count: item.chunkCount, size_stored: item.sizeStored, views_left: s.max_views - s.views_used, burned, ...opened(item),
      });
    }],
    ['GET', /^\/blobs\/([\w-]+)$/, (req, [, ticket]) => {
      const item = state.tickets.get(ticket);
      if (!item) return fail(404, 'not_found');
      const [, a, b] = /^bytes=(\d+)-(\d+)$/.exec(req.headers.get('Range') ?? '') ?? [];
      return new Response(item.blob.subarray(Number(a), Number(b) + 1), { status: 206 });
    }],
    ['POST', /^\/blobs\/([\w-]+)\/done$/, (req, [, ticket]) => {
      state.tickets.delete(ticket);
      return json(204, null);
    }],
    ['POST', /^\/drops$/, async (req) => {
      const b = await req.json();
      const denied = powGate(req, b, { purpose: 'drop_create' });
      if (denied) return denied;
      const dropId = Array.from(randomBytes(10), (x) => '0123456789abcdefghjkmnpqrstvwxyz'[x & 31]).join('');
      state.drops.set(dropId, { ...b, state: 'active', manage_hash: b64uDecode(b.manage_verifier) });
      return json(201, { drop_id: dropId, url: `${FAKE_ORIGIN}/d/${dropId}` });
    }],
    ['GET', /^\/drops\/(\w+)$/, (req, [, dropId]) => {
      const d = state.drops.get(dropId);
      if (!d) return fail(404, 'drop_not_found');
      if (d.state !== 'active') return fail(410, 'drop_closed', { reason: 'closed' });
      return json(200, { drop_id: dropId, state: d.state, address: d.address, tag: d.tag, label: d.label, limits: { max_file_bytes: 26214400, expiry_s: 604800, views: 3 }, today: { left: 50 } });
    }],
    ['PATCH', /^\/drops\/(\w+)$/, async (req, [, dropId]) => {
      const d = state.drops.get(dropId);
      const manage = req.headers.get('X-Mutis-Manage');
      if (!manage || !equal(await sha256(b64uDecode(manage)), d.manage_hash)) return fail(403, 'forbidden');
      Object.assign(d, await req.json());
      return json(200, { drop_id: dropId, state: d.state });
    }],
    ['POST', /^\/courier$/, async (req) => {
      const b = await req.json();
      if (b64uDecode(b.blob).length !== 125) return fail(422, 'bad_blob');
      const denied = powGate(req, b, { spend: true, purpose: b.to === 'drop' ? 'courier' : null });
      if (denied) return denied;
      const jobId = id22();
      const address = b.to === 'drop' ? state.drops.get(b.drop_id)?.address : b.address;
      state.courier.push({ ...b, address, memo: `${FAKE_ORIGIN}/t#${b.kind}${b.blob}` });
      state.jobs.set(jobId, { kind: 'courier', state: 'done', not_before: now(), result: { tx_id: 'ab'.repeat(32) }, error: null });
      return json(202, { job_id: jobId, not_before: now() });
    }],
    ['GET', /^\/jobs\/([\w-]+)$/, (req, [, jobId]) => json(200, state.jobs.get(jobId))],
    ['POST', /^\/auth\/session$/, () => fail(404, 'unknown_identity')],
    ['POST', /^\/auth\/register$/, async (req) => {
      const b = await req.json();
      const denied = powGate(req, b, { purpose: 'register' });
      if (denied) return denied;
      return json(201, { token: b64uEncode(randomBytes(32)), expires_at: now() + 86400, identity_id: b.identity_id, probation: true });
    }],
    ['POST', /^\/sponsor$/, async (req) => {
      const b = await req.json();
      const denied = powGate(req, b, { spend: true, purpose: 'sponsor' });
      if (denied) return denied;
      state.sponsored.push(b.wallet_address);
      return sponsorStatus === 202 ? json(202, { job_id: id22() }) : fail(sponsorStatus, 'rate_limited');
    }],
    ['GET', /^\/chain\/utxos$/, (req) => {
      const u = new URL(req.url);
      const after = Number(u.searchParams.get('after'));
      const limit = Number(u.searchParams.get('limit'));
      const items = mirror.filter((r) => r.seq > after).slice(0, limit);
      return json(200, { items, next: items.at(-1)?.seq ?? after, head: mirror.at(-1)?.seq ?? 0 });
    }],
    ['GET', /^\/chain\/seq$/, (req) => {
      const e = Number(new URL(req.url).searchParams.get('epoch'));
      return json(200, { seq: mirror.filter((r) => r.epoch < e).at(-1)?.seq ?? 0 });
    }],
    ['GET', /^\/me\/items$/, () => json(200, {
      items: [...state.items].filter(([, i]) => i.retention === 'kept' && i.ready).map(([itemId, i]) => ({
        item_id: itemId, retention: 'kept', size_stored: i.sizeStored, chunk_count: i.chunkCount,
        header: b64uEncode(i.header), meta_ct: b64uEncode(i.metaCt), owner_wrap: i.ownerWrap, shares: [],
      })),
      next: null,
    })],
    ['POST', /^\/me\/items\/([\w-]+)\/open$/, (req, [, itemId]) => json(200, opened(state.items.get(itemId)))],
    ['GET', /^\/chain\/ix\/epoch-manager\/stats$/, () => json(200, { current_epoch: epoch, consensus_epoch: epoch })],
    ['GET', /^\/chain\/ix\/substates\/(utxo_\w+)$/, (req, [, id]) => {
      const o = substates.get(id);
      if (!o) return fail(404, 'not_found');
      const value = { Utxo: { output: { output: { public_nonce: o.nonce, encrypted_data: o.enc } }, is_frozen: Boolean(o.frozen) } };
      // tari_indexer 0.47.0's answer; `o.indexer` 'older' answers in the earlier shape, 'down' as a proven spent version.
      if (o.indexer === 'older') return json(200, { version: 0, verified: true, substate: value });
      if (o.indexer === 'down') return json(200, { version: 0, state: { down: {} }, verified: true, proof: { down_proof: '' } });
      return json(200, { version: 0, state: { up: { substate: value } }, verified: true, proof: { value_hash_epoch: epoch } });
    }],
    ['POST', /^\/chain\/ix\/transactions$/, async (req) => {
      if (!req.headers.get('Authorization')) return fail(401, 'auth_required');
      const b = await req.json();
      state.submitted.push(b.transaction);
      return json(200, { transaction_id: hex(await sha256(new TextEncoder().encode(b.transaction))) });
    }],
    ['GET', /^\/chain\/ix\/transactions\/[0-9a-f]{64}\/result$/, () => json(200, {
      result: txDecision === null ? null : { Finalized: { final_decision: txDecision } },
    })],
  ];

  globalThis.fetch = async (input, init = {}) => {
    const req = new Request(input, init);
    const url = new URL(req.url);
    if (url.origin !== FAKE_ORIGIN) return realFetch(input, init);
    const body = req.method === 'GET' || req.method === 'HEAD' ? new Uint8Array() : new Uint8Array(await req.clone().arrayBuffer());
    state.requests.push({ method: req.method, url: req.url, headers: [...req.headers], body });
    const path = url.pathname.replace(/^\/api\/v1/, '');
    for (const [method, re, handler] of routes) {
      const m = re.exec(path);
      if (m && method === req.method) return handler(req, m);
    }
    return fail(404, 'not_found');
  };
  configureApi({ origin: FAKE_ORIGIN });
  return {
    state,
    restore() {
      globalThis.fetch = realFetch;
    },
  };
}
