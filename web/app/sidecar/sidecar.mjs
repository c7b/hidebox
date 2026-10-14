// SPDX-License-Identifier: MIT
// mutis verifier sidecar (§3.4.6): the same browser library and official ootle-wasm, under Node 20's
// permission model (no file writes, no child processes, no workers). One JSON request per stdin line,
// one response per stdout line, hex for bytes. stderr carries fixed strings only, never data. Secrets
// (receiver/robot view keys arriving per request, canary keys) stay in this process's memory.
//
//   node --experimental-permission --allow-fs-read=<dir> --disallow-code-generation-from-strings sidecar.mjs
import { createInterface } from 'node:readline';
import { loadLib, readSidecarJson } from './loader.mjs';

const VERSION = 'mutis-sidecar/1';
const MAX_LINE = 8 * 1024 * 1024;
const CANARY_KEEP = 48;

let lib;
try {
  lib = await loadLib();
} catch {
  process.stderr.write('mutis-sidecar: could not load ootle-wasm (hash mismatch or missing files)\n');
  process.exit(2);
}
const { ootle, api, apiLocker, b64, courier, crypto, seal } = lib;
const { hex, unhex, b64uEncode } = b64;

class RequestError extends Error {}

const need = (cond) => { if (!cond) throw new RequestError('bad_request'); };
const hexField = (v, len) => {
  need(typeof v === 'string' && v.length === len * 2 && /^[0-9a-f]+$/.test(v));
  return unhex(v);
};

function keysHex(k) {
  return { owner_sk: hex(k.ownerSk), view_sk: hex(k.viewSk), owner_pk: hex(k.ownerPk), view_pk: hex(k.viewPk), address: k.address };
}

async function scanRows(viewSk, rows) {
  const found = [];
  for (const row of rows) {
    need(row && typeof row.id === 'string' && typeof row.nonce === 'string' && typeof row.enc === 'string');
    const d = await ootle.tryDecryptUtxo(viewSk, row);
    if (d) found.push({ id: row.id, value_ut: d.value.toString(), memo: d.memo });
  }
  return found;
}

// G4: the official unblindOutput must reject a payload that doesn't open its commitment.
async function selftest() {
  const v = readSidecarJson('selftest.json');
  const cases = [];
  for (const u of v.known_good) {
    const d = await ootle.tryDecryptUtxo(unhex(u.view_sk), u);
    cases.push({ name: `real output ${u.id.slice(-8)} opens`, passed: d !== null && d.value.toString() === u.value_ut });
  }
  for (const c of v.crafted) {
    cases.push({ name: `rejected: ${c.name}`, passed: (await ootle.tryDecryptUtxo(unhex(c.view_sk), c)) === null });
  }
  // A fresh pair made here: the genuine output opens, the swapped one doesn't.
  const k = await ootle.newRandomKeys();
  const w = ootle.bindings();
  const mk = (amount) => JSON.parse(w.createStealthOutputWitness(ootle.NETWORK_BYTE, k.ownerPk, k.viewPk, amount, ootle.TARI_RESOURCE, null, null, null, 0n));
  const st = w.generateStealthOutputsStatement(JSON.stringify([mk(1000n), mk(5000n)]), 0n, new Uint8Array(32));
  const [a, b] = JSON.parse(st.statement_json).outputs.map((o) => o.output);
  st.free();
  const id = (o) => `utxo_${'01'.repeat(32)}_${o.commitment}`;
  const genuine = await ootle.tryDecryptUtxo(k.viewSk, { id: id(b), nonce: b.sender_public_nonce, enc: b.encrypted_data });
  const swapped = await ootle.tryDecryptUtxo(k.viewSk, { id: id(a), nonce: b.sender_public_nonce, enc: b.encrypted_data });
  cases.push({ name: 'fresh genuine output opens', passed: genuine?.value === 5000n });
  cases.push({ name: 'fresh swapped payload rejected', passed: swapped === null });
  // R1: a view key proves the amount, not who can spend it. Both outputs below open with our view key
  // and prove their value; only the genuine one carries the one-time key our owner key derives.
  const own = v.ownership;
  const ownerSk = unhex(own.owner_sk);
  for (const [name, row, ours] of [['genuine', own.genuine, true], ['not ours', own.not_ours, false]]) {
    const d = await ootle.tryDecryptUtxo(unhex(own.view_sk), row);
    cases.push({ name: `ownership KAT: ${name} output opens with our view key`, passed: d !== null && d.value.toString() === row.value_ut });
    cases.push({ name: `ownership KAT: ${name} output ${ours ? 'is' : 'is not'} spendable by our owner key`, passed: (oneTimeKeyHex(ownerSk, unhex(row.nonce)) === row.auth_key) === ours });
  }
  const other = await ootle.newRandomKeys();
  const fake = JSON.parse(w.createStealthOutputWitness(ootle.NETWORK_BYTE, other.ownerPk, k.viewPk, 7000n, ootle.TARI_RESOURCE, null, null, null, 0n));
  const st2 = w.generateStealthOutputsStatement(JSON.stringify([fake]), 0n, new Uint8Array(32));
  const [f] = JSON.parse(st2.statement_json).outputs;
  st2.free();
  const opened = await ootle.tryDecryptUtxo(k.viewSk, { id: id(f.output), nonce: f.output.sender_public_nonce, enc: f.output.encrypted_data });
  cases.push({ name: 'fresh output for another owner opens with our view key but is not ours', passed: opened?.value === 7000n && oneTimeKeyHex(k.ownerSk, unhex(f.output.sender_public_nonce)) !== f.auth.Key });
  // Pay to open: a sales view key sealed to our receiver opens only with the watch flag, the reference of
  // exactly that address and a key that is the address's view key.
  const seller = await ootle.newRandomKeys();
  const shareId = b64uEncode(new Uint8Array(16));
  const sealFor = async (flags, addr, key) => hex(await courier.sealDelivery(k.address, { shareId, s: key, flags, ref16: await watchRef(addr) }, 3));
  const ask = (blob) => openWatchKey({ blob, owner_sk: hex(k.ownerSk), view_sk: hex(k.viewSk), address: seller.address });
  const good = await ask(await sealFor(0x08, seller.address, seller.viewSk));
  cases.push({ name: 'sealed sales view key opens', passed: good.view_sk === hex(seller.viewSk) });
  for (const [name, flags, addr, key] of [['without the watch flag', 0x04, seller.address, seller.viewSk],
    ['for another address', 0x08, other.address, seller.viewSk], ['with a key not the address\'s', 0x08, seller.address, other.viewSk]]) {
    let refused = false;
    try { await ask(await sealFor(flags, addr, key)); } catch (e) { refused = e instanceof RequestError; }
    cases.push({ name: `sealed sales view key refused ${name}`, passed: refused });
  }
  return { passed: cases.every((c) => c.passed), cases };
}

// R1: the one-time public key (c + k)·G of a stealth output, from the receiver's owner key and the
// output's public nonce. It equals the output's `auth.Key` only when that owner key can spend it.
function oneTimeKeyHex(ownerSk, nonce) {
  const w = ootle.bindings();
  const secret = w.stealthDhSecret(ootle.NETWORK_BYTE, ownerSk, nonce);
  try {
    return hex(w.publicKeyFromSecretKey(secret));
  } finally {
    secret.fill(0);
  }
}

const canaries = new Map();

function canaryText(n, sealedAt) {
  const head = `mutis canary #${n}. Sealed ${new Date(sealedAt * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z')}. `
    + 'If you can read this without the key, we failed. Drop a file. Mutis.\n';
  const alphabet = 'abcdefghijklmnopqrstuvwxyz234567';
  const pad = Array.from(crypto.randomBytes(4000 - head.length), (b) => alphabet[b & 31]).join('');
  return head + pad;
}

async function canary({ n, canary_token: token, robot_address: robot }) {
  need(Number.isSafeInteger(n) && n >= 0 && typeof token === 'string' && /^[A-Za-z0-9_-]{43}$/.test(token));
  need(ootle.classifyAddressInput(robot) === 'ootle_testnet');
  api.configureApi({ origin: process.env.MUTIS_API, headers: { 'X-Mutis-Canary': token } });
  const sealedAt = Math.floor(Date.now() / 1000);
  const item = await seal.sealItem({ text: canaryText(n, sealedAt) }, { expiresAt: sealedAt + 172800 });
  const link = await seal.createLink(item, { mode: 'link', maxViews: 3, expiresAt: sealedAt + 86400 });
  const blob = await courier.sealDelivery(robot, link, 3);
  const job = await apiLocker.postCourier({ to: 'address', address: robot, kind: 3, blob: b64uEncode(blob), evidence: true });
  canaries.set(n, { fk: item.fk, sealedAt });
  if (canaries.size > CANARY_KEEP) canaries.delete(canaries.keys().next().value);
  return { item_id: item.itemId, share_id: link.shareId, sealed_at: sealedAt, job_id: job.job_id };
}

// Health check: open a delivery found in the mirror with the robot locker's keys. Returns the access
// token (not the link secret) so the health check can open the link once through the real API.
async function openDelivery({ memo, owner_sk, view_sk, origins }) {
  const text = typeof memo === 'string' ? memo : memo?.Message;
  need(typeof text === 'string');
  const allowed = Array.isArray(origins) ? origins : [/^(https?:\/\/[^/]+)\/t#/.exec(text)?.[1]].filter(Boolean);
  const parsed = courier.parseMemo({ Message: text }, allowed);
  if (!parsed) throw new RequestError('not_a_delivery');
  const ownerSk = hexField(owner_sk, 32);
  const viewSk = hexField(view_sk, 32);
  const w = ootle.bindings();
  const keys = { ownerSk, viewSk, ownerPk: w.publicKeyFromSecretKey(ownerSk), viewPk: w.publicKeyFromSecretKey(viewSk) };
  let inner;
  try {
    inner = courier.decodeInner(await ootle.unwrapBlob(keys, parsed.blob, parsed.kind));
  } catch {
    throw new RequestError('cannot_open');
  }
  const { accessToken } = await lib.share.shareKeys(inner.s);
  return { share_id: inner.shareId, flags: inner.flags, ref: hex(inner.ref16), access_token: b64uEncode(accessToken) };
}

// Pay to open (16-drive-architecture §1.5): a seller's sales view key, sealed (kind 3) to our receiver by
// the seller's drive. Only the chain worker asks, with the receiver keys; the key goes back to its memory.
// The blob must carry the watch flag, the reference of exactly this address, and a key whose public half
// is the address's view key, so a drive can't make us watch an address it doesn't hold the key of.
async function watchRef(address) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode('mutis-watch-v1' + address));
  return new Uint8Array(digest).slice(0, 16);
}

async function openWatchKey({ blob, owner_sk, view_sk, address }) {
  const sealed = hexField(blob, 125);
  need(typeof address === 'string' && ootle.classifyAddressInput(address) === 'ootle_testnet');
  const ownerSk = hexField(owner_sk, 32);
  const viewSk = hexField(view_sk, 32);
  const w = ootle.bindings();
  const keys = { ownerSk, viewSk, ownerPk: w.publicKeyFromSecretKey(ownerSk), viewPk: w.publicKeyFromSecretKey(viewSk) };
  let inner;
  try {
    inner = courier.decodeInner(await ootle.unwrapBlob(keys, sealed, 3));
  } catch {
    throw new RequestError('cannot_open');
  } finally {
    ownerSk.fill(0);
    viewSk.fill(0);
  }
  const ref = await watchRef(address);
  const { viewPk } = ootle.decodeAddress(address);
  const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
  if (inner.flags !== 0x08 || !same(inner.ref16, ref) || !same(w.publicKeyFromSecretKey(inner.s), viewPk)) {
    inner.s.fill(0);
    throw new RequestError('bad_key');
  }
  const out = hex(inner.s);
  inner.s.fill(0);
  return { view_sk: out };
}

const handlers = {
  hello: async () => ({ version: VERSION, wasm_sha256: lib.wasmSha256, node: process.version, permission: Boolean(process.permission) }),
  newKeys: async () => keysHex(await ootle.newRandomKeys()),
  decoyAddress: async () => ({ address: (await ootle.newRandomKeys()).address }),
  scan: async (r) => {
    need(Array.isArray(r.utxos));
    return { found: await scanRows(hexField(r.view_sk, 32), r.utxos) };
  },
  // R1: the chain worker compares this with the indexer's `auth.Key` before it credits a payment.
  oneTimeKey: async (r) => {
    const ownerSk = hexField(r.owner_sk, 32);
    const nonce = hexField(r.nonce, 32);
    let key;
    try {
      key = oneTimeKeyHex(ownerSk, nonce);
    } catch {
      throw new RequestError('bad_point');
    } finally {
      ownerSk.fill(0);
    }
    return { public_key: key };
  },
  openWatchKey,
  selftest,
  canary,
  openDelivery,
  // P1: "yesterday's key". Only canaries sealed by this process are known: after a restart the
  // answer is not_found, and the site shows that reveal as missed.
  reveal: async ({ n }) => {
    const c = canaries.get(n);
    if (!c) throw new RequestError('not_found');
    return { n, sealed_at: c.sealedAt, fk: b64uEncode(c.fk) };
  },
};

async function handle(line) {
  let req;
  try {
    req = JSON.parse(line);
  } catch {
    return { id: null, ok: false, error: 'bad_json' };
  }
  const id = Number.isSafeInteger(req?.id) ? req.id : null;
  const fn = Object.hasOwn(handlers, req?.cmd) ? handlers[req.cmd] : null;
  if (!fn) return { id, ok: false, error: 'unknown_cmd' };
  try {
    return { id, ok: true, ...(await fn(req)) };
  } catch (e) {
    if (e instanceof RequestError) return { id, ok: false, error: e.message };
    if (e instanceof api.ApiError) return { id, ok: false, error: `api_${e.code}` };
    return { id, ok: false, error: 'internal' };
  }
}

// Requests run one at a time, in order, so responses come back in request order too.
let queue = Promise.resolve();
const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', (line) => {
  queue = queue.then(async () => {
    const res = line.length > MAX_LINE ? { id: null, ok: false, error: 'too_large' } : await handle(line);
    process.stdout.write(JSON.stringify(res) + '\n');
  });
});
rl.on('close', () => queue.then(() => process.exit(0)));
process.stderr.write('mutis-sidecar: ready\n');
